//! Durable Rust-owned execution checkpoint for sessions, terminals, and loops.
//!
//! This is a clean-break state adapter. It captures metadata from the three
//! lower-layer books into one versioned JSON document, never imports Python
//! state, and never persists live process ownership or queued terminal bytes.
//! An unclean load turns active session/loop state into explicit recovery
//! states and turns active terminals into unbound `Created` terminals.

use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::agent_loop::{
    AGENT_LOOP_CONTRACT_VERSION, AGENT_LOOP_MAX_ID_BYTES, AgentLoopBook, AgentLoopError,
    AgentLoopSnapshot, AgentLoopState,
};
use crate::session::{
    SESSION_CHECKPOINT_VERSION, Session, SessionBook, SessionCheckpoint, SessionError,
    SessionSnapshot, SessionState,
};
use crate::terminal::{TerminalBook, TerminalError, TerminalSnapshot, TerminalState};

/// Version of the combined execution checkpoint document.
pub const EXECUTION_STORE_VERSION: u32 = 1;
/// Relative path owned by the Rust execution state adapter.
pub const EXECUTION_STORE_RELATIVE_PATH: &str = "snapshots/execution/checkpoint.json";

/// Versioned snapshot of the Rust execution books.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionStoreDocument {
    /// Store document schema version.
    pub store_version: u32,
    /// Monotonic generation assigned after each successful write.
    pub generation: u64,
    /// Whether the source books were captured after a clean shutdown.
    pub clean_shutdown: bool,
    /// Session truth checkpoints sorted by session id.
    pub sessions: Vec<SessionCheckpoint>,
    /// Terminal metadata snapshots sorted by terminal id.
    pub terminals: Vec<TerminalSnapshot>,
    /// Logical loop snapshots sorted by loop id.
    pub loops: Vec<AgentLoopSnapshot>,
}

/// Reconstructed books returned by an execution-store load.
pub struct ExecutionState {
    /// Restored session truth.
    pub sessions: SessionBook,
    /// Restored terminal metadata.
    pub terminals: TerminalBook,
    /// Restored AgentLoop identities.
    pub loops: AgentLoopBook,
}

/// Fail-closed errors at the combined execution checkpoint boundary.
#[derive(Debug)]
pub enum ExecutionStoreError {
    /// Filesystem operation failed.
    Io(io::Error),
    /// The persisted document violated its version or cross-book contract.
    InvalidDocument { path: PathBuf, message: String },
    /// A session checkpoint was rejected.
    Session(SessionError),
    /// A terminal snapshot was rejected.
    Terminal(TerminalError),
    /// A loop snapshot was rejected.
    AgentLoop(AgentLoopError),
    /// A clean checkpoint attempted to persist writable session state.
    WritableSession(String),
    /// A clean checkpoint attempted to persist an active terminal.
    WritableTerminal(String),
    /// A clean checkpoint attempted to persist a live process binding.
    LiveProcessBinding(String),
    /// A clean checkpoint attempted to persist an active logical loop.
    WritableLoop(String),
    /// A terminal still had queued bytes that the metadata checkpoint cannot retain.
    PendingTerminalFrames(String),
    /// The requested root is not a directory.
    RootNotDirectory(PathBuf),
    /// One book references an identity absent from another book.
    MissingReference { owner: String, target: String },
}

impl std::fmt::Display for ExecutionStoreError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "execution store I/O failed: {error}"),
            Self::InvalidDocument { path, message } => {
                write!(
                    formatter,
                    "invalid execution document {}: {message}",
                    path.display()
                )
            }
            Self::Session(error) => write!(formatter, "session checkpoint rejected: {error:?}"),
            Self::Terminal(error) => write!(formatter, "terminal checkpoint rejected: {error:?}"),
            Self::AgentLoop(error) => write!(formatter, "AgentLoop checkpoint rejected: {error:?}"),
            Self::WritableSession(id) => {
                write!(formatter, "clean checkpoint contains writable session {id}")
            }
            Self::WritableTerminal(id) => {
                write!(formatter, "clean checkpoint contains active terminal {id}")
            }
            Self::LiveProcessBinding(id) => {
                write!(formatter, "terminal {id} retains a live process binding")
            }
            Self::WritableLoop(id) => {
                write!(formatter, "clean checkpoint contains active AgentLoop {id}")
            }
            Self::PendingTerminalFrames(id) => write!(formatter, "terminal {id} has queued frames"),
            Self::RootNotDirectory(path) => write!(
                formatter,
                "execution store root is not a directory: {}",
                path.display()
            ),
            Self::MissingReference { owner, target } => {
                write!(formatter, "{owner} references missing identity {target}")
            }
        }
    }
}

