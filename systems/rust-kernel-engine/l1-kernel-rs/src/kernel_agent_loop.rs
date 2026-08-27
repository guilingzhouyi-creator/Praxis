//! Rust-owned AgentLoop routing state for the clean-break kernel.
//!
//! This module binds one logical loop to an agent, cell, session, and terminal
//! identity. It admits session input/events with authoritative sequencing but
//! deliberately leaves provider calls, prompt/tool policy, PTY I/O, and worker
//! execution to upper-layer adapters.

use std::collections::{BTreeSet, HashMap};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, PoisonError, RwLock, RwLockReadGuard, RwLockWriteGuard, TryLockError};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::session::{MessageRole, Session, SessionError, SessionInput};
use crate::snapshot::{BookSnapshotPage, BookSnapshotPageError, BookSnapshotPageRequest};
use crate::terminal::{TerminalBook, TerminalError, TerminalState};

/// Version of the logical AgentLoop routing contract.
pub const AGENT_LOOP_CONTRACT_VERSION: u32 = 1;
/// Maximum UTF-8 byte length of a logical loop identity field.
pub const AGENT_LOOP_MAX_ID_BYTES: usize = 128;

/// Lifecycle of one logical AgentLoop execution identity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentLoopState {
    /// Identity is registered but session/terminal correlation is incomplete.
    Created,
    /// Session and terminal correlation is validated; execution has not begun.
    Ready,
    /// The loop may admit user input and agent/tool events.
    Running,
    /// The loop is paused and does not admit new messages.
    Paused,
    /// Shutdown has begun and no new messages may be admitted.
    Closing,
    /// Execution ended cleanly and cannot restart.
    Stopped,
    /// Execution ended with an unclean failure.
    Failed,
}

impl AgentLoopState {
    /// Return whether this state is terminal.
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Stopped | Self::Failed)
    }

    fn can_transition_to(self, target: Self) -> bool {
        matches!(
            (self, target),
            (Self::Created, Self::Ready | Self::Failed)
                | (Self::Ready, Self::Running | Self::Closing | Self::Failed)
                | (Self::Running, Self::Paused | Self::Closing | Self::Failed)
                | (Self::Paused, Self::Running | Self::Closing | Self::Failed)
                | (Self::Closing, Self::Stopped | Self::Failed)
        )
    }
}

/// Declarative identity for one logical AgentLoop.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentLoopSpec {
    /// Stable loop identity.
    /// Unique loop identity.
    pub loop_id: String,
    /// Owning agent identity.
    /// Owning agent execution body.
    pub agent_id: String,
    /// Owning Cell identity.
    /// Owning cell domain.
    pub cell_id: String,
    /// Session identity used as the message truth root.
    /// Correlated session identity.
    pub session_id: String,
    /// Terminal identity used by the I/O adapter.
    /// Correlated terminal identity.
    pub terminal_id: String,
}

impl AgentLoopSpec {
    /// Build an AgentLoop identity; correlation is checked on attachment.
    pub fn new(
        loop_id: impl Into<String>,
        agent_id: impl Into<String>,
        cell_id: impl Into<String>,
        session_id: impl Into<String>,
        terminal_id: impl Into<String>,
    ) -> Self {
        Self {
            loop_id: loop_id.into(),
            agent_id: agent_id.into(),
            cell_id: cell_id.into(),
            session_id: session_id.into(),
            terminal_id: terminal_id.into(),
        }
    }
}

/// Stable AgentLoop snapshot exposed to adapters and evidence collectors.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentLoopSnapshot {
    /// AgentLoop routing contract version.
    /// Snapshot schema version.
    pub contract_version: u32,
    /// Logical loop identity.
    /// Immutable creation specification.
    pub spec: AgentLoopSpec,
    /// Current execution state.
    /// Lifecycle state at snapshot time.
    pub state: AgentLoopState,
    /// Next accepted command sequence.
    /// Next command ordinal to allocate.
    pub next_command_seq: u64,
    /// Number of accepted input/event commands.
    /// Commands admitted since creation.
    pub accepted_commands: u64,
    /// Number of failed admission attempts after registration.
    /// Commands rejected since creation.
    pub failed_commands: u64,
    /// Aggregate contended wait to acquire the loop state mutex.
    /// Contended-lock wait total (contention-only sampling).
    pub lock_wait_ns: u64,
}

