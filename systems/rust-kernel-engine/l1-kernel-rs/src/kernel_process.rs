//! Rust process-table candidate behind the Python PCB contract.

use std::collections::{BTreeMap, VecDeque};
use std::sync::{Mutex as StdMutex, MutexGuard, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

pub use crate::contract::ProcessState;
use crate::substrate::ProcessHandle;
use serde_json::{Value, json};

/// Dictionary-shaped process value retained for the Python adapter seam.
pub type WireMap = BTreeMap<String, Value>;

/// Deployment values supplied to the process-table mechanism.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessTableConfig {
    /// Maximum number of audit rows retained in memory.
    pub audit_max: usize,
    /// Name assigned to PID 0.
    pub init_name: String,
    /// Role assigned to PID 0.
    pub init_role: String,
    /// Ring assigned to PID 0.
    pub init_ring: u8,
    /// Default ring for ordinary processes.
    pub default_ring: u8,
}

impl ProcessTableConfig {
    /// Build a process configuration without embedding deployment constants.
    pub fn new(
        audit_max: usize,
        init_name: impl Into<String>,
        init_role: impl Into<String>,
        init_ring: u8,
        default_ring: u8,
    ) -> Self {
        Self {
            audit_max,
            init_name: init_name.into(),
            init_role: init_role.into(),
            init_ring,
            default_ring,
        }
    }
}

/// Resource counters carried by a process control block.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ResourceUsage {
    /// Total token budget allocated to the process.
    pub tokens_allocated: u64,
    /// Total tokens consumed by the process.
    pub tokens_used: u64,
    /// Number of active workers owned by the process.
    pub workers_active: u64,
    /// Number of active scouts owned by the process.
    pub scouts_active: u64,
    /// Number of memory entries attributed to the process.
    pub memory_entries: u64,
    /// Number of cards processed by the process.
    pub cards_processed: u64,
    /// Accumulated CPU time in seconds.
    pub cpu_time: f64,
}

impl ResourceUsage {
    /// Record allocated and consumed tokens.
    pub fn record_tokens(&mut self, allocated: u64, used: u64) {
        self.tokens_allocated = self.tokens_allocated.saturating_add(allocated);
        self.tokens_used = self.tokens_used.saturating_add(used);
    }

    /// Increment the completed-card counter.
    pub fn record_card(&mut self) {
        self.cards_processed = self.cards_processed.saturating_add(1);
    }

    /// Accumulate CPU time in seconds.
    pub fn record_cpu(&mut self, seconds: f64) {
        self.cpu_time += seconds;
    }

    /// Record an allocation event without touching activity time.
    pub fn record_alloc(&mut self, tokens: u64) {
        self.tokens_allocated = self.tokens_allocated.saturating_add(tokens);
    }

    /// Record usage and optional CPU time.
    pub fn record_use(&mut self, tokens: u64, cpu_seconds: f64) {
        self.tokens_used = self.tokens_used.saturating_add(tokens);
        self.cpu_time += cpu_seconds;
    }

    /// Apply a signed scout count delta without allowing underflow.
    pub fn record_scout(&mut self, delta: i64) {
        if delta >= 0 {
            self.scouts_active = self.scouts_active.saturating_add(delta as u64);
        } else {
            self.scouts_active = self.scouts_active.saturating_sub(delta.unsigned_abs());
        }
    }
}

/// Process control block snapshot and mutable kernel state.
#[derive(Debug, Clone, PartialEq)]
pub struct Pcb {
    /// Stable process identifier.
    pub pid: u64,
    /// Agent or process name.
    pub name: String,
    /// Optional role label.
    pub role: String,
    /// Parent process identifier.
    pub parent_pid: u64,
    /// Security ring supplied by the caller.
    pub ring: u8,
    /// Current lifecycle state.
    pub state: ProcessState,
    /// Resource accounting owned by the process.
    pub resources: ResourceUsage,
    /// Creation timestamp in Unix seconds.
    pub created_at: f64,
    /// Last activity timestamp in Unix seconds.
    pub last_active: f64,
    /// Optional exit code after termination.
    pub exit_code: Option<i32>,
    /// Human-readable exit reason.
    pub exit_reason: String,
    /// Whether cancellation was requested.
    pub cancelled: bool,
    /// Cancellation reason retained for diagnostics.
    pub cancel_reason: String,
    /// Whether an external identity proof was recorded.
    pub identity_verified: bool,
}

