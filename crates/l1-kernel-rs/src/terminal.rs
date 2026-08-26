//! Rust-owned terminal/session substrate for the clean-break kernel.
//!
//! This module owns only terminal identity, session/process bindings, lifecycle
//! terminality, and bounded byte mailboxes. PTY creation, subprocess control,
//! AgentLoop execution, rendering, and policy remain adapter responsibilities.

use std::collections::{BTreeSet, HashMap, VecDeque};
use std::sync::{
    Arc, Mutex, MutexGuard, PoisonError, RwLock, RwLockReadGuard, RwLockWriteGuard, TryLockError,
};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::snapshot::{BookSnapshotPage, BookSnapshotPageError, BookSnapshotPageRequest};
use crate::substrate::ProcessHandle;

/// Version of the terminal substrate contract.
pub const TERMINAL_CONTRACT_VERSION: u32 = 1;
/// Version of the terminal lifecycle model.
pub const TERMINAL_LIFECYCLE_VERSION: u32 = 1;
/// Version of the bounded input/output mailbox shape.
pub const TERMINAL_MAILBOX_VERSION: u32 = 1;
/// Maximum frame size accepted by the metadata-only candidate.
pub const TERMINAL_MAX_FRAME_BYTES: usize = 1 << 20;

/// Descriptor of the terminal mechanism carried by the Rust kernel.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalContractDescriptor {
    /// Terminal substrate contract version.
    /// Required protocol contract version.
    pub contract_version: u32,
    /// Lifecycle state model version.
    /// Required terminal lifecycle version.
    pub lifecycle_version: u32,
    /// Input/output mailbox shape version.
    /// Required mailbox framing version.
    pub mailbox_version: u32,
    /// Maximum frame size accepted by the candidate.
    /// Hard per-frame byte cap shared with the wire layer.
    pub max_frame_bytes: usize,
}

impl TerminalContractDescriptor {
    /// Return the descriptor consumed by a current Rust assembly.
    pub const fn current() -> Self {
        Self {
            contract_version: TERMINAL_CONTRACT_VERSION,
            lifecycle_version: TERMINAL_LIFECYCLE_VERSION,
            mailbox_version: TERMINAL_MAILBOX_VERSION,
            max_frame_bytes: TERMINAL_MAX_FRAME_BYTES,
        }
    }

    /// Validate a host-supplied descriptor before assembly.
    ///
    /// # Errors
    ///
    /// ContractVersion / LifecycleVersion / MailboxVersion when a version
    /// falls outside the supported range; FrameLimit when `max_frame_bytes`
    /// is zero or exceeds the transport ceiling.
    pub fn validate(&self) -> Result<(), TerminalContractError> {
        let expected = Self::current();
        if self.contract_version != expected.contract_version {
            return Err(TerminalContractError::ContractVersion {
                expected: expected.contract_version,
                actual: self.contract_version,
            });
        }
        if self.lifecycle_version != expected.lifecycle_version {
            return Err(TerminalContractError::LifecycleVersion {
                expected: expected.lifecycle_version,
                actual: self.lifecycle_version,
            });
        }
        if self.mailbox_version != expected.mailbox_version {
            return Err(TerminalContractError::MailboxVersion {
                expected: expected.mailbox_version,
                actual: self.mailbox_version,
            });
        }
        if self.max_frame_bytes != expected.max_frame_bytes {
            return Err(TerminalContractError::FrameLimit {
                expected: expected.max_frame_bytes,
                actual: self.max_frame_bytes,
            });
        }
        Ok(())
    }
}

/// Version mismatch at the assembly boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalContractError {
    /// The terminal contract version is unsupported.
    ContractVersion { expected: u32, actual: u32 },
    /// The lifecycle model version is unsupported.
    LifecycleVersion { expected: u32, actual: u32 },
    /// The mailbox model version is unsupported.
    MailboxVersion { expected: u32, actual: u32 },
    /// The frame limit diverges from the current contract.
    FrameLimit { expected: usize, actual: usize },
}

