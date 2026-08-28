//! Rust-native identity-binding metadata registry for the L1 kernel.
//!
//! This candidate owns only bounded binding metadata and the write gate. Prompt
//! fragments, identity definitions, persistence, events, and API routing stay
//! in adapters because they are policy or transport concerns rather than
//! kernel state ownership.

use std::collections::BTreeMap;
use std::sync::{PoisonError, RwLock};

use serde::{Deserialize, Serialize};

/// Default maximum number of role bindings owned by one Cell.
pub const DEFAULT_MAX_BINDINGS_PER_CELL: usize = 32;
/// Default maximum character budget declared for an adapter-owned fragment.
pub const DEFAULT_MAX_FRAGMENT_CHARS: usize = 1_200;
/// Default maximum number of domain tags retained in one binding.
pub const DEFAULT_MAX_DOMAIN_TAGS: usize = 16;
/// Default minimum caller clearance for a binding write.
pub const DEFAULT_MIN_WRITE_CLEARANCE: u8 = 3;

/// Policy for bounded binding metadata and authorization.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BindingPolicy {
    /// Maximum distinct roles that one Cell may own.
    /// Binding capacity per cell.
    pub max_bindings_per_cell: usize,
    /// Maximum domain tags retained in one binding.
    /// Domain tags allowed per binding.
    pub max_domain_tags: usize,
    /// Maximum declared prompt budget; prompt bytes stay outside this crate.
    /// Prompt-fragment character budget.
    pub max_fragment_chars: usize,
    /// Minimum explicit clearance for a non-role-based write.
    /// Minimum clearance required to mutate bindings.
    pub min_write_clearance: u8,
    /// Roles allowed to write regardless of numeric clearance.
    /// Roles authorized for binding writes.
    pub write_roles: Vec<String>,
}

impl Default for BindingPolicy {
    /// Apply the default identity-binding policy limits.
    fn default() -> Self {
        Self {
            max_bindings_per_cell: DEFAULT_MAX_BINDINGS_PER_CELL,
            max_domain_tags: DEFAULT_MAX_DOMAIN_TAGS,
            max_fragment_chars: DEFAULT_MAX_FRAGMENT_CHARS,
            min_write_clearance: DEFAULT_MIN_WRITE_CLEARANCE,
            write_roles: vec!["l3".to_owned(), "deployer".to_owned(), "default".to_owned()],
        }
    }
}

impl BindingPolicy {
    /// Reject an unbounded or unusable policy before registry construction.
    ///
    /// # Errors
    ///
    /// `Err` with a stable message when any capacity/budget/role floor is
    /// non-positive or the write-role list is empty.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.max_bindings_per_cell == 0 {
            return Err("binding cell capacity must be positive");
        }
        if self.max_domain_tags == 0 {
            return Err("binding domain capacity must be positive");
        }
        if self.max_fragment_chars == 0 {
            return Err("binding fragment budget must be positive");
        }
        if self.write_roles.iter().any(|role| role.trim().is_empty()) {
            return Err("binding write roles must not be empty");
        }
        Ok(())
    }
}

/// Caller identity and clearance supplied by an adapter at the write edge.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WritePrincipal {
    /// Stable caller identity, when available.
    /// Bound agent identity.
    pub agent_id: String,
    /// Declared caller role used by the role allow-list.
    /// Role fragment key.
    /// Role served within the cell.
    pub role: String,
    /// Caller clearance evaluated by the adapter or kernel authority.
    /// Authority clearance level.
    pub clearance: u8,
    /// Whether this is a trusted boot/system mutation.
    /// Internal system identities bypass external checks.
    pub internal: bool,
}

impl WritePrincipal {
    /// Build an external principal with explicit identity and clearance.
    pub fn external(agent_id: impl Into<String>, role: impl Into<String>, clearance: u8) -> Self {
        Self {
            agent_id: agent_id.into(),
            role: role.into(),
            clearance,
            internal: false,
        }
    }

    /// Build a trusted system principal for boot-owned configuration.
    pub fn internal() -> Self {
        Self {
            agent_id: "".to_owned(),
            role: "internal".to_owned(),
            clearance: u8::MAX,
            internal: true,
        }
    }

    /// Return the effective actor, preferring the agent id when bound.
    fn actor(&self) -> &str {
        if !self.agent_id.is_empty() {
            &self.agent_id
        } else {
            &self.role
        }
    }
}

