//! Sharded Rust session truth for the clean-break kernel.
//!
//! This module owns bounded session identity, authoritative input/message
//! sequencing, lifecycle transitions, cursor paging, and checkpoint values.
//! It deliberately does not call an AgentLoop, provider, tool, PTY, or
//! filesystem adapter; those remain above this mechanism boundary.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::sync::{Arc, Mutex, PoisonError, RwLock, TryLockError};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::snapshot::{BookSnapshotPage, BookSnapshotPageError, BookSnapshotPageRequest};

/// Version of the session mechanism contract.
pub const SESSION_CONTRACT_VERSION: u32 = 1;
/// Version of the durable session checkpoint envelope.
pub const SESSION_CHECKPOINT_VERSION: u32 = 1;
/// Number of independent registry shards in the default session book.
pub const SESSION_SHARD_COUNT: usize = 16;
/// Maximum UTF-8 byte length of an identity field.
pub const SESSION_MAX_ID_BYTES: usize = 128;
/// Maximum UTF-8 byte length of a message role.
pub const SESSION_MAX_ROLE_BYTES: usize = 32;
/// Maximum UTF-8 byte length of one message body.
pub const SESSION_MAX_CONTENT_BYTES: usize = 1 << 20;
/// Maximum number of retained messages in one session.
pub const SESSION_MAX_MESSAGES: usize = 16_384;
/// Maximum page size exposed by the public history API.
pub const SESSION_MAX_PAGE_SIZE: usize = 512;

/// Session lifecycle independent of AgentLoop execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionState {
    /// Identity exists but execution has not started.
    Created,
    /// Session accepts new input and events.
    Active,
    /// Close has begun and no new input is accepted.
    Closing,
    /// Session closed cleanly and cannot be reopened.
    Closed,
    /// Session stopped without a clean checkpoint and requires recovery.
    Crashed,
}

impl SessionState {
    /// Return the stable wire spelling of this state.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Active => "active",
            Self::Closing => "closing",
            Self::Closed => "closed",
            Self::Crashed => "crashed",
        }
    }

    fn can_transition_to(self, target: Self) -> bool {
        matches!(
            (self, target),
            (Self::Created, Self::Active | Self::Crashed)
                | (Self::Active, Self::Closing | Self::Crashed)
                | (Self::Closing, Self::Closed | Self::Crashed)
                | (Self::Crashed, Self::Created)
        )
    }
}

/// Closed message roles retained by the session wire contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MessageRole {
    /// System-originated context.
    System,
    /// User-originated input that advances `input_seq`.
    User,
    /// Agent-originated response.
    Assistant,
    /// Tool-originated result.
    Tool,
}

impl MessageRole {
    /// Return the stable wire spelling of this role.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::System => "system",
            Self::User => "user",
            Self::Assistant => "assistant",
            Self::Tool => "tool",
        }
    }
}

/// Declarative identity and retention policy for one session.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionSpec {
    /// Stable session identity.
    /// Unique session identity.
    pub session_id: String,
    /// Owning AgentLoop identity, without an execution callback.
    /// Owning agent execution body.
    pub agent_id: String,
    /// Owning Cell identity.
    /// Owning cell domain.
    pub cell_id: String,
    /// Role selected by the upper-layer dispatcher.
    /// Declared role fragment bound at creation.
    pub role: String,
    /// Maximum retained messages for this session.
    /// Hard bound on retained messages (bounded history).
    pub max_messages: usize,
}

impl SessionSpec {
    /// Build a session specification; validation runs when it is admitted.
    ///
    /// # Errors
    ///
    /// SessionError::InvalidSnapshot / capacity violations from the spec.
    pub fn new(
        session_id: impl Into<String>,
        agent_id: impl Into<String>,
        cell_id: impl Into<String>,
        role: impl Into<String>,
        max_messages: usize,
    ) -> Self {
        Self {
            session_id: session_id.into(),
            agent_id: agent_id.into(),
            cell_id: cell_id.into(),
            role: role.into(),
            max_messages,
        }
    }
}