/// Lifecycle state of a terminal independent of frontend attachment.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalState {
    /// Registered but not yet bound to a process.
    Created,
    /// Bound to a process and eligible to start.
    Ready,
    /// Running work for the bound process.
    Running,
    /// Permanently stopped; no restart is permitted.
    Stopped,
    /// Permanently closed; no binding or I/O is permitted.
    Closed,
}

impl TerminalState {
    /// Return the stable wire spelling used by snapshots and adapters.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Ready => "ready",
            Self::Running => "running",
            Self::Stopped => "stopped",
            Self::Closed => "closed",
        }
    }
}

/// Stream carried by a terminal mailbox frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalStream {
    /// Input directed toward the AgentLoop adapter.
    Input,
    /// Normal output emitted by the AgentLoop adapter.
    Output,
    /// Diagnostic output emitted by the AgentLoop adapter.
    Error,
}

/// One bounded terminal frame. Bytes stay opaque to the kernel.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalFrame {
    /// Monotonic sequence within the input or output mailbox.
    /// Monotonic frame sequence within its stream.
    pub sequence: u64,
    /// Stream represented by this frame.
    /// Direction this frame belongs to (input/output).
    pub stream: TerminalStream,
    /// Opaque bytes; encoding and rendering belong to the adapter.
    /// Opaque frame bytes; interpretation is host-owned.
    pub data: Vec<u8>,
}

/// Declarative terminal registration input.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalSpec {
    /// Stable terminal identity.
    /// Unique terminal identity.
    /// Terminal this snapshot describes.
    pub terminal_id: String,
    /// Maximum queued input frames.
    /// Bounded input mailbox capacity in frames.
    pub input_capacity: usize,
    /// Maximum queued output frames.
    /// Bounded output mailbox capacity in frames.
    pub output_capacity: usize,
}

impl TerminalSpec {
    /// Build a terminal registration request.
    pub fn new(
        terminal_id: impl Into<String>,
        input_capacity: usize,
        output_capacity: usize,
    ) -> Self {
        Self {
            terminal_id: terminal_id.into(),
            input_capacity,
            output_capacity,
        }
    }
}

/// Public terminal state snapshot with queue counts but no queued bytes.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalSnapshot {
    /// Stable terminal identity.
    pub terminal_id: String,
    /// Current lifecycle state.
    /// Current lifecycle state.
    pub state: TerminalState,
    /// Attached frontend/session identity, if any.
    /// Attached session, if any (single-tenant binding).
    pub session_id: Option<String>,
    /// Bound generation-tagged process handle encoded as a raw value.
    /// Bound process handle id, if any.
    pub process_id: Option<u64>,
    /// Configured input mailbox capacity.
    pub input_capacity: usize,
    /// Configured output mailbox capacity.
    pub output_capacity: usize,
    /// Number of queued input frames.
    /// Frames currently queued for input.
    pub input_depth: usize,
    /// Number of queued output frames.
    /// Frames currently queued for output.
    pub output_depth: usize,
    /// Cumulative input frames rejected by capacity or frame-size limits.
    /// Cumulative input frames dropped under backpressure.
    pub input_dropped: u64,
    /// Cumulative output frames rejected by capacity or frame-size limits.
    /// Cumulative output frames dropped under backpressure.
    pub output_dropped: u64,
}