impl Pcb {
    /// Construct a ready process control block.
    pub fn new(
        pid: u64,
        name: impl Into<String>,
        role: impl Into<String>,
        parent_pid: u64,
        ring: u8,
    ) -> Self {
        let now = now_seconds();
        Self {
            pid,
            name: name.into(),
            role: role.into(),
            parent_pid,
            ring,
            state: ProcessState::Ready,
            resources: ResourceUsage::default(),
            created_at: now,
            last_active: now,
            exit_code: None,
            exit_reason: String::new(),
            cancelled: false,
            cancel_reason: String::new(),
            identity_verified: false,
        }
    }

    /// Mark this process as recently active.
    pub fn touch(&mut self) {
        self.last_active = now_seconds();
    }

    /// Record allocated and consumed tokens, then touch the PCB.
    pub fn record_tokens(&mut self, allocated: u64, used: u64) {
        self.resources.record_tokens(allocated, used);
        self.touch();
    }

    /// Increment the card counter, then touch the PCB.
    pub fn record_card(&mut self) {
        self.resources.record_card();
        self.touch();
    }

    /// Accumulate CPU time, then touch the PCB.
    pub fn record_cpu(&mut self, seconds: f64) {
        self.resources.record_cpu(seconds);
        self.touch();
    }

    /// Record an allocation event without touching the PCB.
    pub fn record_alloc(&mut self, tokens: u64) {
        self.resources.record_alloc(tokens);
    }

    /// Record usage and CPU time, then touch the PCB.
    pub fn record_use(&mut self, tokens: u64, cpu_seconds: f64) {
        self.resources.record_use(tokens, cpu_seconds);
        self.touch();
    }

    /// Adjust the active scout count without allowing it below zero.
    pub fn record_scout(&mut self, delta: i64) {
        self.resources.record_scout(delta);
    }

    /// Return the stable dictionary shape consumed by Python callers.
    pub fn snapshot(&self) -> WireMap {
        let mut snapshot = BTreeMap::from([
            ("pid".to_owned(), json!(self.pid)),
            ("name".to_owned(), json!(self.name)),
            ("role".to_owned(), json!(self.role)),
            ("state".to_owned(), json!(self.state.as_str())),
            ("ring".to_owned(), json!(self.ring)),
            ("parent_pid".to_owned(), json!(self.parent_pid)),
            (
                "uptime".to_owned(),
                json!(round_tenth(now_seconds() - self.created_at)),
            ),
            (
                "idle".to_owned(),
                json!(round_tenth(now_seconds() - self.last_active)),
            ),
        ]);
        snapshot.insert(
            "tokens_allocated".to_owned(),
            json!(self.resources.tokens_allocated),
        );
        snapshot.insert("tokens_used".to_owned(), json!(self.resources.tokens_used));
        snapshot.insert(
            "workers_active".to_owned(),
            json!(self.resources.workers_active),
        );
        snapshot.insert(
            "scouts_active".to_owned(),
            json!(self.resources.scouts_active),
        );
        snapshot.insert(
            "memory_entries".to_owned(),
            json!(self.resources.memory_entries),
        );
        snapshot.insert(
            "cards_processed".to_owned(),
            json!(self.resources.cards_processed),
        );
        snapshot.insert("cpu_time".to_owned(), json!(self.resources.cpu_time));
        snapshot
    }
}

#[derive(Debug, Clone)]
struct AuditEntry {
    op: String,
    pid: u64,
    name: String,
    detail: String,
    timestamp: f64,
}

impl AuditEntry {
    fn to_wire(&self) -> WireMap {
        BTreeMap::from([
            ("op".to_owned(), json!(self.op)),
            ("pid".to_owned(), json!(self.pid)),
            ("name".to_owned(), json!(self.name)),
            ("detail".to_owned(), json!(self.detail)),
            ("timestamp".to_owned(), json!(self.timestamp)),
        ])
    }
}

#[derive(Debug)]
struct TableState {
    processes: BTreeMap<u64, Pcb>,
    name_index: BTreeMap<String, u64>,
    next_pid: u64,
    audit_log: VecDeque<AuditEntry>,
}