/// One immutable history entry after admission sequencing.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionMessage {
    /// Monotonic history sequence assigned by the kernel.
    /// Monotonic message sequence assigned by the book.
    pub sequence: u64,
    /// Authoritative user-input sequence associated with this entry.
    /// Authoritative input ordinal allocated exactly once.
    pub input_seq: u64,
    /// Caller-supplied idempotency identity.
    /// Deduplication id supplied by the caller.
    /// Id of the evicted (oldest) message.
    pub message_id: String,
    /// Closed message role.
    /// User/assistant/system classification.
    pub role: MessageRole,
    /// Opaque UTF-8 message body.
    /// Message body (CoT excluded by contract).
    /// Body of the evicted message.
    pub content: String,
    /// Caller-supplied creation timestamp in nanoseconds.
    /// Creation time in nanoseconds since the epoch.
    /// Original creation time of the evicted message.
    pub created_at_ns: u64,
}

/// One user-input admission request for single or grouped session writes.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionInput {
    /// Caller-supplied idempotency identity.
    pub message_id: String,
    /// Opaque UTF-8 user content.
    pub content: String,
    /// Caller-supplied creation timestamp in nanoseconds.
    pub created_at_ns: u64,
}

impl SessionInput {
    /// Build one user-input admission request.
    pub fn new(
        message_id: impl Into<String>,
        content: impl Into<String>,
        created_at_ns: u64,
    ) -> Self {
        Self {
            message_id: message_id.into(),
            content: content.into(),
            created_at_ns,
        }
    }
}

/// Cursor-paged history response.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionPage {
    /// Entries after the requested cursor.
    /// Page of messages in stable identity order.
    pub items: Vec<SessionMessage>,
    /// Last returned sequence when another page exists.
    /// Exclusive continuation cursor; None ends paging.
    pub next_cursor: Option<u64>,
    /// Total retained entries at the observation point.
    /// Total retained messages across all pages.
    pub total: usize,
}

/// Serializable session state used for clean resume and explicit recovery.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionSnapshot {
    /// Session contract version.
    /// Checkpoint schema version.
    pub contract_version: u32,
    /// Session identity and retention policy.
    /// Immutable creation specification.
    pub spec: SessionSpec,
    /// Current lifecycle state.
    /// Lifecycle state at checkpoint time.
    pub state: SessionState,
    /// Next user input sequence to admit.
    /// Next input ordinal to allocate on resume.
    pub next_input_seq: u64,
    /// Next history sequence to assign.
    /// Next message sequence to allocate on resume.
    pub next_message_seq: u64,
    /// Whether the last checkpoint was clean.
    /// False marks unclean shutdown; sessions load as crashed.
    pub clean_shutdown: bool,
    /// Bounded retained history in ascending sequence order.
    /// Retained history snapshot.
    pub messages: Vec<SessionMessage>,
}

/// Versioned checkpoint envelope for a session snapshot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionCheckpoint {
    /// Checkpoint envelope version.
    /// Envelope version of the outer checkpoint file.
    pub checkpoint_version: u32,
    /// Snapshot captured at the checkpoint boundary.
    /// Embedded snapshot payload.
    pub snapshot: SessionSnapshot,
}

/// Structured failures at the session mechanism boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionError {
    /// An identity field was empty or exceeded its byte limit.
    InvalidIdentity(String),
    /// A message body or role exceeded its byte limit.
    InvalidMessage(String),
    /// The retention capacity was zero or above the global bound.
    InvalidCapacity,
    /// A lifecycle transition was not valid.
    InvalidTransition {
        from: SessionState,
        to: SessionState,
    },
    /// The session does not accept writes in its current state.
    NotWritable(SessionState),
    /// The supplied message id was already retained.
    DuplicateMessage(String),
    /// A non-user event referenced an unknown input sequence.
    UnknownInputSequence(u64),
    /// The next user input sequence did not match the authoritative counter.
    InputSequenceMismatch { expected: u64, actual: u64 },
    /// The bounded history has no admission capacity left.
    HistoryFull,
    /// A cursor or page size was invalid.
    InvalidPage,
    /// A persisted snapshot violated an invariant.
    InvalidSnapshot(String),
    /// A session id already exists in a book.
    DuplicateSession(String),
    /// A requested session id was not found.
    SessionNotFound(String),
    /// A registry cannot be created with zero shards.
    InvalidShardCount,
}