/// Receipt returned after a message is admitted to the session truth root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentLoopReceipt {
    /// Loop-local command sequence assigned after successful admission.
    /// Scratch command ordinal used by callers.
    pub command_seq: u64,
    /// Session history sequence assigned by SessionBook.
    /// Message sequence mirrored from the session.
    pub message_seq: u64,
    /// Authoritative user-input sequence, if this was user input.
    /// Authoritative input ordinal (Session-allocated).
    /// Input ordinal carried on the admitted item.
    pub input_seq: u64,
}

/// Agent-originated or tool-originated event awaiting session admission.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentLoopEvent {
    /// Caller-supplied idempotency identity.
    /// Caller-supplied dedup id.
    pub message_id: String,
    /// User-input sequence that this event answers.
    pub input_seq: u64,
    /// Retained non-user message role.
    /// Message role classification.
    pub role: MessageRole,
    /// Opaque event content.
    /// Admitted content (CoT excluded).
    pub content: String,
    /// Caller-supplied creation timestamp in nanoseconds.
    /// Admission timestamp in nanoseconds.
    pub created_at_ns: u64,
}

impl AgentLoopEvent {
    /// Build one event admission request.
    pub fn new(
        message_id: impl Into<String>,
        input_seq: u64,
        role: MessageRole,
        content: impl Into<String>,
        created_at_ns: u64,
    ) -> Self {
        Self {
            message_id: message_id.into(),
            input_seq,
            role,
            content: content.into(),
            created_at_ns,
        }
    }
}

/// Fail-closed errors at the logical AgentLoop boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentLoopError {
    /// An identity field is empty or exceeds its byte bound.
    InvalidIdentity(String),
    /// A role or content value violates the retained message contract.
    InvalidMessage(String),
    /// The loop identity already exists.
    DuplicateLoop(String),
    /// The loop identity does not exist.
    LoopNotFound(String),
    /// A lifecycle transition is invalid.
    InvalidTransition {
        from: AgentLoopState,
        to: AgentLoopState,
    },
    /// Session metadata does not match the loop identity.
    SessionMismatch,
    /// Terminal metadata does not match the loop identity.
    TerminalMismatch,
    /// The terminal has already reached a terminal lifecycle state.
    TerminalUnavailable(TerminalState),
    /// Session admission rejected the message.
    Session(SessionError),
    /// Terminal lookup or correlation failed.
    Terminal(TerminalError),
    /// A message was submitted while the loop was not running.
    NotRunning(AgentLoopState),
    /// A persisted loop snapshot violated its version or counter contract.
    InvalidSnapshot(String),
}

struct AgentLoopInner {
    state: AgentLoopState,
    next_command_seq: AtomicU64,
    accepted_commands: AtomicU64,
    failed_commands: AtomicU64,
}

struct AgentLoopRecord {
    spec: AgentLoopSpec,
    inner: RwLock<AgentLoopInner>,
    lock_wait_ns: AtomicU64,
}

impl AgentLoopRecord {
    fn snapshot(&self) -> AgentLoopSnapshot {
        let inner = self.read();
        snapshot_locked(&self.spec, &inner, self.lock_wait_ns())
    }

    /// Acquire the lifecycle read lock while admitting concurrent session writes.
    ///
    /// A writer transition still waits for every in-flight admission, so the
    /// lock boundary preserves the original stop/admission linearization while
    /// removing the loop mutex as a serial bottleneck.
    fn read(&self) -> RwLockReadGuard<'_, AgentLoopInner> {
        match self.inner.try_read() {
            Ok(guard) => guard,
            Err(TryLockError::Poisoned(poisoned)) => poisoned.into_inner(),
            Err(TryLockError::WouldBlock) => {
                let started = Instant::now();
                let guard = self.inner.read().unwrap_or_else(PoisonError::into_inner);
                self.lock_wait_ns.fetch_add(
                    started.elapsed().as_nanos().try_into().unwrap_or(u64::MAX),
                    Ordering::Relaxed,
                );
                guard
            }
        }
    }

    fn write(&self) -> RwLockWriteGuard<'_, AgentLoopInner> {
        match self.inner.try_write() {
            Ok(guard) => guard,
            Err(TryLockError::Poisoned(poisoned)) => poisoned.into_inner(),
            Err(TryLockError::WouldBlock) => {
                let started = Instant::now();
                let guard = self.inner.write().unwrap_or_else(PoisonError::into_inner);
                self.lock_wait_ns.fetch_add(
                    started.elapsed().as_nanos().try_into().unwrap_or(u64::MAX),
                    Ordering::Relaxed,
                );
                guard
            }
        }
    }

    fn lock_wait_ns(&self) -> u64 {
        self.lock_wait_ns.load(Ordering::Relaxed)
    }
}