/// Thread-safe process table candidate with explicit FSM and cancellation.
pub struct ProcessTable {
    config: ProcessTableConfig,
    state: StdMutex<TableState>,
}

impl ProcessTable {
    /// Create a process table and install the configured PID 0 kernel process.
    pub fn new(config: ProcessTableConfig) -> Self {
        let init_name = config.init_name.clone();
        let init = Pcb::new(
            0,
            init_name.clone(),
            config.init_role.clone(),
            0,
            config.init_ring,
        );
        let mut init = init;
        init.state = ProcessState::Running;
        let mut processes = BTreeMap::new();
        processes.insert(0, init);
        Self {
            config,
            state: StdMutex::new(TableState {
                processes,
                name_index: BTreeMap::from([(init_name, 0)]),
                next_pid: 1,
                audit_log: VecDeque::new(),
            }),
        }
    }

    /// Create a process in READY state and append a spawn audit row.
    pub fn spawn(
        &self,
        name: impl Into<String>,
        role: impl Into<String>,
        parent_pid: u64,
        ring: Option<u8>,
    ) -> Pcb {
        let name = name.into();
        let role = role.into();
        let mut state = self.lock_state();
        let pid = state.next_pid;
        state.next_pid = state.next_pid.saturating_add(1);
        let pcb = Pcb::new(
            pid,
            name.clone(),
            role.clone(),
            parent_pid,
            ring.unwrap_or(self.config.default_ring),
        );
        state.processes.insert(pid, pcb.clone());
        state.name_index.insert(name.clone(), pid);
        append_audit(
            &mut state,
            self.config.audit_max,
            "spawn",
            pid,
            &name,
            &role,
        );
        pcb
    }

    /// Return a cloned PCB by PID so no interpreter object crosses the seam.
    pub fn get(&self, pid: u64) -> Option<Pcb> {
        self.lock_state().processes.get(&pid).cloned()
    }

    /// Return a generation-tagged handle for a live PID in the substrate range.
    ///
    /// The parity table keeps monotonic PIDs and does not recycle slots, so
    /// this bridge currently uses generation one. Reusable-slot generation
    /// ownership remains in `ShardedStateStore` until the clean-break table is
    /// promoted beyond the reference candidate.
    pub fn handle_for_pid(&self, pid: u64) -> Option<ProcessHandle> {
        let slot = u32::try_from(pid).ok()?;
        let state = self.lock_state();
        if !state.processes.contains_key(&pid) {
            return None;
        }
        ProcessHandle::new(slot, 1)
    }

    /// Return a PCB only when the typed handle generation is still current.
    pub fn get_by_handle(&self, handle: ProcessHandle) -> Option<Pcb> {
        if handle.generation() != 1 {
            return None;
        }
        self.get(u64::from(handle.slot()))
    }

    /// Return a cloned PCB by name so no table lock escapes the call.
    pub fn get_by_name(&self, name: &str) -> Option<Pcb> {
        let state = self.lock_state();
        state
            .name_index
            .get(name)
            .and_then(|pid| state.processes.get(pid))
            .cloned()
    }

    /// Set a state directly, matching the Python administrative setter.
    pub fn set_state(&self, pid: u64, next: ProcessState) -> bool {
        let mut state = self.lock_state();
        let Some(pcb) = state.processes.get_mut(&pid) else {
            return false;
        };
        pcb.state = next;
        pcb.touch();
        true
    }

    /// Drive READY to RUNNING; repeated RUNNING calls are idempotent.
    pub fn set_running(&self, name: &str) -> bool {
        self.transition_by_name(name, "run", true)
    }

    /// Drive RUNNING to READY; repeated READY calls are idempotent.
    pub fn yield_process(&self, name: &str) -> bool {
        self.transition_by_name(name, "yield", true)
    }

    /// Mark an agent stopped and cancelled, recording the reason.
    pub fn cancel(&self, name: &str, reason: &str) -> bool {
        let mut state = self.lock_state();
        let Some(pid) = state.name_index.get(name).copied() else {
            return false;
        };
        let Some(pcb) = state.processes.get_mut(&pid) else {
            return false;
        };
        pcb.cancelled = true;
        pcb.cancel_reason = reason.to_owned();
        if pcb.state != ProcessState::Stopped {
            let _ = apply_transition(pcb, "stop");
        }
        pcb.touch();
        append_audit(
            &mut state,
            self.config.audit_max,
            "cancel",
            pid,
            name,
            reason,
        );
        true
    }

