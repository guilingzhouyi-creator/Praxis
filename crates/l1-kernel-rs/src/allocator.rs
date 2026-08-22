//! Rust resource-accounting candidates behind the Python allocator contracts.

use std::collections::BTreeMap;
use std::sync::{Mutex as StdMutex, MutexGuard, PoisonError};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::Deserialize;
use serde_json::{Value, json};

/// Dictionary-shaped result retained for a language-neutral adapter.
pub type WireMap = BTreeMap<String, Value>;

/// One allocation record owned by an agent.
#[derive(Debug, Clone, PartialEq)]
pub struct Allocation {
    /// Agent owning the reservation.
    pub agent_id: String,
    /// Resource key being reserved.
    pub resource: String,
    /// Reserved amount.
    pub amount: u64,
    /// Unix timestamp when the reservation was created.
    pub allocated_at: f64,
    /// Unix timestamp at which the reservation expires, or zero for no TTL.
    pub expires_at: f64,
    /// Optional purpose used by pressure reclamation.
    pub purpose: String,
}

/// Deployment values for the allocator mechanism.
#[derive(Debug, Clone, PartialEq)]
pub struct AllocatorConfig {
    /// Default limits copied from policy/config data.
    pub defaults: BTreeMap<String, u64>,
    /// Limit used for a resource absent from the configured defaults.
    pub fallback_limit: u64,
    /// Pressure threshold as a percentage.
    pub pressure_threshold: f64,
    /// TTL for the cached pressure result.
    pub pressure_ttl: Duration,
    /// Decimal places used for usage percentages.
    pub pct_precision: u32,
    /// Case-insensitive purpose marker eligible for local reclaim.
    pub observe_marker: String,
    /// Target resource name that means "remove from memory".
    pub disk_resource: String,
    /// Priority used when an agent has no explicit priority limit.
    pub default_priority: u64,
}

impl AllocatorConfig {
    /// Build an allocator configuration from deployment data.
    pub fn new(
        defaults: BTreeMap<String, u64>,
        fallback_limit: u64,
        pressure_threshold: f64,
        pct_precision: u32,
        observe_marker: impl Into<String>,
        disk_resource: impl Into<String>,
    ) -> Self {
        Self {
            defaults,
            fallback_limit,
            pressure_threshold,
            pressure_ttl: Duration::ZERO,
            pct_precision,
            observe_marker: observe_marker.into(),
            disk_resource: disk_resource.into(),
            default_priority: 0,
        }
    }

    /// Set the cache lifetime for pressure snapshots.
    pub fn with_pressure_ttl(mut self, pressure_ttl: Duration) -> Self {
        self.pressure_ttl = pressure_ttl;
        self
    }

    /// Set the fallback priority used by OOM victim selection.
    pub fn with_default_priority(mut self, default_priority: u64) -> Self {
        self.default_priority = default_priority;
        self
    }
}

#[derive(Debug)]
struct AllocatorState {
    limits: BTreeMap<String, BTreeMap<String, u64>>,
    allocations: BTreeMap<String, Vec<Allocation>>,
    usage: BTreeMap<String, BTreeMap<String, u64>>,
    pressure_cache: Option<(f64, WireMap, f64)>,
}

/// Thread-safe quota allocator with bounded reclamation and accounting.
pub struct Allocator {
    config: AllocatorConfig,
    state: StdMutex<AllocatorState>,
}

impl Allocator {
    /// Create an allocator using explicit limits and reclaim policy.
    pub fn new(config: AllocatorConfig) -> Self {
        Self {
            config,
            state: StdMutex::new(AllocatorState {
                limits: BTreeMap::new(),
                allocations: BTreeMap::new(),
                usage: BTreeMap::new(),
                pressure_cache: None,
            }),
        }
    }

    /// Override an agent's limit for one resource.
    pub fn set_limit(&self, agent_id: &str, resource: &str, limit: u64) -> WireMap {
        let mut state = self.lock_state();
        ensure_agent(&mut state, &self.config, agent_id);
        state
            .limits
            .entry(agent_id.to_owned())
            .or_default()
            .insert(resource.to_owned(), limit);
        ok([])
    }

