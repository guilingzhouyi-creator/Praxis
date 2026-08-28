//! Rust-owned fresh-root state store and durable lifecycle checkpoint adapter.
//!
//! This module is the first filesystem-bearing R4 seam. It owns only a new
//! Rust state root described by [`StateLayoutManifest`]; it never discovers,
//! imports, or migrates Python state. Every individual manifest, lifecycle,
//! and checkpoint update is written to a private temporary file, flushed, and
//! atomically renamed into place.

use std::fmt::{Display, Formatter};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::lifecycle::{LifecycleError, LifecycleRecord, LifecycleRegistry, LifecycleState};
use crate::state_layout::{
    STATE_LAYOUT_VERSION, StateAction, StateDecision, StateLayoutError, StateLayoutManifest,
    StateProbe, decide_state_action,
};

/// Filename for the Rust state ownership manifest.
pub const MANIFEST_FILE: &str = "manifest.json";
/// Filename for the durable lifecycle record.
pub const LIFECYCLE_FILE: &str = "lifecycle.json";
/// Relative path for the runtime checkpoint mirror.
pub const CHECKPOINT_FILE: &str = "runtime/checkpoint.json";
/// Serialized checkpoint schema version.
pub const CHECKPOINT_VERSION: u32 = 1;

/// A durable checkpoint that can restore the Rust lifecycle without a host
/// runtime. The generation is monotonic within one state root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StateCheckpoint {
    /// Checkpoint schema version.
    /// Checkpoint envelope version.
    pub checkpoint_version: u32,
    /// Monotonic write generation.
    /// Monotonic persistence generation.
    pub generation: u64,
    /// Lifecycle record captured at the checkpoint boundary.
    /// Embedded lifecycle record.
    pub lifecycle: LifecycleRecord,
}

/// Structured failures returned by the state-store adapter.
#[derive(Debug)]
pub enum StateStoreError {
    /// Filesystem operation failed.
    Io(io::Error),
    /// The declarative layout or host probe was invalid.
    Layout(StateLayoutError),
    /// A persisted JSON document failed schema validation.
    InvalidDocument { path: PathBuf, message: String },
    /// The root is not a directory.
    RootNotDirectory(PathBuf),
    /// The root requires migration or was rejected by the layout decision.
    StateRejected(StateDecision),
    /// A lifecycle transition was not valid from the current state.
    InvalidTransition {
        from: LifecycleState,
        to: LifecycleState,
    },
    /// The lifecycle registry rejected a restore operation.
    Lifecycle(LifecycleError),
}

impl Display for StateStoreError {
    /// Render a state-store error as a human-readable message.
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "state store I/O failed: {error}"),
            Self::Layout(error) => write!(f, "state layout rejected: {error:?}"),
            Self::InvalidDocument { path, message } => {
                write!(f, "invalid state document {}: {message}", path.display())
            }
            Self::RootNotDirectory(path) => {
                write!(f, "state root is not a directory: {}", path.display())
            }
            Self::StateRejected(decision) => write!(f, "state root rejected: {decision:?}"),
            Self::InvalidTransition { from, to } => {
                write!(
                    f,
                    "invalid lifecycle transition {} -> {}",
                    from.as_str(),
                    to.as_str()
                )
            }
            Self::Lifecycle(error) => write!(f, "lifecycle restore failed: {}", error.message),
        }
    }
}

impl std::error::Error for StateStoreError {}

impl From<io::Error> for StateStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<StateLayoutError> for StateStoreError {
    fn from(error: StateLayoutError) -> Self {
        Self::Layout(error)
    }
}

impl From<LifecycleError> for StateStoreError {
    fn from(error: LifecycleError) -> Self {
        Self::Lifecycle(error)
    }
}

/// Filesystem-backed Rust state root.
pub struct StateStore {
    root: PathBuf,
    manifest: StateLayoutManifest,
    lifecycle: Arc<LifecycleRegistry>,
    generation: u64,
    action: StateAction,
}