    /// Return whether cancellation has been requested for a named process.
    pub fn is_cancelled(&self, name: &str) -> bool {
        self.get_by_name(name).is_some_and(|pcb| pcb.cancelled)
    }

    /// Mark a process as identity-verified without changing its lifecycle.
    pub fn mark_identity_verified(&self, name: &str) -> bool {
        let mut state = self.lock_state();
        let Some(pid) = state.name_index.get(name).copied() else {
            return false;
        };
        let Some(pcb) = state.processes.get_mut(&pid) else {
            return false;
        };
        pcb.identity_verified = true;
        pcb.touch();
        true
    }

    /// Record token allocation and usage for a process.
    pub fn record_tokens(&self, pid: u64, allocated: u64, used: u64) -> bool {
        self.with_pcb(pid, |pcb| pcb.record_tokens(allocated, used))
    }

    /// Increment the card counter for a process.
    pub fn record_card(&self, pid: u64) -> bool {
        self.with_pcb(pid, Pcb::record_card)
    }

    /// Accumulate CPU time for a process.
    pub fn record_cpu(&self, pid: u64, seconds: f64) -> bool {
        self.with_pcb(pid, |pcb| pcb.record_cpu(seconds))
    }

    /// Record an allocation event without touching process activity time.
    pub fn record_alloc(&self, pid: u64, tokens: u64) -> bool {
        self.with_pcb(pid, |pcb| pcb.record_alloc(tokens))
    }

    /// Record token usage and CPU time for a process.
    pub fn record_use(&self, pid: u64, tokens: u64, cpu_seconds: f64) -> bool {
        self.with_pcb(pid, |pcb| pcb.record_use(tokens, cpu_seconds))
    }

    /// Adjust the active scout count for a process.
    pub fn record_scout(&self, pid: u64, delta: i64) -> bool {
        self.with_pcb(pid, |pcb| pcb.record_scout(delta))
    }

    /// Terminate a process through the crash transition and retain exit info.
    pub fn exit(&self, pid: u64, exit_code: i32, reason: &str) -> bool {
        let mut state = self.lock_state();
        let Some(pcb) = state.processes.get_mut(&pid) else {
            return false;
        };
        if !apply_transition(pcb, "crash") {
            return false;
        }
        pcb.exit_code = Some(exit_code);
        pcb.exit_reason = reason.to_owned();
        let name = pcb.name.clone();
        let detail = if reason.is_empty() {
            format!("exit({exit_code})")
        } else {
            reason.to_owned()
        };
        append_audit(
            &mut state,
            self.config.audit_max,
            "exit",
            pid,
            &name,
            &detail,
        );
        true
    }

    /// Terminate a process through a current generation-tagged handle.
    pub fn exit_handle(&self, handle: ProcessHandle, exit_code: i32, reason: &str) -> bool {
        if handle.generation() != 1 {
            return false;
        }
        self.exit(u64::from(handle.slot()), exit_code, reason)
    }

    /// Terminate a named process through the same crash transition.
    pub fn exit_by_name(&self, name: &str, exit_code: i32, reason: &str) -> bool {
        let pid = self.lock_state().name_index.get(name).copied();
        pid.is_some_and(|pid| self.exit(pid, exit_code, reason))
    }

    /// Remove a process and return its Python-compatible snapshot.
    pub fn reap(&self, pid: u64) -> Option<WireMap> {
        let mut state = self.lock_state();
        let pcb = state.processes.remove(&pid)?;
        state.name_index.remove(&pcb.name);
        append_audit(
            &mut state,
            self.config.audit_max,
            "reap",
            pid,
            &pcb.name,
            "",
        );
        Some(pcb.snapshot())
    }

    /// Reap a process only through a current generation-tagged handle.
    pub fn reap_handle(&self, handle: ProcessHandle) -> Option<WireMap> {
        if handle.generation() != 1 {
            return None;
        }
        self.reap(u64::from(handle.slot()))
    }