    /// Allocate a resource, reclaiming expired/observe entries before OOM fallback.
    pub fn alloc(
        &self,
        agent_id: &str,
        resource: &str,
        amount: u64,
        purpose: &str,
        ttl: Option<Duration>,
    ) -> WireMap {
        let mut state = self.lock_state();
        ensure_agent(&mut state, &self.config, agent_id);
        let now = now_seconds();
        let limit = limit_for(&state, &self.config, agent_id, resource);
        let used = usage_for(&state, agent_id, resource);
        let available = limit.saturating_sub(used);
        if available < amount {
            let reclaimed = reclaim_local(
                &mut state,
                &self.config,
                agent_id,
                resource,
                amount.saturating_sub(available),
                now,
            );
            if available.saturating_add(reclaimed) >= amount {
                return record_allocation(
                    &mut state, agent_id, resource, amount, purpose, ttl, limit,
                );
            }
        } else {
            return record_allocation(&mut state, agent_id, resource, amount, purpose, ttl, limit);
        }

        let needed =
            amount.saturating_sub(limit.saturating_sub(usage_for(&state, agent_id, resource)));
        let reclaimed = reclaim_victim(&mut state, &self.config, agent_id, resource, needed);
        let used_after = usage_for(&state, agent_id, resource);
        if limit.saturating_sub(used_after).saturating_add(reclaimed) >= amount {
            return record_allocation(&mut state, agent_id, resource, amount, purpose, ttl, limit);
        }
        fail(
            &format!("{resource} exhausted ({used_after}/{limit})"),
            [
                ("used", json!(used_after)),
                ("limit", json!(limit)),
                ("pressure", json!(true)),
                ("oom", json!(true)),
            ],
        )
    }

    /// Release whole allocation records until the requested amount is met.
    pub fn free(&self, agent_id: &str, resource: &str, amount: u64) -> WireMap {
        let mut state = self.lock_state();
        ensure_agent(&mut state, &self.config, agent_id);
        let allocations = state.allocations.entry(agent_id.to_owned()).or_default();
        let mut kept = Vec::with_capacity(allocations.len());
        let mut freed = 0_u64;
        for allocation in allocations.drain(..) {
            if freed < amount && allocation.resource == resource {
                freed = freed.saturating_add(allocation.amount);
            } else {
                kept.push(allocation);
            }
        }
        *allocations = kept;
        let entry = state.usage.entry(agent_id.to_owned()).or_default();
        let current = entry.get(resource).copied().unwrap_or(0);
        entry.insert(resource.to_owned(), current.saturating_sub(freed));
        ok([("freed", json!(freed))])
    }

    /// Return current usage and limits without inserting unknown agents.
    pub fn usage(&self, agent_id: &str) -> WireMap {
        let state = self.lock_state();
        let limits = state
            .limits
            .get(agent_id)
            .cloned()
            .unwrap_or_else(|| self.config.defaults.clone());
        let mut result = WireMap::new();
        for (resource, limit) in limits {
            let used = usage_for(&state, agent_id, &resource);
            let pct = if limit == 0 {
                0.0
            } else {
                round_precision(
                    used as f64 / limit as f64 * 100.0,
                    self.config.pct_precision,
                )
            };
            result.insert(resource, json!({"used": used, "limit": limit, "pct": pct}));
        }
        result
    }

    /// Remove all allocation and limit state owned by an agent.
    pub fn cleanup_agent(&self, agent_id: &str) -> WireMap {
        let mut state = self.lock_state();
        state.limits.remove(agent_id);
        state.allocations.remove(agent_id);
        state.usage.remove(agent_id);
        ok([])
    }