/// Input for one binding mutation; no prompt text crosses this boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BindingSpec {
    /// Cell owning the role binding.
    /// Cell this binding belongs to.
    pub cell_id: String,
    /// Role key unique within the Cell.
    pub role: String,
    /// System-issued identity identifier supplied by the UID adapter.
    /// Referenced identity UID.
    pub identity_id: String,
    /// Structured domain tags used by upper-layer routing.
    #[serde(default)]
    /// Knowledge-domain tags for injection matching.
    pub domain_tags: Vec<String>,
    /// Declared adapter-owned fragment budget; zero selects the policy default.
    #[serde(default)]
    /// Fragment budget actually used.
    pub max_chars: usize,
}

impl BindingSpec {
    /// Build a binding specification with the default fragment budget.
    pub fn new(
        cell_id: impl Into<String>,
        role: impl Into<String>,
        identity_id: impl Into<String>,
    ) -> Self {
        Self {
            cell_id: cell_id.into(),
            role: role.into(),
            identity_id: identity_id.into(),
            domain_tags: Vec::new(),
            max_chars: 0,
        }
    }
}

/// Public metadata record returned from a registry snapshot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BindingRecord {
    /// Cell owning the role binding.
    pub cell_id: String,
    /// Role key unique within the Cell.
    pub role: String,
    /// Stable identity identifier; rebinds preserve this value.
    pub identity_id: String,
    /// Sorted, duplicate-free domain tags.
    pub domain_tags: Vec<String>,
    /// Bounded prompt budget declared for the adapter boundary.
    pub max_chars: usize,
    /// Monotonic registry revision at which this record was written.
    /// Monotonic mutation counter.
    pub revision: u64,
    /// Caller identity recorded for audit correlation.
    /// Last writer identity.
    pub updated_by: String,
}

#[derive(Debug, Default)]
struct BindingState {
    revision: u64,
    records: BTreeMap<(String, String), BindingRecord>,
}

/// Thread-safe bounded registry for Rust-owned binding metadata.
pub struct IdentityBindingRegistry {
    policy: BindingPolicy,
    state: RwLock<BindingState>,
}