/// Cached handle for a validated logical loop identity.
///
/// The handle avoids registry lookup on every hot-path admission. It does not
/// bypass lifecycle checks, session correlation, or the per-loop state lock.
#[derive(Clone)]
pub struct AgentLoopHandle {
    record: Arc<AgentLoopRecord>,
}

impl AgentLoopHandle {
    /// Return the immutable loop identity carried by this handle.
    pub fn spec(&self) -> AgentLoopSpec {
        self.record.spec.clone()
    }

    /// Return the current loop snapshot.
    ///
    /// # Errors
    ///
    /// Never fails; infallible by construction.
    pub fn snapshot(&self) -> AgentLoopSnapshot {
        self.record.snapshot()
    }

    /// Admit one user input through the authoritative Session truth root.
    ///
    /// # Errors
    ///
    /// SessionMismatch when `session_id` diverges from the correlated
    /// session; NotRunning when the loop is paused/stopped; Session when
    /// the underlying session rejects admission (dup id, capacity…).
    pub fn admit_input(
        &self,
        session: &Session,
        message_id: impl Into<String>,
        content: impl Into<String>,
        created_at_ns: u64,
    ) -> Result<AgentLoopReceipt, AgentLoopError> {
        if session.id() != self.record.spec.session_id {
            return Err(AgentLoopError::SessionMismatch);
        }
        let inner = self.record.read();
        if inner.state != AgentLoopState::Running {
            return Err(AgentLoopError::NotRunning(inner.state));
        }
        let message = match session.append_input(message_id, content, created_at_ns) {
            Ok(message) => message,
            Err(error) => {
                increment_saturating(&inner.failed_commands, 1);
                return Err(AgentLoopError::Session(error));
            }
        };
        let command_seq = reserve_commands(&inner, 1);
        Ok(AgentLoopReceipt {
            command_seq,
            message_seq: message.sequence,
            input_seq: message.input_seq,
        })
    }

    /// Admit a group of user inputs while holding the loop state lock once.
    ///
    /// Results retain input order and partial-admission semantics. A failed
    /// item increments the loop failure counter but does not consume a command
    /// sequence; earlier successful items remain admitted.
    ///
    /// # Errors
    ///
    /// Per-item failures mirror [`Self::admit_input`]; partial success is
    /// preserved and failures are returned positionally.
    pub fn admit_input_batch(
        &self,
        session: &Session,
        inputs: Vec<SessionInput>,
    ) -> Vec<Result<AgentLoopReceipt, AgentLoopError>> {
        if inputs.is_empty() {
            return Vec::new();
        }
        if session.id() != self.record.spec.session_id {
            let inner = self.record.read();
            increment_saturating(
                &inner.failed_commands,
                inputs.len().try_into().unwrap_or(u64::MAX),
            );
            return (0..inputs.len())
                .map(|_| Err(AgentLoopError::SessionMismatch))
                .collect();
        }
        let inner = self.record.read();
        if inner.state != AgentLoopState::Running {
            let state = inner.state;
            increment_saturating(
                &inner.failed_commands,
                inputs.len().try_into().unwrap_or(u64::MAX),
            );
            return (0..inputs.len())
                .map(|_| Err(AgentLoopError::NotRunning(state)))
                .collect();
        }

        let results = session.append_input_batch(inputs);
        let successes = results.iter().filter(|result| result.is_ok()).count();
        let first_command_seq = reserve_commands(&inner, successes as u64);
        let mut success_index = 0_u64;
        results
            .into_iter()
            .map(|result| match result {
                Ok(message) => {
                    let command_seq = first_command_seq.saturating_add(success_index);
                    success_index = success_index.saturating_add(1);
                    Ok(AgentLoopReceipt {
                        command_seq,
                        message_seq: message.sequence,
                        input_seq: message.input_seq,
                    })
                }
                Err(error) => {
                    increment_saturating(&inner.failed_commands, 1);
                    Err(AgentLoopError::Session(error))
                }
            })
            .collect()
    }