    /// Return agents and resources at or above a pressure threshold.
    pub fn pressure(&self, threshold: Option<f64>) -> WireMap {
        let threshold = threshold.unwrap_or(self.config.pressure_threshold);
        let now = now_seconds();
        {
            let state = self.lock_state();
            if let Some((cached_threshold, result, cached_at)) = &state.pressure_cache
                && *cached_threshold == threshold
                && now - *cached_at < self.config.pressure_ttl.as_secs_f64()
            {
                return result.clone();
            }
        }
        let state = self.lock_state();
        let mut agents = Vec::new();
        for agent_id in state.limits.keys() {
            let usage = self.usage_locked(&state, agent_id);
            for (resource, stats) in usage {
                let pct = stats.get("pct").and_then(Value::as_f64).unwrap_or(0.0);
                if pct >= threshold {
                    agents.push(json!({
                        "agent_id": agent_id,
                        "resource": resource,
                        "used": stats.get("used").cloned().unwrap_or(json!(0)),
                        "limit": stats.get("limit").cloned().unwrap_or(json!(0)),
                        "pct": pct,
                    }));
                }
            }
        }
        let result = BTreeMap::from([
            ("under_pressure".to_owned(), json!(!agents.is_empty())),
            ("agents".to_owned(), json!(agents)),
            ("count".to_owned(), json!(agents.len())),
        ]);
        drop(state);
        let mut state = self.lock_state();
        state.pressure_cache = Some((threshold, result.clone(), now));
        result
    }

    /// Move a bounded number of allocations to a colder resource or disk.
    pub fn swap_out(
        &self,
        agent_id: &str,
        resource: &str,
        target_resource: &str,
        count: usize,
    ) -> WireMap {
        let mut state = self.lock_state();
        ensure_agent(&mut state, &self.config, agent_id);
        let allocations = state.allocations.entry(agent_id.to_owned()).or_default();
        let mut moved = 0_usize;
        let mut total = 0_u64;
        let mut kept = Vec::with_capacity(allocations.len());
        for mut allocation in allocations.drain(..) {
            if allocation.resource == resource && moved < count {
                moved += 1;
                total = total.saturating_add(allocation.amount);
                if target_resource != self.config.disk_resource {
                    allocation.resource = target_resource.to_owned();
                    kept.push(allocation);
                }
            } else {
                kept.push(allocation);
            }
        }
        *allocations = kept;
        let usage = state.usage.entry(agent_id.to_owned()).or_default();
        usage.insert(
            resource.to_owned(),
            usage
                .get(resource)
                .copied()
                .unwrap_or(0)
                .saturating_sub(total),
        );
        if target_resource != self.config.disk_resource {
            let current = usage.get(target_resource).copied().unwrap_or(0);
            usage.insert(target_resource.to_owned(), current.saturating_add(total));
        }
        ok([
            ("moved", json!(moved)),
            ("from", json!(resource)),
            ("to", json!(target_resource)),
        ])
    }

    /// Return usage snapshots for every known agent.
    pub fn summary(&self) -> WireMap {
        let state = self.lock_state();
        state
            .limits
            .keys()
            .map(|agent_id| (agent_id.clone(), json!(self.usage_locked(&state, agent_id))))
            .collect()
    }

    fn usage_locked(&self, state: &AllocatorState, agent_id: &str) -> WireMap {
        let limits = state
            .limits
            .get(agent_id)
            .cloned()
            .unwrap_or_else(|| self.config.defaults.clone());
        limits
            .into_iter()
            .map(|(resource, limit)| {
                let used = usage_for(state, agent_id, &resource);
                let pct = if limit == 0 {
                    0.0
                } else {
                    round_precision(
                        used as f64 / limit as f64 * 100.0,
                        self.config.pct_precision,
                    )
                };
                (resource, json!({"used": used, "limit": limit, "pct": pct}))
            })
            .collect()
    }

    fn lock_state(&self) -> MutexGuard<'_, AllocatorState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Resource profile used by the bounded ResourceLimiter candidate.
#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct ResourceProfile {
    /// Maximum concurrent workers.
    pub max_workers: u64,
    /// Maximum active scouts.
    pub max_scouts: u64,
    /// Maximum memory entries.
    pub max_memory: u64,
    /// Maximum token units.
    pub max_tokens: u64,
    /// Scheduling priority supplied as data.
    pub priority: u64,
}