/// Structured terminal substrate failure.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalError {
    /// An identity or process handle was empty/invalid.
    InvalidIdentity,
    /// A terminal identity was already registered.
    DuplicateTerminal { terminal_id: String },
    /// The requested terminal does not exist.
    NotFound { terminal_id: String },
    /// The session is already attached to another terminal.
    SessionAlreadyAttached { session_id: String },
    /// The process handle is already bound to another terminal.
    ProcessAlreadyBound { process_id: u64 },
    /// A session was expected but was not attached.
    SessionNotAttached { terminal_id: String },
    /// A process was expected but was not bound.
    ProcessNotBound { terminal_id: String },
    /// An operation is invalid for the current lifecycle state.
    InvalidState {
        terminal_id: String,
        state: TerminalState,
        operation: String,
    },
    /// A mailbox capacity is zero.
    InvalidCapacity,
    /// A frame exceeds the bounded contract.
    FrameTooLarge { size: usize, limit: usize },
    /// A mailbox is full; the frame was not silently overwritten.
    MailboxFull { stream: TerminalStream },
    /// A persisted snapshot cannot be restored without live process state.
    InvalidSnapshot(String),
}

#[derive(Debug)]
struct Mailbox {
    capacity: usize,
    next_sequence: u64,
    dropped: u64,
    frames: VecDeque<TerminalFrame>,
}

impl Mailbox {
    fn new(capacity: usize) -> Result<Self, TerminalError> {
        if capacity == 0 {
            return Err(TerminalError::InvalidCapacity);
        }
        Ok(Self {
            capacity,
            next_sequence: 1,
            dropped: 0,
            frames: VecDeque::with_capacity(capacity),
        })
    }

    fn push(&mut self, stream: TerminalStream, data: Vec<u8>) -> Result<(), TerminalError> {
        if data.len() > TERMINAL_MAX_FRAME_BYTES {
            self.dropped = self.dropped.saturating_add(1);
            return Err(TerminalError::FrameTooLarge {
                size: data.len(),
                limit: TERMINAL_MAX_FRAME_BYTES,
            });
        }
        if self.frames.len() == self.capacity {
            self.dropped = self.dropped.saturating_add(1);
            return Err(TerminalError::MailboxFull { stream });
        }
        let frame = TerminalFrame {
            sequence: self.next_sequence,
            stream,
            data,
        };
        self.next_sequence = self.next_sequence.saturating_add(1);
        self.frames.push_back(frame);
        Ok(())
    }

    fn push_batch(
        &mut self,
        stream: TerminalStream,
        frames: Vec<Vec<u8>>,
    ) -> Vec<Result<(), TerminalError>> {
        frames
            .into_iter()
            .map(|data| self.push(stream, data))
            .collect()
    }

    fn pop(&mut self) -> Option<TerminalFrame> {
        self.frames.pop_front()
    }

    fn pop_batch(&mut self, limit: usize) -> Vec<TerminalFrame> {
        let count = limit.min(self.frames.len());
        self.frames.drain(..count).collect()
    }
}

#[derive(Debug)]
struct TerminalRecord {
    terminal_id: String,
    state: TerminalState,
    session_id: Option<String>,
    process_handle: Option<ProcessHandle>,
    input: Mailbox,
    output: Mailbox,
}

impl TerminalRecord {
    fn snapshot(&self) -> TerminalSnapshot {
        TerminalSnapshot {
            terminal_id: self.terminal_id.clone(),
            state: self.state,
            session_id: self.session_id.clone(),
            process_id: self.process_handle.map(ProcessHandle::raw),
            input_capacity: self.input.capacity,
            output_capacity: self.output.capacity,
            input_depth: self.input.frames.len(),
            output_depth: self.output.frames.len(),
            input_dropped: self.input.dropped,
            output_dropped: self.output.dropped,
        }
    }
}

#[derive(Debug, Default)]
struct TerminalInner {
    terminals: HashMap<String, Arc<Mutex<TerminalRecord>>>,
    ordered_ids: BTreeSet<String>,
    sessions: HashMap<String, String>,
    processes: HashMap<u64, String>,
}

/// Thread-safe terminal/session/process binding registry.
pub struct TerminalBook {
    inner: RwLock<TerminalInner>,
}

impl Default for TerminalBook {
    fn default() -> Self {
        Self::new()
    }
}