struct SessionInner {
    state: SessionState,
    next_input_seq: u64,
    next_message_seq: u64,
    clean_shutdown: bool,
    messages: Vec<SessionMessage>,
    message_ids: HashSet<String>,
}

/// Thread-safe bounded session entity.
pub struct Session {
    spec: SessionSpec,
    inner: Mutex<SessionInner>,
}

impl Session {
    /// Create a validated session in the `created` state.
    ///
    /// # Errors
    ///
    /// InvalidSnapshot when the spec violates identity/bound invariants.
    pub fn new(spec: SessionSpec) -> Result<Self, SessionError> {
        validate_spec(&spec)?;
        Ok(Self {
            spec,
            inner: Mutex::new(SessionInner {
                state: SessionState::Created,
                next_input_seq: 1,
                next_message_seq: 1,
                clean_shutdown: true,
                messages: Vec::new(),
                message_ids: HashSet::new(),
            }),
        })
    }

    /// Restore a session from a validated snapshot without side effects.
    ///
    /// # Errors
    ///
    /// InvalidSnapshot on version mismatch or broken identity/sequence
    /// invariants.
    pub fn from_snapshot(snapshot: SessionSnapshot) -> Result<Self, SessionError> {
        if snapshot.contract_version != SESSION_CONTRACT_VERSION {
            return Err(SessionError::InvalidSnapshot(
                "unsupported session contract version".to_owned(),
            ));
        }
        validate_spec(&snapshot.spec)?;
        validate_messages(
            &snapshot.messages,
            snapshot.next_input_seq,
            snapshot.next_message_seq,
            snapshot.spec.max_messages,
        )?;
        if snapshot.state == SessionState::Crashed && snapshot.clean_shutdown {
            return Err(SessionError::InvalidSnapshot(
                "crashed session cannot claim clean shutdown".to_owned(),
            ));
        }
        Ok(Self {
            spec: snapshot.spec,
            // Validation above guarantees that every retained id is unique.
            // Keep a side index so admission does not scan the full history.
            inner: Mutex::new(SessionInner {
                state: snapshot.state,
                next_input_seq: snapshot.next_input_seq,
                next_message_seq: snapshot.next_message_seq,
                clean_shutdown: snapshot.clean_shutdown,
                message_ids: snapshot
                    .messages
                    .iter()
                    .map(|message| message.message_id.clone())
                    .collect(),
                messages: snapshot.messages,
            }),
        })
    }

    /// Restore a session from a versioned checkpoint envelope.
    ///
    /// # Errors
    ///
    /// InvalidSnapshot when envelope/checkpoint validation fails.
    pub fn from_checkpoint(checkpoint: SessionCheckpoint) -> Result<Self, SessionError> {
        if checkpoint.checkpoint_version != SESSION_CHECKPOINT_VERSION {
            return Err(SessionError::InvalidSnapshot(
                "unsupported session checkpoint version".to_owned(),
            ));
        }
        Self::from_snapshot(checkpoint.snapshot)
    }

    /// Validate a checkpoint without constructing a live session.
    ///
    /// # Errors
    ///
    /// InvalidSnapshot enumerating every violated invariant.
    pub fn validate(checkpoint: &SessionCheckpoint) -> Result<(), SessionError> {
        if checkpoint.checkpoint_version != SESSION_CHECKPOINT_VERSION {
            return Err(SessionError::InvalidSnapshot(
                "unsupported session checkpoint version".to_owned(),
            ));
        }
        Self::from_snapshot(checkpoint.snapshot.clone()).map(|_| ())
    }

    /// Return the stable session identity.
    pub fn id(&self) -> &str {
        &self.spec.session_id
    }

    /// Return an immutable copy of the declarative session specification.
    pub fn spec(&self) -> SessionSpec {
        self.spec.clone()
    }

    /// Return the current lifecycle state.
    pub fn state(&self) -> SessionState {
        self.lock().state
    }