    /// Return sorted snapshots, optionally filtered by lifecycle state.
    pub fn list_processes(&self, filter: Option<ProcessState>) -> Vec<WireMap> {
        let state = self.lock_state();
        state
            .processes
            .values()
            .filter(|pcb| filter.is_none_or(|wanted| pcb.state == wanted))
            .map(Pcb::snapshot)
            .collect()
    }

    /// Aggregate token, worker, scout, and card counters.
    pub fn resource_summary(&self) -> WireMap {
        let state = self.lock_state();
        let mut summary = BTreeMap::from([
            ("tokens".to_owned(), json!(0_u64)),
            ("workers".to_owned(), json!(0_u64)),
            ("scouts".to_owned(), json!(0_u64)),
            ("cards".to_owned(), json!(0_u64)),
        ]);
        let mut tokens = 0_u64;
        let mut workers = 0_u64;
        let mut scouts = 0_u64;
        let mut cards = 0_u64;
        for pcb in state.processes.values() {
            tokens = tokens.saturating_add(pcb.resources.tokens_allocated);
            workers = workers.saturating_add(pcb.resources.workers_active);
            scouts = scouts.saturating_add(pcb.resources.scouts_active);
            cards = cards.saturating_add(pcb.resources.cards_processed);
        }
        summary.insert("tokens".to_owned(), json!(tokens));
        summary.insert("workers".to_owned(), json!(workers));
        summary.insert("scouts".to_owned(), json!(scouts));
        summary.insert("cards".to_owned(), json!(cards));
        summary
    }

    /// Return the newest retained process audit rows.
    pub fn audit_log(&self, limit: usize) -> Vec<WireMap> {
        let state = self.lock_state();
        let start = state.audit_log.len().saturating_sub(limit);
        state
            .audit_log
            .iter()
            .skip(start)
            .map(AuditEntry::to_wire)
            .collect()
    }

    fn transition_by_name(&self, name: &str, action: &str, idempotent: bool) -> bool {
        let mut state = self.lock_state();
        let Some(pid) = state.name_index.get(name).copied() else {
            return false;
        };
        let Some(pcb) = state.processes.get_mut(&pid) else {
            return false;
        };
        if idempotent
            && ((action == "run" && pcb.state == ProcessState::Running)
                || (action == "yield" && pcb.state == ProcessState::Ready))
        {
            return true;
        }
        apply_transition(pcb, action)
    }

    fn with_pcb(&self, pid: u64, update: impl FnOnce(&mut Pcb)) -> bool {
        let mut state = self.lock_state();
        let Some(pcb) = state.processes.get_mut(&pid) else {
            return false;
        };
        update(pcb);
        true
    }

    fn lock_state(&self) -> MutexGuard<'_, TableState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

fn apply_transition(pcb: &mut Pcb, action: &str) -> bool {
    let next = match (pcb.state, action) {
        (ProcessState::Ready, "run") => Some(ProcessState::Running),
        (ProcessState::Ready, "crash") => Some(ProcessState::Zombie),
        (ProcessState::Ready, "stop") => Some(ProcessState::Stopped),
        (ProcessState::Running, "block") => Some(ProcessState::Blocked),
        (ProcessState::Running, "yield") => Some(ProcessState::Ready),
        (ProcessState::Running, "stop") => Some(ProcessState::Stopped),
        (ProcessState::Running, "crash") => Some(ProcessState::Zombie),
        (ProcessState::Blocked, "wake") => Some(ProcessState::Ready),
        (ProcessState::Blocked, "stop") => Some(ProcessState::Stopped),
        (ProcessState::Blocked, "crash") => Some(ProcessState::Zombie),
        (ProcessState::Stopped, "resume") => Some(ProcessState::Ready),
        _ => None,
    };
    let Some(next) = next else {
        return false;
    };
    pcb.state = next;
    pcb.touch();
    true
}

fn append_audit(state: &mut TableState, max: usize, op: &str, pid: u64, name: &str, detail: &str) {
    state.audit_log.push_back(AuditEntry {
        op: op.to_owned(),
        pid,
        name: name.to_owned(),
        detail: detail.to_owned(),
        timestamp: now_seconds(),
    });
    while state.audit_log.len() > max {
        state.audit_log.pop_front();
    }
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}

fn round_tenth(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}