impl StateStore {
    /// Open a fresh Rust root or restore an existing Rust-owned root.
    ///
    /// # Errors
    ///
    /// RootNotDirectory for a non-directory root; StateRejected when the
    /// layout probe rejects resume/recover; InvalidDocument on manifest
    /// parse/version divergence.
    pub fn open(root: impl AsRef<Path>, contract_version: u32) -> Result<Self, StateStoreError> {
        let root = root.as_ref().to_path_buf();
        if root.exists() && !root.is_dir() {
            return Err(StateStoreError::RootNotDirectory(root));
        }
        let probe = probe_root(&root)?;
        let decision = decide_state_action(&probe, STATE_LAYOUT_VERSION)?;
        match decision.action {
            StateAction::Initialize => Self::initialize(root, contract_version, decision.action),
            StateAction::Resume | StateAction::Recover => {
                Self::restore(root, contract_version, decision.action)
            }
            StateAction::Migrate | StateAction::Reject => {
                Err(StateStoreError::StateRejected(decision))
            }
        }
    }

    /// Return the root path selected by the host adapter.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Return the validated manifest owned by this store.
    pub fn manifest(&self) -> &StateLayoutManifest {
        &self.manifest
    }

    /// Return the lifecycle registry restored or initialized for this root.
    pub fn lifecycle(&self) -> &LifecycleRegistry {
        &self.lifecycle
    }

    /// Clone the lifecycle handle for a runtime owner sharing this store.
    pub fn lifecycle_handle(&self) -> Arc<LifecycleRegistry> {
        Arc::clone(&self.lifecycle)
    }

    /// Return the action selected while opening the root.
    pub const fn action(&self) -> StateAction {
        self.action
    }

    /// Return the last persisted checkpoint generation.
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    /// Mark a boot attempt dirty before provider work begins.
    ///
    /// # Errors
    ///
    /// InvalidTransition unless currently halted/installing.
    pub fn begin_boot(&mut self) -> Result<(), StateStoreError> {
        let state = self.lifecycle.state();
        let transitions = match state {
            LifecycleState::Halted => vec![LifecycleState::Installing, LifecycleState::Booting],
            LifecycleState::Crashed => vec![LifecycleState::Booting],
            LifecycleState::Booting => Vec::new(),
            current => {
                return Err(StateStoreError::InvalidTransition {
                    from: current,
                    to: LifecycleState::Booting,
                });
            }
        };
        for target in transitions {
            self.transition(target)?;
        }
        let mut record = self.lifecycle.snapshot();
        record.last_shutdown_clean = false;
        record.last_boot_success = false;
        self.lifecycle.restore(record)?;
        self.persist()
    }

    /// Mark the boot as active and durable.
    ///
    /// # Errors
    ///
    /// InvalidTransition unless currently booting.
    pub fn mark_active(&mut self) -> Result<(), StateStoreError> {
        self.transition(LifecycleState::Active)?;
        self.lifecycle.record_boot_success();
        self.persist()
    }

    /// Record a clean or unclean shutdown and persist it durably.
    ///
    /// # Errors
    ///
    /// InvalidTransition unless active/draining; `clean=false` records an
    /// unclean shutdown for later recovery classification.
    pub fn shutdown(&mut self, clean: bool) -> Result<(), StateStoreError> {
        let state = self.lifecycle.state();
        if state == LifecycleState::Active {
            self.transition(LifecycleState::Draining)?;
        }
        if clean {
            if self.lifecycle.state() != LifecycleState::Draining {
                return Err(StateStoreError::InvalidTransition {
                    from: self.lifecycle.state(),
                    to: LifecycleState::Halted,
                });
            }
            self.transition(LifecycleState::Halted)?;
        } else if self.lifecycle.state() != LifecycleState::Crashed {
            self.transition(LifecycleState::Crashed)?;
        }
        self.lifecycle.record_shutdown(clean);
        self.persist()
    }