impl TerminalBook {
    /// Create an empty terminal registry.
    pub fn new() -> Self {
        Self {
            inner: RwLock::new(TerminalInner::default()),
        }
    }

    /// Register one terminal before any process or session is attached.
    ///
    /// # Errors
    ///
    /// DuplicateTerminal when the id already exists; InvalidCapacity when
    /// either mailbox capacity is zero.
    pub fn register(&self, spec: TerminalSpec) -> Result<TerminalSnapshot, TerminalError> {
        validate_identity(&spec.terminal_id)?;
        let input = Mailbox::new(spec.input_capacity)?;
        let output = Mailbox::new(spec.output_capacity)?;
        let mut inner = self.write_inner();
        if inner.terminals.contains_key(&spec.terminal_id) {
            return Err(TerminalError::DuplicateTerminal {
                terminal_id: spec.terminal_id,
            });
        }
        let record = TerminalRecord {
            terminal_id: spec.terminal_id.clone(),
            state: TerminalState::Created,
            session_id: None,
            process_handle: None,
            input,
            output,
        };
        let snapshot = record.snapshot();
        inner.ordered_ids.insert(spec.terminal_id.clone());
        inner
            .terminals
            .insert(spec.terminal_id, Arc::new(Mutex::new(record)));
        Ok(snapshot)
    }

    /// Restore a metadata-only terminal snapshot from the Rust state root.
    ///
    /// Mailbox bytes and live process ownership are deliberately not persisted.
    /// A restored terminal therefore has to be `Created`, `Stopped`, or
    /// `Closed`; `Ready`/`Running` snapshots must be normalized by the durable
    /// store before this method is called.
    ///
    /// # Errors
    ///
    /// InvalidSnapshot when state/version/capacity invariants break;
    /// DuplicateTerminal on id collision; SessionAlreadyAttached when the
    /// snapshot still carries an active session binding.
    pub fn restore(&self, snapshot: TerminalSnapshot) -> Result<TerminalSnapshot, TerminalError> {
        validate_identity(&snapshot.terminal_id)?;
        if snapshot.input_capacity == 0 || snapshot.output_capacity == 0 {
            return Err(TerminalError::InvalidSnapshot(
                "terminal mailbox capacity must be positive".to_owned(),
            ));
        }
        if snapshot.input_depth != 0 || snapshot.output_depth != 0 {
            return Err(TerminalError::InvalidSnapshot(
                "queued terminal frames are not persisted".to_owned(),
            ));
        }
        if snapshot.process_id.is_some() {
            return Err(TerminalError::InvalidSnapshot(
                "live process binding cannot be restored".to_owned(),
            ));
        }
        if matches!(
            snapshot.state,
            TerminalState::Ready | TerminalState::Running
        ) {
            return Err(TerminalError::InvalidSnapshot(
                "active terminal requires explicit process rebind".to_owned(),
            ));
        }
        if snapshot.state == TerminalState::Closed && snapshot.session_id.is_some() {
            return Err(TerminalError::InvalidSnapshot(
                "closed terminal cannot retain a session binding".to_owned(),
            ));
        }
        let input = Mailbox {
            capacity: snapshot.input_capacity,
            next_sequence: 1,
            dropped: snapshot.input_dropped,
            frames: VecDeque::new(),
        };
        let output = Mailbox {
            capacity: snapshot.output_capacity,
            next_sequence: 1,
            dropped: snapshot.output_dropped,
            frames: VecDeque::new(),
        };
        let record = Arc::new(Mutex::new(TerminalRecord {
            terminal_id: snapshot.terminal_id.clone(),
            state: snapshot.state,
            session_id: snapshot.session_id.clone(),
            process_handle: None,
            input,
            output,
        }));
        let mut inner = self.write_inner();
        if inner.terminals.contains_key(&snapshot.terminal_id) {
            return Err(TerminalError::DuplicateTerminal {
                terminal_id: snapshot.terminal_id,
            });
        }
        if let Some(session_id) = &snapshot.session_id {
            validate_identity(session_id)?;
            if inner.sessions.contains_key(session_id) {
                return Err(TerminalError::SessionAlreadyAttached {
                    session_id: session_id.clone(),
                });
            }
        }
        inner.ordered_ids.insert(snapshot.terminal_id.clone());
        inner.terminals.insert(snapshot.terminal_id.clone(), record);
        if let Some(session_id) = snapshot.session_id.as_ref() {
            inner
                .sessions
                .insert(session_id.clone(), snapshot.terminal_id.clone());
        }
        Ok(snapshot)
    }