    /// Admit one assistant/tool/system event through Session.
    pub fn admit_event(
        &self,
        session: &Session,
        event: AgentLoopEvent,
    ) -> Result<AgentLoopReceipt, AgentLoopError> {
        if session.id() != self.record.spec.session_id {
            return Err(AgentLoopError::SessionMismatch);
        }
        let inner = self.record.read();
        if inner.state != AgentLoopState::Running {
            return Err(AgentLoopError::NotRunning(inner.state));
        }
        let message = match session.append_event(
            event.message_id,
            event.input_seq,
            event.role,
            event.content,
            event.created_at_ns,
        ) {
            Ok(message) => message,
            Err(error) => {
                increment_saturating(&inner.failed_commands, 1);
                return Err(AgentLoopError::Session(error));
            }
        };
        let command_seq = reserve_commands(&inner, 1);
        Ok(AgentLoopReceipt {
            command_seq,
            message_seq: message.sequence,
            input_seq: message.input_seq,
        })
    }
}

/// Thread-safe registry for logical AgentLoop routing identities.
pub struct AgentLoopBook {
    loops: RwLock<AgentLoopRegistry>,
}

/// Hash-backed loop lookup paired with a deterministic identity index.
///
/// The hash map remains the authority for duplicate checks and direct handle
/// resolution. The ordered set bounds page traversal to the identities that
/// can actually enter the requested page; both indexes are updated under the
/// enclosing registry write lock.
#[derive(Default)]
struct AgentLoopRegistry {
    loops: HashMap<String, Arc<AgentLoopRecord>>,
    ordered_ids: BTreeSet<String>,
}

impl AgentLoopRegistry {
    fn contains_key(&self, loop_id: &str) -> bool {
        self.loops.contains_key(loop_id)
    }

    fn get(&self, loop_id: &str) -> Option<&Arc<AgentLoopRecord>> {
        self.loops.get(loop_id)
    }

    fn values(&self) -> impl Iterator<Item = &Arc<AgentLoopRecord>> {
        self.loops.values()
    }

    fn insert(&mut self, loop_id: String, record: Arc<AgentLoopRecord>) {
        self.ordered_ids.insert(loop_id.clone());
        self.loops.insert(loop_id, record);
    }
}

impl Default for AgentLoopBook {
    fn default() -> Self {
        Self::new()
    }
}

impl AgentLoopBook {
    /// Create an empty AgentLoop registry.
    pub fn new() -> Self {
        Self {
            loops: RwLock::new(AgentLoopRegistry::default()),
        }
    }

    /// Register one loop identity before session/terminal attachment.
    ///
    /// # Errors
    ///
    /// AgentLoopError when the loop id collides or the spec violates identity invariants.
    pub fn register(&self, spec: AgentLoopSpec) -> Result<AgentLoopSnapshot, AgentLoopError> {
        validate_spec(&spec)?;
        let mut loops = self.write_loops();
        if loops.contains_key(&spec.loop_id) {
            return Err(AgentLoopError::DuplicateLoop(spec.loop_id));
        }
        let record = Arc::new(AgentLoopRecord {
            spec,
            inner: RwLock::new(AgentLoopInner {
                state: AgentLoopState::Created,
                next_command_seq: AtomicU64::new(1),
                accepted_commands: AtomicU64::new(0),
                failed_commands: AtomicU64::new(0),
            }),
            lock_wait_ns: AtomicU64::new(0),
        });
        let snapshot = record.snapshot();
        loops.insert(snapshot.spec.loop_id.clone(), record);
        Ok(snapshot)
    }