    /// Apply one lifecycle transition with fail-closed validation.
    ///
    /// # Errors
    ///
    /// InvalidTransition when the FSM forbids `target` from the current
    /// state.
    pub fn transition(&self, target: SessionState) -> Result<(), SessionError> {
        let mut inner = self.lock();
        if !inner.state.can_transition_to(target) {
            return Err(SessionError::InvalidTransition {
                from: inner.state,
                to: target,
            });
        }
        inner.state = target;
        inner.clean_shutdown = target != SessionState::Crashed;
        Ok(())
    }

    /// Mark the session active after creation or explicit crash recovery.
    ///
    /// # Errors
    ///
    /// InvalidTransition unless the current state admits activation.
    pub fn activate(&self) -> Result<(), SessionError> {
        self.transition(SessionState::Active)
    }

    /// Close cleanly or record an unclean crash without deleting history.
    ///
    /// # Errors
    ///
    /// InvalidTransition from states that forbid closing; `clean=false`
    /// marks the persisted checkpoint as unclean.
    pub fn close(&self, clean: bool) -> Result<(), SessionError> {
        if !clean {
            let state = self.state();
            if state == SessionState::Crashed {
                return Ok(());
            }
            return self.transition(SessionState::Crashed);
        }
        if self.state() == SessionState::Active {
            self.transition(SessionState::Closing)?;
        }
        self.transition(SessionState::Closed)
    }

    /// Move a crashed session back to `created` for an explicit reactivation.
    ///
    /// # Errors
    ///
    /// InvalidTransition unless the session is in the crashed state.
    pub fn recover(&self) -> Result<(), SessionError> {
        self.transition(SessionState::Created)
    }

    /// Append one user input and advance the authoritative `input_seq`.
    pub fn append_input(
        &self,
        message_id: impl Into<String>,
        content: impl Into<String>,
        created_at_ns: u64,
    ) -> Result<SessionMessage, SessionError> {
        let mut inner = self.lock();
        append_input_locked(
            &mut inner,
            &self.spec,
            SessionInput::new(message_id, content, created_at_ns),
        )
    }

    /// Append a group of user inputs under one session lock.
    ///
    /// Results retain input order and partial-admission semantics: an invalid
    /// or duplicate item does not roll back successful earlier items.
    pub fn append_input_batch(
        &self,
        inputs: Vec<SessionInput>,
    ) -> Vec<Result<SessionMessage, SessionError>> {
        if inputs.is_empty() {
            return Vec::new();
        }
        let mut inner = self.lock();
        inputs
            .into_iter()
            .map(|input| append_input_locked(&mut inner, &self.spec, input))
            .collect()
    }

    /// Append an assistant/tool/system event for an existing input sequence.
    pub fn append_event(
        &self,
        message_id: impl Into<String>,
        input_seq: u64,
        role: MessageRole,
        content: impl Into<String>,
        created_at_ns: u64,
    ) -> Result<SessionMessage, SessionError> {
        if role == MessageRole::User {
            return Err(SessionError::InvalidMessage(
                "user events must use append_input".to_owned(),
            ));
        }
        let mut inner = self.lock();
        ensure_writable(inner.state)?;
        if input_seq == 0 || input_seq >= inner.next_input_seq {
            return Err(SessionError::UnknownInputSequence(input_seq));
        }
        let message_id = message_id.into();
        let content = content.into();
        validate_message_fields(&message_id, role, &content)?;
        ensure_unique_message_id(&inner, &message_id)?;
        ensure_message_capacity(&inner, &self.spec)?;
        let message = SessionMessage {
            sequence: inner.next_message_seq,
            input_seq,
            message_id,
            role,
            content,
            created_at_ns,
        };
        inner.next_message_seq = inner.next_message_seq.saturating_add(1);
        inner.message_ids.insert(message.message_id.clone());
        inner.messages.push(message.clone());
        Ok(message)
    }

    /// Return a bounded cursor page of retained history.
    pub fn messages_page(
        &self,
        cursor: Option<u64>,
        limit: usize,
    ) -> Result<SessionPage, SessionError> {
        if limit == 0 || limit > SESSION_MAX_PAGE_SIZE {
            return Err(SessionError::InvalidPage);
        }
        let inner = self.lock();
        let start = match cursor {
            None => 0,
            Some(cursor) => inner
                .messages
                .binary_search_by_key(&cursor, |message| message.sequence)
                .ok()
                .map(|index| index + 1)
                .ok_or(SessionError::InvalidPage)?,
        };
        let end = (start + limit).min(inner.messages.len());
        let items = inner.messages[start..end].to_vec();
        let next_cursor = if end < inner.messages.len() {
            items.last().map(|message| message.sequence)
        } else {
            None
        };
        Ok(SessionPage {
            items,
            next_cursor,
            total: inner.messages.len(),
        })
    }