    /// Attach one unique session to a terminal without changing its process state.
    ///
    /// # Errors
    ///
    /// SessionAlreadyAttached when another session holds the terminal;
    /// InvalidState when the terminal is not in a bindable state.
    pub fn attach(
        &self,
        terminal_id: &str,
        session_id: impl Into<String>,
    ) -> Result<TerminalSnapshot, TerminalError> {
        let session_id = session_id.into();
        validate_identity(&session_id)?;
        let mut inner = self.write_inner();
        if inner.sessions.contains_key(&session_id) {
            return Err(TerminalError::SessionAlreadyAttached { session_id });
        }
        let record_handle = get_record(&inner, terminal_id)?;
        let mut record = lock_record(&record_handle);
        reject_closed(&record, "attach")?;
        if record.session_id.is_some() {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: record.state,
                operation: "attach_existing_session".to_owned(),
            });
        }
        record.session_id = Some(session_id.clone());
        let snapshot = record.snapshot();
        inner.sessions.insert(session_id, terminal_id.to_owned());
        Ok(snapshot)
    }

    /// Detach a session while leaving a running AgentLoop process untouched.
    ///
    /// # Errors
    ///
    /// InvalidState when no session is attached to `terminal_id`.
    pub fn detach(&self, terminal_id: &str) -> Result<TerminalSnapshot, TerminalError> {
        let mut inner = self.write_inner();
        let record_handle = get_record(&inner, terminal_id)?;
        let mut record = lock_record(&record_handle);
        reject_closed(&record, "detach")?;
        let session_id =
            record
                .session_id
                .take()
                .ok_or_else(|| TerminalError::SessionNotAttached {
                    terminal_id: terminal_id.to_owned(),
                })?;
        let snapshot = record.snapshot();
        inner.sessions.remove(&session_id);
        Ok(snapshot)
    }

    /// Bind one generation-tagged process handle before starting execution.
    pub fn bind_process(
        &self,
        terminal_id: &str,
        process_id: u64,
    ) -> Result<TerminalSnapshot, TerminalError> {
        let process_handle =
            ProcessHandle::from_raw(process_id).ok_or(TerminalError::InvalidIdentity)?;
        self.bind_process_handle(terminal_id, process_handle)
    }

    /// Bind a typed generation-tagged process handle before starting execution.
    pub fn bind_process_handle(
        &self,
        terminal_id: &str,
        process_handle: ProcessHandle,
    ) -> Result<TerminalSnapshot, TerminalError> {
        let process_id = process_handle.raw();
        let mut inner = self.write_inner();
        if inner.processes.contains_key(&process_id) {
            return Err(TerminalError::ProcessAlreadyBound { process_id });
        }
        let record_handle = get_record(&inner, terminal_id)?;
        let mut record = lock_record(&record_handle);
        if record.state != TerminalState::Created {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: record.state,
                operation: "bind_process".to_owned(),
            });
        }
        record.process_handle = Some(process_handle);
        record.state = TerminalState::Ready;
        let snapshot = record.snapshot();
        inner.processes.insert(process_id, terminal_id.to_owned());
        Ok(snapshot)
    }

    /// Start a terminal once its process binding exists.
    ///
    /// # Errors
    ///
    /// TerminalError::InvalidState unless Created; InvalidCapacity surfaces spec violations.
    pub fn start(&self, terminal_id: &str) -> Result<TerminalSnapshot, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        if record.process_handle.is_none() {
            return Err(TerminalError::ProcessNotBound {
                terminal_id: terminal_id.to_owned(),
            });
        }
        if record.state != TerminalState::Ready {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: record.state,
                operation: "start".to_owned(),
            });
        }
        record.state = TerminalState::Running;
        Ok(record.snapshot())
    }

    /// Stop a running terminal permanently; stopped terminals cannot restart.
    ///
    /// # Errors
    ///
    /// InvalidState unless Running.
    pub fn stop(&self, terminal_id: &str) -> Result<TerminalSnapshot, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        if record.state != TerminalState::Running {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: record.state,
                operation: "stop".to_owned(),
            });
        }
        record.state = TerminalState::Stopped;
        Ok(record.snapshot())
    }

    /// Close a non-running terminal and release its session/process bindings.
    ///
    /// # Errors
    ///
    /// InvalidState when already closed; pending frames are dropped by contract.
    pub fn close(&self, terminal_id: &str) -> Result<TerminalSnapshot, TerminalError> {
        let mut inner = self.write_inner();
        let record_handle = get_record(&inner, terminal_id)?;
        let mut record = lock_record(&record_handle);
        if record.state == TerminalState::Running {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: record.state,
                operation: "close".to_owned(),
            });
        }
        record.state = TerminalState::Closed;
        let session_id = record.session_id.take();
        let process_handle = record.process_handle.take();
        let snapshot = record.snapshot();
        if let Some(session_id) = session_id {
            inner.sessions.remove(&session_id);
        }
        if let Some(process_handle) = process_handle {
            inner.processes.remove(&process_handle.raw());
        }
        Ok(snapshot)
    }

    /// Submit opaque input to a running terminal without waiting or overwriting.
    pub fn submit_input(
        &self,
        terminal_id: &str,
        data: Vec<u8>,
    ) -> Result<TerminalSnapshot, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        require_running(&record, terminal_id, "submit_input")?;
        record.input.push(TerminalStream::Input, data)?;
        Ok(record.snapshot())
    }

    /// Consume the oldest input frame for the AgentLoop adapter.
    ///
    /// # Errors
    ///
    /// InvalidState when closed; empty Ok signals no queued frame.
    pub fn take_input(&self, terminal_id: &str) -> Result<Option<TerminalFrame>, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        require_running(&record, terminal_id, "take_input")?;
        Ok(record.input.pop())
    }

    /// Submit a batch of opaque input frames under one terminal record lock.
    ///
    /// Results retain input order and preserve per-frame capacity and size
    /// errors. Successful frames before a rejection remain admitted, matching
    /// repeated [`Self::submit_input`] calls without repeated registry lookup.
    pub fn submit_input_batch(
        &self,
        terminal_id: &str,
        frames: Vec<Vec<u8>>,
    ) -> Result<Vec<Result<(), TerminalError>>, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        require_running(&record, terminal_id, "submit_input_batch")?;
        Ok(record.input.push_batch(TerminalStream::Input, frames))
    }

    /// Consume up to `limit` input frames under one terminal record lock.
    pub fn take_input_batch(
        &self,
        terminal_id: &str,
        limit: usize,
    ) -> Result<Vec<TerminalFrame>, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        require_running(&record, terminal_id, "take_input_batch")?;
        Ok(record.input.pop_batch(limit))
    }

    /// Publish normal or diagnostic output from the AgentLoop adapter.
    pub fn publish_output(
        &self,
        terminal_id: &str,
        stream: TerminalStream,
        data: Vec<u8>,
    ) -> Result<TerminalSnapshot, TerminalError> {
        if stream == TerminalStream::Input {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: TerminalState::Running,
                operation: "publish_input_as_output".to_owned(),
            });
        }
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        if record.state != TerminalState::Running {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: record.state,
                operation: "publish_output".to_owned(),
            });
        }
        record.output.push(stream, data)?;
        Ok(record.snapshot())
    }

    /// Publish a batch of normal or diagnostic output frames under one lock.
    ///
    /// Each result corresponds to one input item. An input-stream item is
    /// rejected as it would be by [`Self::publish_output`], while valid items
    /// continue through the bounded mailbox and update drop counters.
    pub fn publish_output_batch(
        &self,
        terminal_id: &str,
        frames: Vec<(TerminalStream, Vec<u8>)>,
    ) -> Result<Vec<Result<(), TerminalError>>, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        require_running(&record, terminal_id, "publish_output_batch")?;
        let results = frames
            .into_iter()
            .map(|(stream, data)| {
                if stream == TerminalStream::Input {
                    return Err(TerminalError::InvalidState {
                        terminal_id: terminal_id.to_owned(),
                        state: TerminalState::Running,
                        operation: "publish_input_as_output".to_owned(),
                    });
                }
                record.output.push(stream, data)
            })
            .collect();
        Ok(results)
    }

    /// Consume the oldest output frame, including during stopped-state drain.
    ///
    /// # Errors
    ///
    /// InvalidState when closed; empty Ok signals no queued frame.
    pub fn take_output(&self, terminal_id: &str) -> Result<Option<TerminalFrame>, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        if matches!(record.state, TerminalState::Created | TerminalState::Ready) {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: record.state,
                operation: "take_output".to_owned(),
            });
        }
        Ok(record.output.pop())
    }

    /// Consume up to `limit` output frames under one terminal record lock.
    pub fn take_output_batch(
        &self,
        terminal_id: &str,
        limit: usize,
    ) -> Result<Vec<TerminalFrame>, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        let mut record = lock_record(&record_handle);
        if matches!(record.state, TerminalState::Created | TerminalState::Ready) {
            return Err(TerminalError::InvalidState {
                terminal_id: terminal_id.to_owned(),
                state: record.state,
                operation: "take_output_batch".to_owned(),
            });
        }
        Ok(record.output.pop_batch(limit))
    }

    /// Return one deterministic terminal snapshot.
    ///
    /// # Errors
    ///
    /// Infallible: returns the current bounded snapshot.
    pub fn snapshot(&self, terminal_id: &str) -> Result<TerminalSnapshot, TerminalError> {
        let record_handle = self.record_handle(terminal_id)?;
        Ok(lock_record(&record_handle).snapshot())
    }

    /// Return all terminal snapshots in stable identity order.
    pub fn snapshots(&self) -> Vec<TerminalSnapshot> {
        let record_handles = {
            let inner = self.read_inner();
            inner.terminals.values().cloned().collect::<Vec<_>>()
        };
        let mut snapshots = record_handles
            .iter()
            .map(|record| lock_record(record).snapshot())
            .collect::<Vec<_>>();
        snapshots.sort_unstable_by(|left, right| left.terminal_id.cmp(&right.terminal_id));
        snapshots
    }

    /// Return a bounded identity-ordered page without materializing every snapshot.
    ///
    /// The exclusive cursor is a terminal identity, not a durable scan token.
    /// Concurrent registry writes can therefore alter later pages; checkpoint
    /// callers must continue using [`Self::snapshots`].
    pub fn snapshot_page(
        &self,
        after: Option<&str>,
        limit: usize,
    ) -> Result<BookSnapshotPage<TerminalSnapshot>, BookSnapshotPageError> {
        let request = BookSnapshotPageRequest::new(after, limit)?;
        let mut candidates = request.candidates();
        let inner = self.read_inner();
        let mut retained = 0;
        for terminal_id in &inner.ordered_ids {
            if !request.is_after_cursor(terminal_id) {
                continue;
            }
            if retained == request.candidate_capacity() {
                break;
            }
            let record = inner
                .terminals
                .get(terminal_id)
                .expect("ordered terminal identity must have a hash entry");
            request.retain_candidate(&mut candidates, terminal_id, || Arc::clone(record));
            retained += 1;
        }
        drop(inner);
        Ok(request
            .finish(candidates)
            .map_items(|record| lock_record(&record).snapshot()))
    }

    /// Return a bounded page and measure only blocked registry-read fallback time.
    ///
    /// This crate-private path exists for fixed-work evidence. The public page
    /// API keeps its uncontended read path free of clock calls.
    pub(crate) fn snapshot_page_with_lock_wait(
        &self,
        after: Option<&str>,
        limit: usize,
    ) -> Result<(BookSnapshotPage<TerminalSnapshot>, u64), BookSnapshotPageError> {
        let request = BookSnapshotPageRequest::new(after, limit)?;
        let (inner, lock_wait_ns) = match self.inner.try_read() {
            Ok(inner) => (inner, 0),
            Err(TryLockError::WouldBlock) => {
                let started = Instant::now();
                let inner = self.inner.read().unwrap_or_else(PoisonError::into_inner);
                let wait_ns = started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64;
                (inner, wait_ns)
            }
            Err(TryLockError::Poisoned(error)) => (error.into_inner(), 0),
        };
        let mut candidates = request.candidates();
        let mut retained = 0;
        for terminal_id in &inner.ordered_ids {
            if !request.is_after_cursor(terminal_id) {
                continue;
            }
            if retained == request.candidate_capacity() {
                break;
            }
            let record = inner
                .terminals
                .get(terminal_id)
                .expect("ordered terminal identity must have a hash entry");
            request.retain_candidate(&mut candidates, terminal_id, || Arc::clone(record));
            retained += 1;
        }
        drop(inner);
        Ok((
            request
                .finish(candidates)
                .map_items(|record| lock_record(&record).snapshot()),
            lock_wait_ns,
        ))
    }

    fn record_handle(
        &self,
        terminal_id: &str,
    ) -> Result<Arc<Mutex<TerminalRecord>>, TerminalError> {
        let inner = self.read_inner();
        get_record(&inner, terminal_id)
    }

    fn read_inner(&self) -> RwLockReadGuard<'_, TerminalInner> {
        self.inner.read().unwrap_or_else(PoisonError::into_inner)
    }

    fn write_inner(&self) -> RwLockWriteGuard<'_, TerminalInner> {
        self.inner.write().unwrap_or_else(PoisonError::into_inner)
    }
}

