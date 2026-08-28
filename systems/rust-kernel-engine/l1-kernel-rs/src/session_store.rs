//! Durable Rust-owned session checkpoints for the clean-break kernel.
//!
//! This adapter persists the complete [`SessionBook`] under the new Rust state
//! root. It never imports Python state and does not execute AgentLoops,
//! providers, tools, or PTY processes. Unclean documents are normalized to
//! crashed sessions during load so recovery remains explicit at the session
//! boundary.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::session::{
    SESSION_CHECKPOINT_VERSION, SessionBook, SessionCheckpoint, SessionError, SessionSnapshot,
    SessionState,
};

/// Version of the durable session-store document.
pub const SESSION_STORE_VERSION: u32 = 1;
/// Relative location owned by the session adapter under a Rust state root.
pub const SESSION_STORE_RELATIVE_PATH: &str = "snapshots/sessions/checkpoint.json";

/// Versioned collection checkpoint written by [`SessionStore`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionStoreDocument {
    /// Store document schema version.
    pub store_version: u32,
    /// Monotonic generation assigned on every successful write.
    pub generation: u64,
    /// Whether all persisted sessions were captured after a clean shutdown.
    pub clean_shutdown: bool,
    /// Deterministically ordered session checkpoints.
    pub sessions: Vec<SessionCheckpoint>,
}

/// Fail-closed errors at the durable session boundary.
#[derive(Debug)]
pub enum SessionStoreError {
    /// Filesystem operation failed.
    Io(io::Error),
    /// The persisted document failed schema or invariant validation.
    InvalidDocument { path: PathBuf, message: String },
    /// A session checkpoint violated the session contract.
    Session(SessionError),
    /// A clean shutdown attempted to persist a writable session.
    WritableSession(String),
    /// The requested root is not a directory.
    RootNotDirectory(PathBuf),
}

impl std::fmt::Display for SessionStoreError {
    /// Render a store error as a human-readable message.
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "session store I/O failed: {error}"),
            Self::InvalidDocument { path, message } => {
                write!(
                    formatter,
                    "invalid session document {}: {message}",
                    path.display()
                )
            }
            Self::Session(error) => write!(formatter, "session checkpoint rejected: {error:?}"),
            Self::WritableSession(session_id) => write!(
                formatter,
                "clean shutdown cannot persist writable session {session_id}"
            ),
            Self::RootNotDirectory(path) => {
                write!(
                    formatter,
                    "session store root is not a directory: {}",
                    path.display()
                )
            }
        }
    }
}

impl std::error::Error for SessionStoreError {}

impl From<io::Error> for SessionStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<SessionError> for SessionStoreError {
    fn from(error: SessionError) -> Self {
        Self::Session(error)
    }
}

/// Filesystem adapter for the Rust-owned session checkpoint collection.
pub struct SessionStore {
    path: PathBuf,
    generation: u64,
}