impl IdentityBindingRegistry {
    /// Create an empty registry with an explicit validated policy.
    ///
    /// # Errors
    ///
    /// `Err` forwarding [`BindingPolicy::validate`] failures.
    pub fn new(policy: BindingPolicy) -> Result<Self, &'static str> {
        policy.validate()?;
        Ok(Self {
            policy,
            state: RwLock::new(BindingState::default()),
        })
    }

    /// Return the immutable policy used by this registry.
    pub fn policy(&self) -> &BindingPolicy {
        &self.policy
    }

    /// Check a caller before any binding mutation is admitted.
    ///
    /// # Errors
    ///
    /// Denied result when clearance < min_write_clearance, role not in write_roles, or cell binding capacity is exhausted.
    pub fn authorize_write(&self, principal: &WritePrincipal) -> Result<(), &'static str> {
        if principal.internal {
            return Ok(());
        }
        if principal.agent_id.is_empty() && principal.role.is_empty() {
            return Err("identity required for identity-binding writes");
        }
        if self
            .policy
            .write_roles
            .iter()
            .any(|role| role == &principal.role)
            || principal.clearance >= self.policy.min_write_clearance
        {
            return Ok(());
        }
        Err("caller may not mutate identity bindings")
    }

    /// Insert or update one binding while preserving an existing identity id.
    pub fn upsert(
        &self,
        spec: BindingSpec,
        principal: &WritePrincipal,
    ) -> Result<BindingRecord, &'static str> {
        self.authorize_write(principal)?;
        let (cell_id, role) = Self::validate_spec(&spec, &self.policy)?;
        let cell_id = cell_id.to_owned();
        let role = role.to_owned();
        let key = (cell_id.clone(), role.clone());
        let mut state = self.state.write().unwrap_or_else(PoisonError::into_inner);
        if !state.records.contains_key(&key)
            && state
                .records
                .keys()
                .filter(|(existing_cell, _)| existing_cell == &cell_id)
                .count()
                >= self.policy.max_bindings_per_cell
        {
            return Err("binding cap reached for cell");
        }
        let identity_id = match state.records.get(&key) {
            Some(record) => record.identity_id.clone(),
            None => {
                if spec.identity_id.trim().is_empty() {
                    return Err("binding identity id is required for a new binding");
                }
                spec.identity_id.clone()
            }
        };
        state.revision = state.revision.saturating_add(1);
        let record = BindingRecord {
            cell_id,
            role,
            identity_id,
            domain_tags: Self::normalize_tags(spec.domain_tags, &self.policy)?,
            max_chars: Self::normalize_max_chars(spec.max_chars, &self.policy),
            revision: state.revision,
            updated_by: principal.actor().to_owned(),
        };
        state.records.insert(key, record.clone());
        Ok(record)
    }

    /// Remove one binding and return whether a record was deleted.
    pub fn unbind(
        &self,
        cell_id: &str,
        role: &str,
        principal: &WritePrincipal,
    ) -> Result<bool, &'static str> {
        self.authorize_write(principal)?;
        let mut state = self.state.write().unwrap_or_else(PoisonError::into_inner);
        let removed = state
            .records
            .remove(&(cell_id.to_owned(), role.to_owned()))
            .is_some();
        if removed {
            state.revision = state.revision.saturating_add(1);
        }
        Ok(removed)
    }

    /// Remove all records for one Cell and return the number deleted.
    pub fn clear_cell(
        &self,
        cell_id: &str,
        principal: &WritePrincipal,
    ) -> Result<usize, &'static str> {
        self.authorize_write(principal)?;
        let mut state = self.state.write().unwrap_or_else(PoisonError::into_inner);
        let before = state.records.len();
        state
            .records
            .retain(|(existing_cell, _), _| existing_cell != cell_id);
        let removed = before - state.records.len();
        state.revision = state.revision.saturating_add(1);
        Ok(removed)
    }

    /// Return a cloned record only when both key components match.
    pub fn get(&self, cell_id: &str, role: &str) -> Option<BindingRecord> {
        self.state
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .records
            .get(&(cell_id.to_owned(), role.to_owned()))
            .cloned()
    }

    /// Return all records in deterministic Cell/role order.
    pub fn snapshot(&self) -> Vec<BindingRecord> {
        self.state
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .records
            .values()
            .cloned()
            .collect()
    }

    /// Return all Cells in deterministic order.
    pub fn cell_ids(&self) -> Vec<String> {
        let state = self.state.read().unwrap_or_else(PoisonError::into_inner);
        let mut cells = Vec::new();
        for (cell_id, _) in state.records.keys() {
            if cells.last() != Some(cell_id) {
                cells.push(cell_id.clone());
            }
        }
        cells
    }

    /// Return the current mutation revision.
    pub fn revision(&self) -> u64 {
        self.state
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .revision
    }

    /// Validate a binding spec's identity fields fail-closed.
    fn validate_spec<'a>(
        spec: &'a BindingSpec,
        policy: &BindingPolicy,
    ) -> Result<(&'a str, &'a str), &'static str> {
        if spec.cell_id.trim().is_empty() || spec.role.trim().is_empty() {
            return Err("binding cell and role are required");
        }
        if spec.domain_tags.len() > policy.max_domain_tags {
            return Err("binding domain tag cap exceeded");
        }
        if spec.domain_tags.iter().any(|tag| tag.trim().is_empty()) {
            return Err("binding domain tags must not be empty");
        }
        Ok((spec.cell_id.as_str(), spec.role.as_str()))
    }

    /// Deduplicate and bound the tag list for a binding spec.
    fn normalize_tags(
        mut tags: Vec<String>,
        policy: &BindingPolicy,
    ) -> Result<Vec<String>, &'static str> {
        tags.sort_unstable();
        tags.dedup();
        if tags.len() > policy.max_domain_tags {
            return Err("binding domain tag cap exceeded");
        }
        Ok(tags)
    }

    /// Bound the max-chars value to the policy ceiling when unset.
    fn normalize_max_chars(value: usize, policy: &BindingPolicy) -> usize {
        if value == 0 {
            policy.max_fragment_chars
        } else {
            value.min(policy.max_fragment_chars)
        }
    }
}

impl Default for IdentityBindingRegistry {
    /// Create a binding registry with the default policy.
    fn default() -> Self {
        Self::new(BindingPolicy::default()).expect("default identity binding policy is valid")
    }
}