    /// Return the number of retained history entries.
    pub fn message_count(&self) -> usize {
        self.lock().messages.len()
    }

    /// Capture a serializable snapshot at one lock observation point.
    pub fn snapshot(&self) -> SessionSnapshot {
        let inner = self.lock();
        SessionSnapshot {
            contract_version: SESSION_CONTRACT_VERSION,
            spec: self.spec.clone(),
            state: inner.state,
            next_input_seq: inner.next_input_seq,
            next_message_seq: inner.next_message_seq,
            clean_shutdown: inner.clean_shutdown,
            messages: inner.messages.clone(),
        }
    }

    /// Capture a versioned checkpoint envelope.
    pub fn checkpoint(&self) -> SessionCheckpoint {
        SessionCheckpoint {
            checkpoint_version: SESSION_CHECKPOINT_VERSION,
            snapshot: self.snapshot(),
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, SessionInner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Sharded registry with concurrent read snapshots and exclusive admission writes.
pub struct SessionBook {
    shards: Vec<RwLock<SessionShard>>,
}

/// One registry shard with hash lookup and an ordered identity index.
///
/// The hash map keeps duplicate admission and direct lookup at expected O(1),
/// while the ordered set lets bounded page reads avoid scanning unrelated
/// identities. Both structures are mutated under the same shard write lock.
#[derive(Default)]
struct SessionShard {
    sessions: HashMap<String, Arc<Session>>,
    ordered_ids: BTreeSet<String>,
}

impl SessionShard {
    fn contains_key(&self, session_id: &str) -> bool {
        self.sessions.contains_key(session_id)
    }

    fn get(&self, session_id: &str) -> Option<&Arc<Session>> {
        self.sessions.get(session_id)
    }

    fn insert(&mut self, session_id: String, session: Arc<Session>) {
        self.ordered_ids.insert(session_id.clone());
        self.sessions.insert(session_id, session);
    }

    fn remove(&mut self, session_id: &str) -> Option<Arc<Session>> {
        let session = self.sessions.remove(session_id);
        if session.is_some() {
            self.ordered_ids.remove(session_id);
        }
        session
    }
}

impl Default for SessionBook {
    fn default() -> Self {
        Self::new(SESSION_SHARD_COUNT).expect("default session shard count is valid")
    }
}

impl SessionBook {
    /// Create a session registry with explicit shard count.
    ///
    /// # Errors
    ///
    /// SessionError::InvalidShardCount when `shard_count` is zero.
    pub fn new(shard_count: usize) -> Result<Self, SessionError> {
        if shard_count == 0 {
            return Err(SessionError::InvalidShardCount);
        }
        let shards = (0..shard_count)
            .map(|_| RwLock::new(SessionShard::default()))
            .collect();
        Ok(Self { shards })
    }

    /// Create and atomically admit one session identity.
    ///
    /// # Errors
    ///
    /// SessionError::SessionFull at message bound; DuplicateMessageId on id collision; InvalidTransition unless Active.
    pub fn create(&self, spec: SessionSpec) -> Result<Arc<Session>, SessionError> {
        let session = Arc::new(Session::new(spec)?);
        let mut shard = self.shards[self.shard_index(session.id())]
            .write()
            .unwrap_or_else(PoisonError::into_inner);
        if shard.contains_key(session.id()) {
            return Err(SessionError::DuplicateSession(session.id().to_owned()));
        }
        shard.insert(session.id().to_owned(), Arc::clone(&session));
        Ok(session)
    }

    /// Create one session and report only waiting behind a write-locked shard.
    ///
    /// This crate-private path exists for fixed-work evidence. The public
    /// admission path does not read the clock on an uncontended write lock.
    pub(crate) fn create_with_lock_wait(
        &self,
        spec: SessionSpec,
    ) -> Result<(Arc<Session>, u64), SessionError> {
        let session = Arc::new(Session::new(spec)?);
        let shard = &self.shards[self.shard_index(session.id())];
        let (mut shard, lock_wait_ns) = match shard.try_write() {
            Ok(shard) => (shard, 0),
            Err(TryLockError::WouldBlock) => {
                let started = Instant::now();
                let shard = shard.write().unwrap_or_else(PoisonError::into_inner);
                let wait_ns = started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64;
                (shard, wait_ns)
            }
            Err(TryLockError::Poisoned(error)) => (error.into_inner(), 0),
        };
        if shard.contains_key(session.id()) {
            return Err(SessionError::DuplicateSession(session.id().to_owned()));
        }
        shard.insert(session.id().to_owned(), Arc::clone(&session));
        Ok((session, lock_wait_ns))
    }

    /// Create several sessions while acquiring each shard lock once.
    ///
    /// Results retain input order and are independent: an invalid or duplicate
    /// item does not discard successful admissions from other items. The
    /// caller still receives one owned session handle per successful item.
    pub fn create_batch(&self, specs: Vec<SessionSpec>) -> Vec<Result<Arc<Session>, SessionError>> {
        let mut results: Vec<Option<Result<Arc<Session>, SessionError>>> =
            (0..specs.len()).map(|_| None).collect();
        let mut groups: Vec<Vec<(usize, Arc<Session>)>> =
            (0..self.shards.len()).map(|_| Vec::new()).collect();

        for (index, spec) in specs.into_iter().enumerate() {
            match Session::new(spec) {
                Ok(session) => {
                    let session = Arc::new(session);
                    let shard_index = self.shard_index(session.id());
                    groups[shard_index].push((index, session));
                }
                Err(error) => results[index] = Some(Err(error)),
            }
        }

        for (shard_index, group) in groups.into_iter().enumerate() {
            if group.is_empty() {
                continue;
            }
            let mut shard = self.shards[shard_index]
                .write()
                .unwrap_or_else(PoisonError::into_inner);
            for (index, session) in group {
                if shard.contains_key(session.id()) {
                    results[index] =
                        Some(Err(SessionError::DuplicateSession(session.id().to_owned())));
                } else {
                    shard.insert(session.id().to_owned(), Arc::clone(&session));
                    results[index] = Some(Ok(session));
                }
            }
        }

        results
            .into_iter()
            .map(|result| result.expect("every batch item has a result"))
            .collect()
    }

    /// Restore and atomically admit a checkpointed session identity.
    ///
    /// # Errors
    ///
    /// InvalidSnapshot on version/identity/sequence divergence.
    pub fn restore(&self, checkpoint: SessionCheckpoint) -> Result<Arc<Session>, SessionError> {
        let session = Arc::new(Session::from_checkpoint(checkpoint)?);
        let mut shard = self.shards[self.shard_index(session.id())]
            .write()
            .unwrap_or_else(PoisonError::into_inner);
        if shard.contains_key(session.id()) {
            return Err(SessionError::DuplicateSession(session.id().to_owned()));
        }
        shard.insert(session.id().to_owned(), Arc::clone(&session));
        Ok(session)
    }

    /// Return a session handle without holding the shard lock afterward.
    pub fn get(&self, session_id: &str) -> Option<Arc<Session>> {
        self.shards[self.shard_index(session_id)]
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .get(session_id)
            .cloned()
    }

    /// Remove only a closed session and return its final checkpoint.
    ///
    /// # Errors
    ///
    /// InvalidState unless the session is Closed/Crashed.
    pub fn remove_closed(&self, session_id: &str) -> Result<SessionCheckpoint, SessionError> {
        let mut shard = self.shards[self.shard_index(session_id)]
            .write()
            .unwrap_or_else(PoisonError::into_inner);
        let session = shard
            .get(session_id)
            .cloned()
            .ok_or_else(|| SessionError::SessionNotFound(session_id.to_owned()))?;
        if session.state() != SessionState::Closed {
            return Err(SessionError::NotWritable(session.state()));
        }
        shard.remove(session_id);
        Ok(session.checkpoint())
    }

    /// Return deterministic snapshots sorted by session identity.
    pub fn snapshots(&self) -> Vec<SessionSnapshot> {
        let mut snapshots = Vec::new();
        for shard in &self.shards {
            let shard = shard.read().unwrap_or_else(PoisonError::into_inner);
            snapshots.extend(shard.sessions.values().map(|session| session.snapshot()));
        }
        snapshots.sort_by(|left, right| left.spec.session_id.cmp(&right.spec.session_id));
        snapshots
    }

    /// Return a bounded identity-ordered page without materializing every snapshot.
    ///
    /// The exclusive cursor is a session identity, not a durable scan token.
    /// Concurrent registry writes can therefore alter later pages; checkpoint
    /// callers must continue using [`Self::snapshots`].
    pub fn snapshot_page(
        &self,
        after: Option<&str>,
        limit: usize,
    ) -> Result<BookSnapshotPage<SessionSnapshot>, BookSnapshotPageError> {
        let request = BookSnapshotPageRequest::new(after, limit)?;
        let mut candidates = request.candidates();
        for shard in &self.shards {
            let shard = shard.read().unwrap_or_else(PoisonError::into_inner);
            // Each shard is ordered; later identities cannot enter this page
            // after the first limit+1 eligible identities from that shard.
            let mut retained = 0;
            for session_id in &shard.ordered_ids {
                if !request.is_after_cursor(session_id) {
                    continue;
                }
                if retained == request.candidate_capacity() {
                    break;
                }
                let session = shard
                    .sessions
                    .get(session_id)
                    .expect("ordered session identity must have a hash entry");
                request.retain_candidate(&mut candidates, session_id, || Arc::clone(session));
                retained += 1;
            }
        }
        Ok(request
            .finish(candidates)
            .map_items(|session| session.snapshot()))
    }

    /// Return a bounded page with aggregate waiting behind write-locked shards.
    ///
    /// This is deliberately crate-private benchmark instrumentation. The
    /// public read API avoids clock reads on its uncontended fast path.
    pub(crate) fn snapshot_page_with_lock_wait(
        &self,
        after: Option<&str>,
        limit: usize,
    ) -> Result<(BookSnapshotPage<SessionSnapshot>, u64), BookSnapshotPageError> {
        let request = BookSnapshotPageRequest::new(after, limit)?;
        let mut candidates = request.candidates();
        let mut lock_wait_ns = 0_u64;
        for shard in &self.shards {
            let shard = match shard.try_read() {
                Ok(shard) => shard,
                Err(TryLockError::WouldBlock) => {
                    let started = Instant::now();
                    let shard = shard.read().unwrap_or_else(PoisonError::into_inner);
                    let wait_ns = started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64;
                    lock_wait_ns = lock_wait_ns.saturating_add(wait_ns);
                    shard
                }
                Err(TryLockError::Poisoned(error)) => error.into_inner(),
            };
            // Each shard is ordered; later identities cannot enter this page
            // after the first limit+1 eligible identities from that shard.
            let mut retained = 0;
            for session_id in &shard.ordered_ids {
                if !request.is_after_cursor(session_id) {
                    continue;
                }
                if retained == request.candidate_capacity() {
                    break;
                }
                let session = shard
                    .sessions
                    .get(session_id)
                    .expect("ordered session identity must have a hash entry");
                request.retain_candidate(&mut candidates, session_id, || Arc::clone(session));
                retained += 1;
            }
        }
        Ok((
            request
                .finish(candidates)
                .map_items(|session| session.snapshot()),
            lock_wait_ns,
        ))
    }

    fn shard_index(&self, session_id: &str) -> usize {
        let mut hash = 2_166_136_261_u32;
        for byte in session_id.as_bytes() {
            hash ^= u32::from(*byte);
            hash = hash.wrapping_mul(16_777_619);
        }
        (hash as usize) % self.shards.len()
    }
}

fn validate_spec(spec: &SessionSpec) -> Result<(), SessionError> {
    validate_identity(&spec.session_id, "session_id")?;
    validate_identity(&spec.agent_id, "agent_id")?;
    validate_identity(&spec.cell_id, "cell_id")?;
    validate_identity(&spec.role, "role")?;
    if spec.max_messages == 0 || spec.max_messages > SESSION_MAX_MESSAGES {
        return Err(SessionError::InvalidCapacity);
    }
    Ok(())
}

fn validate_identity(value: &str, name: &str) -> Result<(), SessionError> {
    if value.is_empty() || value.len() > SESSION_MAX_ID_BYTES {
        return Err(SessionError::InvalidIdentity(name.to_owned()));
    }
    Ok(())
}

fn validate_message_fields(
    message_id: &str,
    role: MessageRole,
    content: &str,
) -> Result<(), SessionError> {
    if message_id.is_empty() || message_id.len() > SESSION_MAX_ID_BYTES {
        return Err(SessionError::InvalidMessage("message_id".to_owned()));
    }
    if role.as_str().len() > SESSION_MAX_ROLE_BYTES || content.len() > SESSION_MAX_CONTENT_BYTES {
        return Err(SessionError::InvalidMessage("message size".to_owned()));
    }
    Ok(())
}

fn ensure_writable(state: SessionState) -> Result<(), SessionError> {
    if state == SessionState::Active {
        Ok(())
    } else {
        Err(SessionError::NotWritable(state))
    }
}

fn ensure_message_capacity(inner: &SessionInner, spec: &SessionSpec) -> Result<(), SessionError> {
    if inner.messages.len() >= spec.max_messages {
        Err(SessionError::HistoryFull)
    } else {
        Ok(())
    }
}

fn ensure_unique_message_id(inner: &SessionInner, message_id: &str) -> Result<(), SessionError> {
    if inner.message_ids.contains(message_id) {
        Err(SessionError::DuplicateMessage(message_id.to_owned()))
    } else {
        Ok(())
    }
}

fn append_input_locked(
    inner: &mut SessionInner,
    spec: &SessionSpec,
    input: SessionInput,
) -> Result<SessionMessage, SessionError> {
    ensure_writable(inner.state)?;
    validate_message_fields(&input.message_id, MessageRole::User, &input.content)?;
    ensure_unique_message_id(inner, &input.message_id)?;
    ensure_message_capacity(inner, spec)?;

    let message = SessionMessage {
        sequence: inner.next_message_seq,
        input_seq: inner.next_input_seq,
        message_id: input.message_id,
        role: MessageRole::User,
        content: input.content,
        created_at_ns: input.created_at_ns,
    };
    inner.next_input_seq = inner.next_input_seq.saturating_add(1);
    inner.next_message_seq = inner.next_message_seq.saturating_add(1);
    inner.message_ids.insert(message.message_id.clone());
    inner.messages.push(message.clone());
    Ok(message)
}

fn validate_messages(
    messages: &[SessionMessage],
    next_input_seq: u64,
    next_message_seq: u64,
    max_messages: usize,
) -> Result<(), SessionError> {
    if messages.len() > max_messages || messages.len() > SESSION_MAX_MESSAGES {
        return Err(SessionError::InvalidSnapshot(
            "message history exceeds retention capacity".to_owned(),
        ));
    }
    let mut ids = HashSet::new();
    let mut previous_sequence = 0_u64;
    let mut highest_input = 0_u64;
    for message in messages {
        validate_message_fields(&message.message_id, message.role, &message.content)
            .map_err(|_| SessionError::InvalidSnapshot("invalid message fields".to_owned()))?;
        if message.sequence == 0 || message.sequence <= previous_sequence {
            return Err(SessionError::InvalidSnapshot(
                "message sequences must be strictly increasing".to_owned(),
            ));
        }
        if !ids.insert(message.message_id.clone()) {
            return Err(SessionError::DuplicateMessage(message.message_id.clone()));
        }
        if message.input_seq == 0 || message.input_seq >= next_input_seq {
            return Err(SessionError::InvalidSnapshot(
                "message input sequence is outside the authoritative range".to_owned(),
            ));
        }
        if message.role == MessageRole::User {
            highest_input = highest_input.max(message.input_seq);
        }
        previous_sequence = message.sequence;
    }
    if next_message_seq <= previous_sequence || next_input_seq <= highest_input {
        return Err(SessionError::InvalidSnapshot(
            "next sequence counters do not follow retained history".to_owned(),
        ));
    }
    Ok(())
}