impl std::error::Error for ExecutionStoreError {}

impl From<io::Error> for ExecutionStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<SessionError> for ExecutionStoreError {
    fn from(error: SessionError) -> Self {
        Self::Session(error)
    }
}

impl From<TerminalError> for ExecutionStoreError {
    fn from(error: TerminalError) -> Self {
        Self::Terminal(error)
    }
}

impl From<AgentLoopError> for ExecutionStoreError {
    fn from(error: AgentLoopError) -> Self {
        Self::AgentLoop(error)
    }
}

/// Filesystem adapter for a Rust-owned combined execution checkpoint.
pub struct ExecutionStore {
    path: PathBuf,
    generation: u64,
}

impl ExecutionStore {
    /// Open a new Rust state root or validate an existing checkpoint.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, ExecutionStoreError> {
        let root = root.as_ref();
        if root.exists() && !root.is_dir() {
            return Err(ExecutionStoreError::RootNotDirectory(root.to_path_buf()));
        }
        let path = root.join(EXECUTION_STORE_RELATIVE_PATH);
        if !path.exists() {
            return Ok(Self {
                path,
                generation: 0,
            });
        }
        if fs::metadata(&path)?.len() == 0 {
            return Ok(Self {
                path,
                generation: 0,
            });
        }
        let document = read_document(&path)?;
        validate_document(&document, &path)?;
        Ok(Self {
            path,
            generation: document.generation,
        })
    }

    /// Return the durable checkpoint path.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Return the last successfully persisted generation.
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    /// Read the current document, returning an empty fresh collection if absent.
    pub fn document(&self) -> Result<ExecutionStoreDocument, ExecutionStoreError> {
        if !self.path.exists() || fs::metadata(&self.path)?.len() == 0 {
            return Ok(empty_document());
        }
        let document = read_document(&self.path)?;
        validate_document(&document, &self.path)?;
        Ok(document)
    }

    /// Persist all three execution books as one atomically replaced document.
    pub fn save(
        &mut self,
        sessions: &SessionBook,
        terminals: &TerminalBook,
        loops: &AgentLoopBook,
        clean_shutdown: bool,
    ) -> Result<ExecutionStoreDocument, ExecutionStoreError> {
        let session_snapshots = sessions.snapshots();
        let session_ids = session_snapshots
            .iter()
            .map(|snapshot| snapshot.spec.session_id.clone())
            .collect::<HashSet<_>>();
        let mut session_checkpoints = session_snapshots
            .into_iter()
            .map(|snapshot| {
                if clean_shutdown
                    && matches!(
                        snapshot.state,
                        SessionState::Active | SessionState::Closing | SessionState::Crashed
                    )
                {
                    return Err(ExecutionStoreError::WritableSession(
                        snapshot.spec.session_id.clone(),
                    ));
                }
                let snapshot = if clean_shutdown {
                    clean_session(snapshot)
                } else {
                    crash_session(snapshot)
                };
                Ok(SessionCheckpoint {
                    checkpoint_version: SESSION_CHECKPOINT_VERSION,
                    snapshot,
                })
            })
            .collect::<Result<Vec<_>, ExecutionStoreError>>()?;
        session_checkpoints.sort_unstable_by(|left, right| {
            left.snapshot
                .spec
                .session_id
                .cmp(&right.snapshot.spec.session_id)
        });

        let mut terminal_snapshots = terminals
            .snapshots()
            .into_iter()
            .map(|snapshot| {
                if let Some(session_id) = &snapshot.session_id
                    && !session_ids.contains(session_id)
                {
                    return Err(ExecutionStoreError::MissingReference {
                        owner: format!("terminal {}", snapshot.terminal_id),
                        target: session_id.clone(),
                    });
                }
                if clean_shutdown {
                    if snapshot.process_id.is_some() {
                        return Err(ExecutionStoreError::LiveProcessBinding(
                            snapshot.terminal_id,
                        ));
                    }
                    if matches!(
                        snapshot.state,
                        TerminalState::Ready | TerminalState::Running
                    ) {
                        return Err(ExecutionStoreError::WritableTerminal(snapshot.terminal_id));
                    }
                    if snapshot.input_depth != 0 || snapshot.output_depth != 0 {
                        return Err(ExecutionStoreError::PendingTerminalFrames(
                            snapshot.terminal_id,
                        ));
                    }
                    Ok(snapshot)
                } else {
                    Ok(recover_terminal(snapshot))
                }
            })
            .collect::<Result<Vec<_>, ExecutionStoreError>>()?;
        terminal_snapshots.sort_unstable_by(|left, right| left.terminal_id.cmp(&right.terminal_id));
        let terminal_ids = terminal_snapshots
            .iter()
            .map(|snapshot| snapshot.terminal_id.clone())
            .collect::<HashSet<_>>();

        let mut loop_snapshots = loops
            .snapshots()
            .into_iter()
            .map(|snapshot| {
                if !session_ids.contains(&snapshot.spec.session_id) {
                    return Err(ExecutionStoreError::MissingReference {
                        owner: format!("AgentLoop {}", snapshot.spec.loop_id),
                        target: snapshot.spec.session_id.clone(),
                    });
                }
                if !terminal_ids.contains(&snapshot.spec.terminal_id) {
                    return Err(ExecutionStoreError::MissingReference {
                        owner: format!("AgentLoop {}", snapshot.spec.loop_id),
                        target: snapshot.spec.terminal_id.clone(),
                    });
                }
                if clean_shutdown
                    && !matches!(
                        snapshot.state,
                        AgentLoopState::Created | AgentLoopState::Stopped | AgentLoopState::Failed
                    )
                {
                    return Err(ExecutionStoreError::WritableLoop(snapshot.spec.loop_id));
                }
                Ok(if clean_shutdown {
                    snapshot
                } else {
                    recover_loop(snapshot)
                })
            })
            .collect::<Result<Vec<_>, ExecutionStoreError>>()?;
        loop_snapshots.sort_unstable_by(|left, right| left.spec.loop_id.cmp(&right.spec.loop_id));

        let document = ExecutionStoreDocument {
            store_version: EXECUTION_STORE_VERSION,
            generation: self.generation.saturating_add(1),
            clean_shutdown,
            sessions: session_checkpoints,
            terminals: terminal_snapshots,
            loops: loop_snapshots,
        };
        validate_document(&document, &self.path)?;
        let bytes = serde_json::to_vec(&document).map_err(|error| {
            ExecutionStoreError::InvalidDocument {
                path: self.path.clone(),
                message: error.to_string(),
            }
        })?;
        atomic_write(&self.path, &bytes)?;
        self.generation = document.generation;
        Ok(document)
    }

    /// Load all books, normalizing unclean active state before restore.
    pub fn load_state(&self, shard_count: usize) -> Result<ExecutionState, ExecutionStoreError> {
        let document = self.document()?;
        let sessions = SessionBook::new(shard_count)?;
        for checkpoint in document.sessions {
            sessions.restore(if document.clean_shutdown {
                checkpoint
            } else {
                SessionCheckpoint {
                    checkpoint_version: checkpoint.checkpoint_version,
                    snapshot: crash_session(checkpoint.snapshot),
                }
            })?;
        }
        let terminals = TerminalBook::new();
        for snapshot in document.terminals {
            terminals.restore(if document.clean_shutdown {
                snapshot
            } else {
                recover_terminal(snapshot)
            })?;
        }
        let loops = AgentLoopBook::new();
        for snapshot in document.loops {
            loops.restore(if document.clean_shutdown {
                snapshot
            } else {
                recover_loop(snapshot)
            })?;
        }
        Ok(ExecutionState {
            sessions,
            terminals,
            loops,
        })
    }
}