impl ResourceProfile {
    /// Build a profile from explicit policy values.
    pub const fn new(
        max_workers: u64,
        max_scouts: u64,
        max_memory: u64,
        max_tokens: u64,
        priority: u64,
    ) -> Self {
        Self {
            max_workers,
            max_scouts,
            max_memory,
            max_tokens,
            priority,
        }
    }
}

#[derive(Debug)]
struct LimiterState {
    profiles: BTreeMap<String, ResourceProfile>,
    usage: BTreeMap<String, BTreeMap<String, i64>>,
}

/// Thread-safe per-agent resource limiter with profile injection.
pub struct ResourceLimiter {
    default_profile: ResourceProfile,
    fallback_agent: String,
    default_cost: i64,
    resource_keys: Vec<String>,
    state: StdMutex<LimiterState>,
}

impl ResourceLimiter {
    /// Create a limiter without importing Python role policy.
    pub fn new(
        default_profile: ResourceProfile,
        fallback_agent: impl Into<String>,
        resource_keys: Vec<String>,
        default_cost: i64,
    ) -> Self {
        Self {
            default_profile,
            fallback_agent: fallback_agent.into(),
            default_cost,
            resource_keys,
            state: StdMutex::new(LimiterState {
                profiles: BTreeMap::new(),
                usage: BTreeMap::new(),
            }),
        }
    }

    /// Return an agent profile, falling back to the configured default profile.
    pub fn get_profile(&self, agent_id: &str) -> WireMap {
        let state = self.lock_state();
        profile_wire(
            state
                .profiles
                .get(agent_id)
                .unwrap_or(&self.default_profile),
        )
    }

    /// Update known profile fields from a primitive map.
    pub fn set_profile(&self, agent_id: &str, fields: &BTreeMap<String, u64>) -> WireMap {
        let mut state = self.lock_state();
        let profile = state
            .profiles
            .entry(agent_id.to_owned())
            .or_insert_with(|| self.default_profile.clone());
        for (key, value) in fields {
            match key.as_str() {
                "max_workers" => profile.max_workers = *value,
                "max_scouts" => profile.max_scouts = *value,
                "max_memory" => profile.max_memory = *value,
                "max_tokens" => profile.max_tokens = *value,
                "priority" => profile.priority = *value,
                _ => {}
            }
        }
        ok([])
    }

    /// Reserve resource units when the profile limit permits them.
    pub fn check(&self, agent_id: &str, resource: &str, cost: Option<i64>) -> WireMap {
        let cost = cost.unwrap_or(self.default_cost);
        let mut state = self.lock_state();
        let profile = self.profile_for(&state, agent_id);
        let limit = match profile_limit(profile, resource) {
            Some(limit) => limit,
            None => return fail(&format!("unknown resource: {resource}"), []),
        };
        let usage = state.usage.entry(agent_id.to_owned()).or_default();
        let current = usage.get(resource).copied().unwrap_or(0);
        let requested = current.saturating_add(cost);
        let limit = i64::try_from(limit).unwrap_or(i64::MAX);
        if requested > limit {
            return fail(
                &format!("{resource} limit exceeded ({requested} > {limit})"),
                [
                    ("current", json!(current)),
                    ("limit", json!(limit)),
                    ("requested", json!(cost)),
                ],
            );
        }
        usage.insert(resource.to_owned(), requested);
        ok([("current", json!(requested)), ("limit", json!(limit))])
    }

    /// Release resource units, flooring usage at zero.
    pub fn release(&self, agent_id: &str, resource: &str, cost: Option<i64>) -> WireMap {
        let cost = cost.unwrap_or(self.default_cost);
        let mut state = self.lock_state();
        let usage = state.usage.entry(agent_id.to_owned()).or_default();
        let current = usage.get(resource).copied().unwrap_or(0);
        let current = current.saturating_sub(cost).max(0);
        usage.insert(resource.to_owned(), current);
        ok([("current", json!(current))])
    }

    /// Return current and maximum usage for all standard resource keys.
    pub fn usage(&self, agent_id: &str) -> WireMap {
        let state = self.lock_state();
        let profile = self.profile_for(&state, agent_id);
        self.resource_keys
            .iter()
            .map(|resource| {
                let current = state
                    .usage
                    .get(agent_id)
                    .and_then(|usage| usage.get(resource))
                    .copied()
                    .unwrap_or(0);
                let max = profile_limit(profile, resource).unwrap_or(0);
                (resource.clone(), json!({"current": current, "max": max}))
            })
            .collect()
    }