    /// Restore a checkpointed logical loop without starting execution.
    ///
    /// Active states are intentionally rejected here. The durable execution
    /// store normalizes unclean active loops to `Failed`; a clean checkpoint
    /// may contain only `Created`, `Stopped`, or `Failed` identities.
    pub fn restore(
        &self,
        snapshot: AgentLoopSnapshot,
    ) -> Result<AgentLoopSnapshot, AgentLoopError> {
        validate_spec(&snapshot.spec)?;
        if snapshot.contract_version != AGENT_LOOP_CONTRACT_VERSION {
            return Err(AgentLoopError::InvalidSnapshot(
                "unsupported AgentLoop contract version".to_owned(),
            ));
        }
        if !matches!(
            snapshot.state,
            AgentLoopState::Created | AgentLoopState::Stopped | AgentLoopState::Failed
        ) {
            return Err(AgentLoopError::InvalidTransition {
                from: snapshot.state,
                to: AgentLoopState::Created,
            });
        }
        if snapshot.next_command_seq == 0 {
            return Err(AgentLoopError::InvalidSnapshot(
                "next command sequence must be positive".to_owned(),
            ));
        }
        if snapshot.accepted_commands >= snapshot.next_command_seq {
            return Err(AgentLoopError::InvalidSnapshot(
                "accepted command count exceeds sequence cursor".to_owned(),
            ));
        }
        let record = Arc::new(AgentLoopRecord {
            spec: snapshot.spec.clone(),
            inner: RwLock::new(AgentLoopInner {
                state: snapshot.state,
                next_command_seq: AtomicU64::new(snapshot.next_command_seq),
                accepted_commands: AtomicU64::new(snapshot.accepted_commands),
                failed_commands: AtomicU64::new(snapshot.failed_commands),
            }),
            lock_wait_ns: AtomicU64::new(snapshot.lock_wait_ns),
        });
        let mut loops = self.write_loops();
        if loops.contains_key(&snapshot.spec.loop_id) {
            return Err(AgentLoopError::DuplicateLoop(snapshot.spec.loop_id));
        }
        loops.insert(snapshot.spec.loop_id.clone(), record);
        Ok(snapshot)
    }

    /// Validate session and terminal correlation before making the loop ready.
    pub fn attach(
        &self,
        loop_id: &str,
        session: &Session,
        terminals: &TerminalBook,
    ) -> Result<AgentLoopSnapshot, AgentLoopError> {
        let record = self.record(loop_id)?;
        if session.id() != record.spec.session_id
            || session.spec().agent_id != record.spec.agent_id
            || session.spec().cell_id != record.spec.cell_id
        {
            return Err(AgentLoopError::SessionMismatch);
        }
        let terminal = terminals
            .snapshot(&record.spec.terminal_id)
            .map_err(AgentLoopError::Terminal)?;
        if terminal.session_id.as_deref() != Some(record.spec.session_id.as_str()) {
            return Err(AgentLoopError::TerminalMismatch);
        }
        if matches!(
            terminal.state,
            TerminalState::Stopped | TerminalState::Closed
        ) {
            return Err(AgentLoopError::TerminalUnavailable(terminal.state));
        }
        let mut inner = record.write();
        transition(&mut inner, AgentLoopState::Ready)?;
        Ok(snapshot_locked(&record.spec, &inner, record.lock_wait_ns()))
    }

    /// Start execution after correlation has been attached.
    ///
    /// # Errors
    ///
    /// InvalidState unless the loop is Created/Ready.
    pub fn start(&self, loop_id: &str) -> Result<AgentLoopSnapshot, AgentLoopError> {
        self.transition(loop_id, AgentLoopState::Running)
    }

    /// Pause admission without discarding session history.
    ///
    /// # Errors
    ///
    /// InvalidState unless currently Running.
    pub fn pause(&self, loop_id: &str) -> Result<AgentLoopSnapshot, AgentLoopError> {
        self.transition(loop_id, AgentLoopState::Paused)
    }

    /// Resume a paused loop.
    ///
    /// # Errors
    ///
    /// InvalidState unless currently Paused.
    pub fn resume(&self, loop_id: &str) -> Result<AgentLoopSnapshot, AgentLoopError> {
        self.transition(loop_id, AgentLoopState::Running)
    }