    /// Convert an unclean open into an explicit crashed state before recovery.
    ///
    /// # Errors
    ///
    /// InvalidTransition unless crashed.
    pub fn recover(&mut self) -> Result<(), StateStoreError> {
        if self.action != StateAction::Recover {
            return Ok(());
        }
        if self.lifecycle.state() != LifecycleState::Crashed {
            self.transition(LifecycleState::Crashed)?;
        }
        self.persist()
    }

    /// Persist lifecycle.json and runtime/checkpoint.json atomically per file.
    ///
    /// # Errors
    ///
    /// Io/serialization failures surfaced as StateStoreError variants;
    /// writes are atomic via temp-file rename.
    pub fn persist(&mut self) -> Result<(), StateStoreError> {
        self.generation = self.generation.saturating_add(1);
        let lifecycle = self.lifecycle.encode()?;
        let checkpoint = StateCheckpoint {
            checkpoint_version: CHECKPOINT_VERSION,
            generation: self.generation,
            lifecycle: self.lifecycle.snapshot(),
        };
        let checkpoint_bytes =
            serde_json::to_vec(&checkpoint).map_err(|error| StateStoreError::InvalidDocument {
                path: self.root.join(CHECKPOINT_FILE),
                message: error.to_string(),
            })?;
        atomic_write(&self.root.join(LIFECYCLE_FILE), &lifecycle)?;
        atomic_write(&self.root.join(CHECKPOINT_FILE), &checkpoint_bytes)?;
        Ok(())
    }

    /// Read and validate the latest runtime checkpoint.
    ///
    /// # Errors
    ///
    /// InvalidTransition when checkpointing is forbidden mid-transition.
    pub fn checkpoint(&self) -> Result<StateCheckpoint, StateStoreError> {
        read_json(&self.root.join(CHECKPOINT_FILE))
    }

    /// Transition the store lifecycle, validating fail-closed.
    fn transition(&self, target: LifecycleState) -> Result<(), StateStoreError> {
        let from = self.lifecycle.state();
        if self.lifecycle.transition(target) {
            Ok(())
        } else {
            Err(StateStoreError::InvalidTransition { from, to: target })
        }
    }

    /// Initialize the store at a root path.
    fn initialize(
        root: PathBuf,
        contract_version: u32,
        action: StateAction,
    ) -> Result<Self, StateStoreError> {
        fs::create_dir_all(&root)?;
        let manifest =
            StateLayoutManifest::fresh(root.to_string_lossy().to_string(), contract_version)?;
        for entry in &manifest.entries {
            let path = root.join(&entry.path);
            match entry.kind {
                crate::state_layout::StateEntryKind::Directory => fs::create_dir_all(path)?,
                crate::state_layout::StateEntryKind::File => {
                    if let Some(parent) = path.parent() {
                        fs::create_dir_all(parent)?;
                    }
                    OpenOptions::new()
                        .create(true)
                        .truncate(true)
                        .write(true)
                        .open(path)?;
                }
            }
        }
        atomic_write(&root.join(MANIFEST_FILE), &manifest.encode()?)?;
        let lifecycle = Arc::new(LifecycleRegistry::new());
        let mut record = lifecycle.snapshot();
        record.install_version = 1;
        record.schema_version = format!("layout-{STATE_LAYOUT_VERSION}");
        record.app_version = format!("contract-{contract_version}");
        record.last_shutdown_clean = true;
        lifecycle.restore(record)?;
        let mut store = Self {
            root,
            manifest,
            lifecycle,
            generation: 0,
            action,
        };
        store.persist()?;
        Ok(store)
    }