fn validate_identity(value: &str) -> Result<(), TerminalError> {
    if value.trim().is_empty() || value.contains('\0') {
        return Err(TerminalError::InvalidIdentity);
    }
    Ok(())
}

fn get_record(
    inner: &TerminalInner,
    terminal_id: &str,
) -> Result<Arc<Mutex<TerminalRecord>>, TerminalError> {
    inner
        .terminals
        .get(terminal_id)
        .cloned()
        .ok_or_else(|| TerminalError::NotFound {
            terminal_id: terminal_id.to_owned(),
        })
}

fn lock_record(record: &Arc<Mutex<TerminalRecord>>) -> MutexGuard<'_, TerminalRecord> {
    record.lock().unwrap_or_else(PoisonError::into_inner)
}

fn reject_closed(record: &TerminalRecord, operation: &str) -> Result<(), TerminalError> {
    if record.state == TerminalState::Closed {
        return Err(TerminalError::InvalidState {
            terminal_id: record.terminal_id.clone(),
            state: record.state,
            operation: operation.to_owned(),
        });
    }
    Ok(())
}

fn require_running(
    record: &TerminalRecord,
    terminal_id: &str,
    operation: &str,
) -> Result<(), TerminalError> {
    if record.state != TerminalState::Running {
        return Err(TerminalError::InvalidState {
            terminal_id: terminal_id.to_owned(),
            state: record.state,
            operation: operation.to_owned(),
        });
    }
    Ok(())
}