    /// Stop a loop cleanly after closing admission.
    ///
    /// # Errors
    ///
    /// InvalidState when already Stopped/Failed; in-flight admissions drain first.
    pub fn stop(&self, loop_id: &str, clean: bool) -> Result<AgentLoopSnapshot, AgentLoopError> {
        let record = self.record(loop_id)?;
        let mut inner = record.write();
        if !inner.state.is_terminal() {
            transition(&mut inner, AgentLoopState::Closing)?;
            transition(
                &mut inner,
                if clean {
                    AgentLoopState::Stopped
                } else {
                    AgentLoopState::Failed
                },
            )?;
        }
        Ok(snapshot_locked(&record.spec, &inner, record.lock_wait_ns()))
    }

    /// Admit one user input and let Session assign the authoritative sequence.
    pub fn admit_input(
        &self,
        loop_id: &str,
        session: &Session,
        message_id: impl Into<String>,
        content: impl Into<String>,
        created_at_ns: u64,
    ) -> Result<AgentLoopReceipt, AgentLoopError> {
        self.handle(loop_id)?
            .admit_input(session, message_id, content, created_at_ns)
    }

    /// Admit a group of user inputs through one cached loop-state admission.
    pub fn admit_input_batch(
        &self,
        loop_id: &str,
        session: &Session,
        inputs: Vec<SessionInput>,
    ) -> Result<Vec<Result<AgentLoopReceipt, AgentLoopError>>, AgentLoopError> {
        Ok(self.handle(loop_id)?.admit_input_batch(session, inputs))
    }

    /// Admit one assistant/tool/system event for an existing input sequence.
    pub fn admit_event(
        &self,
        loop_id: &str,
        session: &Session,
        event: AgentLoopEvent,
    ) -> Result<AgentLoopReceipt, AgentLoopError> {
        self.handle(loop_id)?.admit_event(session, event)
    }

    /// Return a cached handle after resolving one registered loop identity.
    ///
    /// # Errors
    ///
    /// SessionMismatch / NotRunning / Session mirroring `admit_input`; failures also bump `failed_commands`.
    pub fn handle(&self, loop_id: &str) -> Result<AgentLoopHandle, AgentLoopError> {
        Ok(AgentLoopHandle {
            record: self.record(loop_id)?,
        })
    }

    /// Return one deterministic loop snapshot.
    ///
    /// # Errors
    ///
    /// AgentLoopError when `loop_id` is unknown; the snapshot itself is
    /// infallible once the record resolves.
    pub fn snapshot(&self, loop_id: &str) -> Result<AgentLoopSnapshot, AgentLoopError> {
        Ok(self.record(loop_id)?.snapshot())
    }

    /// Return all loop snapshots sorted by logical loop identity.
    pub fn snapshots(&self) -> Vec<AgentLoopSnapshot> {
        let records = self.read_loops().values().cloned().collect::<Vec<_>>();
        let mut snapshots = records
            .iter()
            .map(|record| record.snapshot())
            .collect::<Vec<_>>();
        snapshots.sort_unstable_by(|left, right| left.spec.loop_id.cmp(&right.spec.loop_id));
        snapshots
    }

    /// Return a bounded identity-ordered page without materializing every snapshot.
    ///
    /// The exclusive cursor is a loop identity, not a durable scan token.
    /// Concurrent registry writes can therefore alter later pages; checkpoint
    /// callers must continue using [`Self::snapshots`].
    pub fn snapshot_page(
        &self,
        after: Option<&str>,
        limit: usize,
    ) -> Result<BookSnapshotPage<AgentLoopSnapshot>, BookSnapshotPageError> {
        let request = BookSnapshotPageRequest::new(after, limit)?;
        let mut candidates = request.candidates();
        let loops = self.read_loops();
        let mut retained = 0;
        for loop_id in &loops.ordered_ids {
            if !request.is_after_cursor(loop_id) {
                continue;
            }
            if retained == request.candidate_capacity() {
                break;
            }
            let record = loops
                .get(loop_id)
                .expect("ordered loop identity must have a hash entry");
            request.retain_candidate(&mut candidates, loop_id, || Arc::clone(record));
            retained += 1;
        }
        drop(loops);
        Ok(request
            .finish(candidates)
            .map_items(|record| record.snapshot()))
    }