fn empty_document() -> ExecutionStoreDocument {
    ExecutionStoreDocument {
        store_version: EXECUTION_STORE_VERSION,
        generation: 0,
        clean_shutdown: true,
        sessions: Vec::new(),
        terminals: Vec::new(),
        loops: Vec::new(),
    }
}

fn clean_session(mut snapshot: SessionSnapshot) -> SessionSnapshot {
    snapshot.clean_shutdown = true;
    snapshot
}

fn crash_session(mut snapshot: SessionSnapshot) -> SessionSnapshot {
    if snapshot.state != SessionState::Closed {
        snapshot.state = SessionState::Crashed;
        snapshot.clean_shutdown = false;
    }
    snapshot
}

fn recover_terminal(mut snapshot: TerminalSnapshot) -> TerminalSnapshot {
    snapshot.process_id = None;
    snapshot.input_depth = 0;
    snapshot.output_depth = 0;
    if matches!(
        snapshot.state,
        TerminalState::Ready | TerminalState::Running
    ) {
        snapshot.state = TerminalState::Created;
    }
    snapshot
}

fn recover_loop(mut snapshot: AgentLoopSnapshot) -> AgentLoopSnapshot {
    if matches!(
        snapshot.state,
        AgentLoopState::Ready
            | AgentLoopState::Running
            | AgentLoopState::Paused
            | AgentLoopState::Closing
    ) {
        snapshot.state = AgentLoopState::Failed;
    }
    snapshot
}