    /// Return usage snapshots for every configured profile.
    pub fn all_usage(&self) -> WireMap {
        let state = self.lock_state();
        state
            .profiles
            .keys()
            .map(|agent_id| (agent_id.clone(), json!(self.usage_locked(&state, agent_id))))
            .collect()
    }

    /// Drop profile and usage state for an exited process.
    pub fn cleanup_agent(&self, agent_id: &str) -> WireMap {
        let mut state = self.lock_state();
        state.profiles.remove(agent_id);
        state.usage.remove(agent_id);
        ok([])
    }

    fn usage_locked(&self, state: &LimiterState, agent_id: &str) -> WireMap {
        let profile = self.profile_for(state, agent_id);
        self.resource_keys
            .iter()
            .map(|resource| {
                let current = state
                    .usage
                    .get(agent_id)
                    .and_then(|usage| usage.get(resource))
                    .copied()
                    .unwrap_or(0);
                let max = profile_limit(profile, resource).unwrap_or(0);
                (resource.clone(), json!({"current": current, "max": max}))
            })
            .collect()
    }

    fn lock_state(&self) -> MutexGuard<'_, LimiterState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn profile_for<'a>(&'a self, state: &'a LimiterState, agent_id: &str) -> &'a ResourceProfile {
        state
            .profiles
            .get(agent_id)
            .or_else(|| state.profiles.get(&self.fallback_agent))
            .unwrap_or(&self.default_profile)
    }
}

fn ensure_agent(state: &mut AllocatorState, config: &AllocatorConfig, agent_id: &str) {
    state
        .limits
        .entry(agent_id.to_owned())
        .or_insert_with(|| config.defaults.clone());
    state.allocations.entry(agent_id.to_owned()).or_default();
    state.usage.entry(agent_id.to_owned()).or_default();
}

fn limit_for(
    state: &AllocatorState,
    config: &AllocatorConfig,
    agent_id: &str,
    resource: &str,
) -> u64 {
    state
        .limits
        .get(agent_id)
        .and_then(|limits| limits.get(resource))
        .copied()
        .or_else(|| config.defaults.get(resource).copied())
        .unwrap_or(config.fallback_limit)
}

fn usage_for(state: &AllocatorState, agent_id: &str, resource: &str) -> u64 {
    state
        .usage
        .get(agent_id)
        .and_then(|usage| usage.get(resource))
        .copied()
        .unwrap_or(0)
}

fn record_allocation(
    state: &mut AllocatorState,
    agent_id: &str,
    resource: &str,
    amount: u64,
    purpose: &str,
    ttl: Option<Duration>,
    limit: u64,
) -> WireMap {
    let used = usage_for(state, agent_id, resource);
    state
        .allocations
        .entry(agent_id.to_owned())
        .or_default()
        .push(Allocation {
            agent_id: agent_id.to_owned(),
            resource: resource.to_owned(),
            amount,
            allocated_at: now_seconds(),
            expires_at: ttl.map_or(0.0, |duration| now_seconds() + duration.as_secs_f64()),
            purpose: purpose.to_owned(),
        });
    state
        .usage
        .entry(agent_id.to_owned())
        .or_default()
        .insert(resource.to_owned(), used.saturating_add(amount));
    ok([
        ("used", json!(used.saturating_add(amount))),
        ("limit", json!(limit)),
        (
            "remaining",
            json!(limit.saturating_sub(used.saturating_add(amount))),
        ),
    ])
}