    /// Restore the store from a root path.
    fn restore(
        root: PathBuf,
        contract_version: u32,
        action: StateAction,
    ) -> Result<Self, StateStoreError> {
        let manifest: StateLayoutManifest = read_json(&root.join(MANIFEST_FILE))?;
        if manifest.layout_version != STATE_LAYOUT_VERSION
            || manifest.contract_version != contract_version
        {
            return Err(StateStoreError::StateRejected(StateDecision {
                action: StateAction::Reject,
                reason: crate::state_layout::StateReason::FutureLayout,
            }));
        }
        validate_entries_on_disk(&root, &manifest)?;
        let record: LifecycleRecord = read_json(&root.join(LIFECYCLE_FILE))?;
        let lifecycle = Arc::new(LifecycleRegistry::from_record(record)?);
        let checkpoint: StateCheckpoint = read_json(&root.join(CHECKPOINT_FILE))?;
        if checkpoint.checkpoint_version != CHECKPOINT_VERSION {
            return Err(StateStoreError::InvalidDocument {
                path: root.join(CHECKPOINT_FILE),
                message: format!(
                    "unsupported checkpoint version {}",
                    checkpoint.checkpoint_version
                ),
            });
        }
        if checkpoint.lifecycle != lifecycle.snapshot() {
            return Err(StateStoreError::InvalidDocument {
                path: root.join(CHECKPOINT_FILE),
                message: "lifecycle and checkpoint records diverge".to_owned(),
            });
        }
        Ok(Self {
            root,
            manifest,
            lifecycle,
            generation: checkpoint.generation,
            action,
        })
    }
}

/// Probe a root path and classify its state.
fn probe_root(root: &Path) -> Result<StateProbe, StateStoreError> {
    if !root.exists() {
        return Ok(StateProbe {
            root_exists: false,
            root_empty: false,
            manifest_version: None,
            clean_shutdown: None,
        });
    }
    let mut entries = fs::read_dir(root)?;
    let root_empty = entries.next().transpose()?.is_none();
    let manifest_path = root.join(MANIFEST_FILE);
    let manifest_version = if manifest_path.is_file() {
        let value: serde_json::Value = read_json(&manifest_path)?;
        value
            .get("layout_version")
            .and_then(serde_json::Value::as_u64)
            .map(|v| v as u32)
    } else {
        None
    };
    let lifecycle_path = root.join(LIFECYCLE_FILE);
    let clean_shutdown = if lifecycle_path.is_file() {
        let record: LifecycleRecord = read_json(&lifecycle_path)?;
        Some(record.last_shutdown_clean)
    } else {
        None
    };
    Ok(StateProbe {
        root_exists: true,
        root_empty,
        manifest_version,
        clean_shutdown,
    })
}

/// Validate on-disk entries against the layout.
fn validate_entries_on_disk(
    root: &Path,
    manifest: &StateLayoutManifest,
) -> Result<(), StateStoreError> {
    for entry in &manifest.entries {
        let path = root.join(&entry.path);
        let metadata = fs::metadata(&path).map_err(StateStoreError::Io)?;
        let valid = match entry.kind {
            crate::state_layout::StateEntryKind::Directory => metadata.is_dir(),
            crate::state_layout::StateEntryKind::File => metadata.is_file(),
        };
        if !valid {
            return Err(StateStoreError::InvalidDocument {
                path,
                message: format!(
                    "manifest entry has the wrong filesystem type: {:?}",
                    entry.kind
                ),
            });
        }
    }
    Ok(())
}

/// Read and deserialize a JSON file.
fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, StateStoreError> {
    let mut file = File::open(path).map_err(StateStoreError::Io)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).map_err(StateStoreError::Io)?;
    serde_json::from_slice(&bytes).map_err(|error| StateStoreError::InvalidDocument {
        path: path.to_path_buf(),
        message: error.to_string(),
    })
}

/// Write bytes atomically via a temporary file and rename.
fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), StateStoreError> {
    let parent = path.parent().ok_or_else(|| {
        StateStoreError::Io(io::Error::new(
            io::ErrorKind::InvalidInput,
            "state document has no parent",
        ))
    })?;
    fs::create_dir_all(parent)?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            StateStoreError::Io(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid state filename",
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