fn validate_document(
    document: &ExecutionStoreDocument,
    path: &Path,
) -> Result<(), ExecutionStoreError> {
    if document.store_version != EXECUTION_STORE_VERSION {
        return Err(ExecutionStoreError::InvalidDocument {
            path: path.to_path_buf(),
            message: format!("unsupported store version {}", document.store_version),
        });
    }
    let mut session_ids = HashSet::new();
    let mut previous_session = None;
    for checkpoint in &document.sessions {
        if checkpoint.checkpoint_version != SESSION_CHECKPOINT_VERSION {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "unsupported session checkpoint version".to_owned(),
            });
        }
        Session::validate(checkpoint)?;
        let id = checkpoint.snapshot.spec.session_id.as_str();
        if previous_session.is_some_and(|previous: &str| previous >= id) {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "sessions must be sorted and unique".to_owned(),
            });
        }
        if !session_ids.insert(id.to_owned()) {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "duplicate session identity".to_owned(),
            });
        }
        if document.clean_shutdown
            && matches!(
                checkpoint.snapshot.state,
                SessionState::Active | SessionState::Closing | SessionState::Crashed
            )
        {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "clean document contains writable session".to_owned(),
            });
        }
        previous_session = Some(id);
    }

    let mut terminal_ids = HashSet::new();
    let mut previous_terminal = None;
    for snapshot in &document.terminals {
        validate_terminal_snapshot(snapshot, path)?;
        if previous_terminal.is_some_and(|previous: &str| previous >= snapshot.terminal_id.as_str())
        {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "terminals must be sorted and unique".to_owned(),
            });
        }
        if !terminal_ids.insert(snapshot.terminal_id.clone()) {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "duplicate terminal identity".to_owned(),
            });
        }
        if let Some(session_id) = &snapshot.session_id
            && !session_ids.contains(session_id)
        {
            return Err(ExecutionStoreError::MissingReference {
                owner: format!("terminal {}", snapshot.terminal_id),
                target: session_id.clone(),
            });
        }
        if document.clean_shutdown
            && matches!(
                snapshot.state,
                TerminalState::Ready | TerminalState::Running
            )
        {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "clean document contains active terminal".to_owned(),
            });
        }
        if document.clean_shutdown && snapshot.process_id.is_some() {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "clean document contains a live process binding".to_owned(),
            });
        }
        if document.clean_shutdown && (snapshot.input_depth != 0 || snapshot.output_depth != 0) {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "clean document contains queued terminal frames".to_owned(),
            });
        }
        previous_terminal = Some(snapshot.terminal_id.as_str());
    }

    let mut loop_ids = HashSet::new();
    let mut previous_loop = None;
    for snapshot in &document.loops {
        if snapshot.contract_version != AGENT_LOOP_CONTRACT_VERSION {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "unsupported AgentLoop contract version".to_owned(),
            });
        }
        if previous_loop.is_some_and(|previous: &str| previous >= snapshot.spec.loop_id.as_str()) {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "loops must be sorted and unique".to_owned(),
            });
        }
        if !loop_ids.insert(snapshot.spec.loop_id.clone()) {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "duplicate AgentLoop identity".to_owned(),
            });
        }
        if !session_ids.contains(&snapshot.spec.session_id) {
            return Err(ExecutionStoreError::MissingReference {
                owner: format!("AgentLoop {}", snapshot.spec.loop_id),
                target: snapshot.spec.session_id.clone(),
            });
        }
        if !terminal_ids.contains(&snapshot.spec.terminal_id) {
            return Err(ExecutionStoreError::MissingReference {
                owner: format!("AgentLoop {}", snapshot.spec.loop_id),
                target: snapshot.spec.terminal_id.clone(),
            });
        }
        if snapshot.next_command_seq == 0
            || snapshot.accepted_commands >= snapshot.next_command_seq
            || [
                &snapshot.spec.loop_id,
                &snapshot.spec.agent_id,
                &snapshot.spec.cell_id,
                &snapshot.spec.session_id,
                &snapshot.spec.terminal_id,
            ]
            .iter()
            .any(|value| value.is_empty() || value.len() > AGENT_LOOP_MAX_ID_BYTES)
        {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "invalid AgentLoop sequence or identity".to_owned(),
            });
        }
        if document.clean_shutdown
            && !matches!(
                snapshot.state,
                AgentLoopState::Created | AgentLoopState::Stopped | AgentLoopState::Failed
            )
        {
            return Err(ExecutionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "clean document contains active AgentLoop".to_owned(),
            });
        }
        previous_loop = Some(snapshot.spec.loop_id.as_str());
    }
    Ok(())
}