    /// Return a bounded page and measure only blocked registry-read fallback time.
    ///
    /// This crate-private path exists for fixed-work evidence. The public page
    /// API keeps its uncontended read path free of clock calls.
    pub(crate) fn snapshot_page_with_lock_wait(
        &self,
        after: Option<&str>,
        limit: usize,
    ) -> Result<(BookSnapshotPage<AgentLoopSnapshot>, u64), BookSnapshotPageError> {
        let request = BookSnapshotPageRequest::new(after, limit)?;
        let (loops, lock_wait_ns) = match self.loops.try_read() {
            Ok(loops) => (loops, 0),
            Err(TryLockError::WouldBlock) => {
                let started = Instant::now();
                let loops = self.loops.read().unwrap_or_else(PoisonError::into_inner);
                let wait_ns = started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64;
                (loops, wait_ns)
            }
            Err(TryLockError::Poisoned(error)) => (error.into_inner(), 0),
        };
        let mut candidates = request.candidates();
        let mut retained = 0;
        for loop_id in &loops.ordered_ids {
            if !request.is_after_cursor(loop_id) {
                continue;
            }
            if retained == request.candidate_capacity() {
                break;
            }
            let record = loops
                .get(loop_id)
                .expect("ordered loop identity must have a hash entry");
            request.retain_candidate(&mut candidates, loop_id, || Arc::clone(record));
            retained += 1;
        }
        drop(loops);
        Ok((
            request
                .finish(candidates)
                .map_items(|record| record.snapshot()),
            lock_wait_ns,
        ))
    }

    fn transition(
        &self,
        loop_id: &str,
        target: AgentLoopState,
    ) -> Result<AgentLoopSnapshot, AgentLoopError> {
        let record = self.record(loop_id)?;
        let mut inner = record.write();
        transition(&mut inner, target)?;
        Ok(snapshot_locked(&record.spec, &inner, record.lock_wait_ns()))
    }

    fn record(&self, loop_id: &str) -> Result<Arc<AgentLoopRecord>, AgentLoopError> {
        self.read_loops()
            .get(loop_id)
            .cloned()
            .ok_or_else(|| AgentLoopError::LoopNotFound(loop_id.to_owned()))
    }

    fn read_loops(&self) -> RwLockReadGuard<'_, AgentLoopRegistry> {
        self.loops.read().unwrap_or_else(PoisonError::into_inner)
    }

    fn write_loops(&self) -> RwLockWriteGuard<'_, AgentLoopRegistry> {
        self.loops.write().unwrap_or_else(PoisonError::into_inner)
    }
}

fn validate_spec(spec: &AgentLoopSpec) -> Result<(), AgentLoopError> {
    for (name, value) in [
        ("loop_id", &spec.loop_id),
        ("agent_id", &spec.agent_id),
        ("cell_id", &spec.cell_id),
        ("session_id", &spec.session_id),
        ("terminal_id", &spec.terminal_id),
    ] {
        if value.is_empty() || value.len() > AGENT_LOOP_MAX_ID_BYTES {
            return Err(AgentLoopError::InvalidIdentity(name.to_owned()));
        }
    }
    Ok(())
}

fn transition(inner: &mut AgentLoopInner, target: AgentLoopState) -> Result<(), AgentLoopError> {
    if !inner.state.can_transition_to(target) {
        return Err(AgentLoopError::InvalidTransition {
            from: inner.state,
            to: target,
        });
    }
    inner.state = target;
    Ok(())
}

fn snapshot_locked(
    spec: &AgentLoopSpec,
    inner: &AgentLoopInner,
    lock_wait_ns: u64,
) -> AgentLoopSnapshot {
    AgentLoopSnapshot {
        contract_version: AGENT_LOOP_CONTRACT_VERSION,
        spec: spec.clone(),
        state: inner.state,
        next_command_seq: inner.next_command_seq.load(Ordering::Relaxed),
        accepted_commands: inner.accepted_commands.load(Ordering::Relaxed),
        failed_commands: inner.failed_commands.load(Ordering::Relaxed),
        lock_wait_ns,
    }
}

fn increment_saturating(counter: &AtomicU64, amount: u64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
        Some(current.saturating_add(amount))
    });
}

fn reserve_commands(inner: &AgentLoopInner, count: u64) -> u64 {
    let command_seq = inner
        .next_command_seq
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
            Some(current.saturating_add(count))
        })
        .unwrap_or_else(|current| current);
    increment_saturating(&inner.accepted_commands, count);
    command_seq
}