fn reclaim_local(
    state: &mut AllocatorState,
    config: &AllocatorConfig,
    agent_id: &str,
    resource: &str,
    needed: u64,
    now: f64,
) -> u64 {
    let allocations = state.allocations.entry(agent_id.to_owned()).or_default();
    let marker = config.observe_marker.to_ascii_lowercase();
    let mut reclaimed = 0_u64;
    let mut kept = Vec::with_capacity(allocations.len());
    for allocation in allocations.drain(..) {
        if allocation.resource == resource
            && allocation.expires_at > 0.0
            && now > allocation.expires_at
        {
            reclaimed = reclaimed.saturating_add(allocation.amount);
        } else {
            kept.push(allocation);
        }
    }
    if reclaimed < needed {
        let mut retained = Vec::with_capacity(kept.len());
        for allocation in kept {
            if reclaimed < needed
                && allocation.resource == resource
                && allocation.purpose.to_ascii_lowercase().contains(&marker)
            {
                reclaimed = reclaimed.saturating_add(allocation.amount);
            } else {
                retained.push(allocation);
            }
        }
        kept = retained;
    }
    *allocations = kept;
    let current = usage_for(state, agent_id, resource);
    state
        .usage
        .entry(agent_id.to_owned())
        .or_default()
        .insert(resource.to_owned(), current.saturating_sub(reclaimed));
    reclaimed
}

fn reclaim_victim(
    state: &mut AllocatorState,
    config: &AllocatorConfig,
    requesting_agent: &str,
    resource: &str,
    needed: u64,
) -> u64 {
    let mut candidates: Vec<(String, u64, u64)> = state
        .allocations
        .iter()
        .filter(|(agent_id, _)| agent_id.as_str() != requesting_agent)
        .filter_map(|(agent_id, allocations)| {
            let total: u64 = allocations
                .iter()
                .filter(|allocation| allocation.resource == resource)
                .map(|allocation| allocation.amount)
                .sum();
            if total == 0 {
                return None;
            }
            let priority = state
                .limits
                .get(agent_id)
                .and_then(|limits| limits.get("priority"))
                .copied()
                .unwrap_or(config.default_priority);
            Some((agent_id.clone(), priority, total))
        })
        .collect();
    candidates.sort_by(|left, right| left.1.cmp(&right.1).then(right.2.cmp(&left.2)));
    let Some((victim, _, total)) = candidates.into_iter().next() else {
        return 0;
    };
    let reclaim = total.min(needed);
    let allocations = state.allocations.entry(victim.clone()).or_default();
    let mut freed = 0_u64;
    let mut kept = Vec::with_capacity(allocations.len());
    for allocation in allocations.drain(..) {
        if allocation.resource == resource && freed < reclaim {
            freed = freed.saturating_add(allocation.amount);
        } else {
            kept.push(allocation);
        }
    }
    *allocations = kept;
    let current = usage_for(state, &victim, resource);
    state
        .usage
        .entry(victim)
        .or_default()
        .insert(resource.to_owned(), current.saturating_sub(freed));
    freed
}

fn profile_limit(profile: &ResourceProfile, resource: &str) -> Option<u64> {
    match resource {
        "workers" => Some(profile.max_workers),
        "scouts" => Some(profile.max_scouts),
        "memory" => Some(profile.max_memory),
        "tokens" => Some(profile.max_tokens),
        _ => None,
    }
}

fn profile_wire(profile: &ResourceProfile) -> WireMap {
    BTreeMap::from([
        ("max_tokens".to_owned(), json!(profile.max_tokens)),
        ("max_workers".to_owned(), json!(profile.max_workers)),
        ("max_scouts".to_owned(), json!(profile.max_scouts)),
        ("max_memory".to_owned(), json!(profile.max_memory)),
        ("priority".to_owned(), json!(profile.priority)),
    ])
}

fn ok<const N: usize>(fields: [(&str, Value); N]) -> WireMap {
    let mut result = BTreeMap::from_iter(
        fields
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value)),
    );
    result.insert("success".to_owned(), json!(true));
    result
}

fn fail<const N: usize>(error: &str, fields: [(&str, Value); N]) -> WireMap {
    let mut result = BTreeMap::from_iter(
        fields
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value)),
    );
    result.insert("success".to_owned(), json!(false));
    result.insert("error".to_owned(), json!(error));
    result
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}

fn round_precision(value: f64, places: u32) -> f64 {
    let factor = 10_f64.powi(places as i32);
    (value * factor).round() / factor
}