impl SessionStore {
    /// Open a Rust-owned state root, treating an absent or empty file as fresh.
    ///
    /// # Errors
    ///
    /// - [`SessionStoreError::RootNotDirectory`] when `root` exists but is
    ///   not a directory;
    /// - [`SessionStoreError::Io`] when the checkpoint file cannot be read;
    /// - [`SessionStoreError::InvalidDocument`] on malformed JSON, version
    ///   mismatch, or invariant violations.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, SessionStoreError> {
        let root = root.as_ref();
        if root.exists() && !root.is_dir() {
            return Err(SessionStoreError::RootNotDirectory(root.to_path_buf()));
        }
        let path = root.join(SESSION_STORE_RELATIVE_PATH);
        if !path.exists() {
            return Ok(Self {
                path,
                generation: 0,
            });
        }
        let metadata = fs::metadata(&path)?;
        if metadata.len() == 0 {
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

    /// Return the durable checkpoint path for diagnostics and controlled tests.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Return the last successfully persisted generation.
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    /// Read the current document, returning an empty fresh collection if absent.
    ///
    /// # Errors
    ///
    /// [`SessionStoreError::Io`] on read failure; [`SessionStoreError::InvalidDocument`]
    /// on malformed JSON, version mismatch, or invariant violations.
    pub fn document(&self) -> Result<SessionStoreDocument, SessionStoreError> {
        if !self.path.exists() || fs::metadata(&self.path)?.len() == 0 {
            return Ok(empty_document());
        }
        let document = read_document(&self.path)?;
        validate_document(&document, &self.path)?;
        Ok(document)
    }

    /// Restore all sessions into a new sharded book.
    ///
    /// # Errors
    ///
    /// [`SessionStoreError::Io`] on read failure; [`SessionStoreError::InvalidDocument`]
    /// on schema/version/invariant violations; [`SessionStoreError::Session`]
    /// when an individual session checkpoint violates the session contract.
    pub fn load_book(&self, shard_count: usize) -> Result<SessionBook, SessionStoreError> {
        let document = self.document()?;
        let book = SessionBook::new(shard_count)?;
        for checkpoint in document.sessions {
            let checkpoint = if document.clean_shutdown {
                checkpoint
            } else {
                crash_checkpoint(checkpoint)
            };
            book.restore(checkpoint)?;
        }
        Ok(book)
    }

    /// Persist a deterministic snapshot of the complete session book.
    pub fn save(
        &mut self,
        book: &SessionBook,
        clean_shutdown: bool,
    ) -> Result<SessionStoreDocument, SessionStoreError> {
        let mut sessions = book
            .snapshots()
            .into_iter()
            .map(|snapshot| {
                if clean_shutdown
                    && matches!(snapshot.state, SessionState::Active | SessionState::Closing)
                {
                    return Err(SessionStoreError::WritableSession(
                        snapshot.spec.session_id.clone(),
                    ));
                }
                let snapshot = if clean_shutdown {
                    clean_snapshot(snapshot)
                } else {
                    crash_snapshot(snapshot)
                };
                Ok(SessionCheckpoint {
                    checkpoint_version: SESSION_CHECKPOINT_VERSION,
                    snapshot,
                })
            })
            .collect::<Result<Vec<_>, SessionStoreError>>()?;
        sessions.sort_by(|left, right| {
            left.snapshot
                .spec
                .session_id
                .cmp(&right.snapshot.spec.session_id)
        });
        let document = SessionStoreDocument {
            store_version: SESSION_STORE_VERSION,
            generation: self.generation.saturating_add(1),
            clean_shutdown,
            sessions,
        };
        validate_document(&document, &self.path)?;
        let bytes =
            serde_json::to_vec(&document).map_err(|error| SessionStoreError::InvalidDocument {
                path: self.path.clone(),
                message: error.to_string(),
            })?;
        atomic_write(&self.path, &bytes)?;
        self.generation = document.generation;
        Ok(document)
    }
}

/// Build the empty store document shape.
fn empty_document() -> SessionStoreDocument {
    SessionStoreDocument {
        store_version: SESSION_STORE_VERSION,
        generation: 0,
        clean_shutdown: true,
        sessions: Vec::new(),
    }
}

/// Mark a snapshot as cleanly shut down.
fn clean_snapshot(mut snapshot: SessionSnapshot) -> SessionSnapshot {
    snapshot.clean_shutdown = true;
    snapshot
}

/// Mark a snapshot as crash-recovered.
fn crash_snapshot(mut snapshot: SessionSnapshot) -> SessionSnapshot {
    if snapshot.state != SessionState::Closed {
        snapshot.state = SessionState::Crashed;
        snapshot.clean_shutdown = false;
    }
    snapshot
}

/// Mark a checkpoint as crash-recovered.
fn crash_checkpoint(checkpoint: SessionCheckpoint) -> SessionCheckpoint {
    SessionCheckpoint {
        checkpoint_version: checkpoint.checkpoint_version,
        snapshot: crash_snapshot(checkpoint.snapshot),
    }
}

/// Validate a store document fail-closed before use.
fn validate_document(
    document: &SessionStoreDocument,
    path: &Path,
) -> Result<(), SessionStoreError> {
    if document.store_version != SESSION_STORE_VERSION {
        return Err(SessionStoreError::InvalidDocument {
            path: path.to_path_buf(),
            message: format!("unsupported store version {}", document.store_version),
        });
    }
    let mut previous_id: Option<&str> = None;
    for checkpoint in &document.sessions {
        if checkpoint.checkpoint_version != SESSION_CHECKPOINT_VERSION {
            return Err(SessionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: format!(
                    "unsupported session checkpoint version {}",
                    checkpoint.checkpoint_version
                ),
            });
        }
        if let Some(previous_id) = previous_id
            && previous_id >= checkpoint.snapshot.spec.session_id.as_str()
        {
            return Err(SessionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "sessions must be sorted and unique by session_id".to_owned(),
            });
        }
        if document.clean_shutdown
            && matches!(
                checkpoint.snapshot.state,
                SessionState::Active | SessionState::Closing | SessionState::Crashed
            )
        {
            return Err(SessionStoreError::InvalidDocument {
                path: path.to_path_buf(),
                message: "clean document contains a non-terminal session".to_owned(),
            });
        }
        crate::session::Session::validate(checkpoint)?;
        previous_id = Some(checkpoint.snapshot.spec.session_id.as_str());
    }
    Ok(())
}

/// Load a store document from disk.
fn read_document(path: &Path) -> Result<SessionStoreDocument, SessionStoreError> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    serde_json::from_slice(&bytes).map_err(|error| SessionStoreError::InvalidDocument {
        path: path.to_path_buf(),
        message: error.to_string(),
    })
}

/// Write bytes atomically via a temporary file and rename.
fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), SessionStoreError> {
    let parent = path.parent().ok_or_else(|| {
        SessionStoreError::Io(io::Error::new(
            io::ErrorKind::InvalidInput,
            "session document has no parent",
        ))
    })?;
    fs::create_dir_all(parent)?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            SessionStoreError::Io(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid session filename",
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