fn validate_terminal_snapshot(
    snapshot: &TerminalSnapshot,
    path: &Path,
) -> Result<(), ExecutionStoreError> {
    if snapshot.terminal_id.trim().is_empty() || snapshot.terminal_id.contains('\0') {
        return Err(ExecutionStoreError::InvalidDocument {
            path: path.to_path_buf(),
            message: "terminal identity is invalid".to_owned(),
        });
    }
    if snapshot.input_capacity == 0 || snapshot.output_capacity == 0 {
        return Err(ExecutionStoreError::InvalidDocument {
            path: path.to_path_buf(),
            message: "terminal mailbox capacity is zero".to_owned(),
        });
    }
    if snapshot.state == TerminalState::Closed && snapshot.session_id.is_some() {
        return Err(ExecutionStoreError::InvalidDocument {
            path: path.to_path_buf(),
            message: "closed terminal retains a session".to_owned(),
        });
    }
    Ok(())
}

fn read_document(path: &Path) -> Result<ExecutionStoreDocument, ExecutionStoreError> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    serde_json::from_slice(&bytes).map_err(|error| ExecutionStoreError::InvalidDocument {
        path: path.to_path_buf(),
        message: error.to_string(),
    })
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), ExecutionStoreError> {
    let parent = path.parent().ok_or_else(|| {
        ExecutionStoreError::Io(io::Error::new(
            io::ErrorKind::InvalidInput,
            "execution document has no parent",
        ))
    })?;
    fs::create_dir_all(parent)?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            ExecutionStoreError::Io(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid execution filename",
            ))
        })?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    let temporary = parent.join(format!(".{file_name}.tmp-{}-{nonce}", std::process::id()));
    let mut file = OpenOptions::new()
        .create_new(true)
        .truncate(true)
        .write(true)
        .open(&temporary)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temporary, path)?;
    if let Ok(directory) = File::open(parent) {
        let _ = directory.sync_all();
    }
    Ok(())
}
