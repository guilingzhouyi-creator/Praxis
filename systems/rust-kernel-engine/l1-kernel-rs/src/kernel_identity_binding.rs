//! Rust-native identity-binding metadata registry for the L1 kernel.
//!
//! This candidate owns only bounded binding metadata and the write gate. Prompt
//! fragments, identity definitions, persistence, events, and API routing stay
//! in adapters because they are policy or transport concerns rather than
//! kernel state ownership.

use std::collections::BTreeMap;
use std::fmt::{Display, Formatter};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex as StdMutex, PoisonError, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

/// Default maximum number of role bindings owned by one Cell.
pub const DEFAULT_MAX_BINDINGS_PER_CELL: usize = 32;
/// Default maximum character budget declared for an adapter-owned fragment.
pub const DEFAULT_MAX_FRAGMENT_CHARS: usize = 1_200;
/// Default maximum number of domain tags retained in one binding.
pub const DEFAULT_MAX_DOMAIN_TAGS: usize = 16;
/// Default minimum caller clearance for a binding write.
pub const DEFAULT_MIN_WRITE_CLEARANCE: u8 = 3;
/// Version of the Rust-owned identity-binding checkpoint document.
pub const IDENTITY_BINDING_DOCUMENT_VERSION: u32 = 1;

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

/// Versioned Rust-owned checkpoint for identity-binding metadata.
///
/// Prompt fragments and identity definitions are deliberately absent. Those
/// values remain L3 policy data; this checkpoint contains only the bounded
/// metadata required to restore identity correlation and routing.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BindingCheckpoint {
    /// Checkpoint schema version.
    pub document_version: u32,
    /// Monotonic registry revision captured by this checkpoint.
    pub revision: u64,
    /// Deterministically ordered binding records.
    pub records: Vec<BindingRecord>,
}

impl BindingCheckpoint {
    fn validate(&self, policy: &BindingPolicy) -> Result<BindingState, &'static str> {
        if self.document_version != IDENTITY_BINDING_DOCUMENT_VERSION {
            return Err("unsupported identity-binding document version");
        }
        let mut records = BTreeMap::new();
        for record in &self.records {
            if record.cell_id.trim().is_empty()
                || record.role.trim().is_empty()
                || record.cell_id.contains('\0')
                || record.role.contains('\0')
            {
                return Err("persisted binding cell and role are required");
            }
            if record.identity_id.trim().is_empty() || record.identity_id.contains('\0') {
                return Err("persisted binding identity id is required");
            }
            if record.revision == 0 || record.revision > self.revision {
                return Err("persisted binding revision is invalid");
            }
            if record.max_chars == 0 || record.max_chars > policy.max_fragment_chars {
                return Err("persisted binding fragment budget is invalid");
            }
            if record.domain_tags.len() > policy.max_domain_tags
                || record
                    .domain_tags
                    .iter()
                    .any(|tag| tag.trim().is_empty() || tag.contains('\0'))
            {
                return Err("persisted binding domain tags are invalid");
            }
            let mut normalized_tags = record.domain_tags.clone();
            normalized_tags.sort_unstable();
            normalized_tags.dedup();
            if normalized_tags != record.domain_tags {
                return Err("persisted binding domain tags must be sorted and unique");
            }
            let key = (record.cell_id.clone(), record.role.clone());
            if records.insert(key, record.clone()).is_some() {
                return Err("duplicate persisted identity binding");
            }
        }
        for cell_id in records.keys().map(|(cell_id, _)| cell_id) {
            if records
                .keys()
                .filter(|(existing_cell, _)| existing_cell == cell_id)
                .count()
                > policy.max_bindings_per_cell
            {
                return Err("persisted binding cap reached for cell");
            }
        }
        Ok(BindingState {
            revision: self.revision,
            records,
        })
    }
}

/// Fail-closed errors for the Rust-owned identity-binding store.
#[derive(Debug)]
pub enum IdentityBindingStoreError {
    /// Filesystem operation failed.
    Io(io::Error),
    /// The requested checkpoint path is empty, malformed, or a directory.
    InvalidPath(PathBuf),
    /// The checkpoint bytes could not be decoded or validated.
    InvalidDocument { path: PathBuf, message: String },
    /// The in-memory registry rejected a mutation or checkpoint.
    Registry(String),
    /// A failed durable mutation could not restore the prior memory state.
    RollbackFailed { path: PathBuf, message: String },
}

impl Display for IdentityBindingStoreError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "identity-binding store I/O failed: {error}"),
            Self::InvalidPath(path) => write!(
                formatter,
                "identity-binding checkpoint path is invalid: {}",
                path.display()
            ),
            Self::InvalidDocument { path, message } => write!(
                formatter,
                "invalid identity-binding checkpoint {}: {message}",
                path.display()
            ),
            Self::Registry(message) => write!(
                formatter,
                "identity-binding registry rejected operation: {message}"
            ),
            Self::RollbackFailed { path, message } => write!(
                formatter,
                "identity-binding rollback failed for {}: {message}",
                path.display()
            ),
        }
    }
}

impl std::error::Error for IdentityBindingStoreError {}

impl From<io::Error> for IdentityBindingStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
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

    /// Capture a versioned checkpoint containing only durable metadata.
    pub fn checkpoint(&self) -> BindingCheckpoint {
        let state = self.state.read().unwrap_or_else(PoisonError::into_inner);
        BindingCheckpoint {
            document_version: IDENTITY_BINDING_DOCUMENT_VERSION,
            revision: state.revision,
            records: state.records.values().cloned().collect(),
        }
    }

    /// Restore a previously validated metadata checkpoint.
    ///
    /// The checkpoint replaces the registry only after all records have been
    /// validated, so malformed or foreign state cannot partially mutate the
    /// in-memory binding table.
    pub fn restore_checkpoint(&self, checkpoint: BindingCheckpoint) -> Result<(), &'static str> {
        let next = checkpoint.validate(&self.policy)?;
        let mut state = self.state.write().unwrap_or_else(PoisonError::into_inner);
        *state = next;
        Ok(())
    }

    fn validate_spec<'a>(
        spec: &'a BindingSpec,
        policy: &BindingPolicy,
    ) -> Result<(&'a str, &'a str), &'static str> {
        if spec.cell_id.trim().is_empty()
            || spec.role.trim().is_empty()
            || spec.cell_id.contains('\0')
            || spec.role.contains('\0')
        {
            return Err("binding cell and role are required");
        }
        if spec.domain_tags.len() > policy.max_domain_tags {
            return Err("binding domain tag cap exceeded");
        }
        if spec
            .domain_tags
            .iter()
            .any(|tag| tag.trim().is_empty() || tag.contains('\0'))
        {
            return Err("binding domain tags must not be empty");
        }
        Ok((spec.cell_id.as_str(), spec.role.as_str()))
    }

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

    fn normalize_max_chars(value: usize, policy: &BindingPolicy) -> usize {
        if value == 0 {
            policy.max_fragment_chars
        } else {
            value.min(policy.max_fragment_chars)
        }
    }
}

impl Default for IdentityBindingRegistry {
    fn default() -> Self {
        Self::new(BindingPolicy::default()).expect("default identity binding policy is valid")
    }
}

/// Atomic filesystem-backed identity-binding metadata registry.
///
/// The store owns only the Rust checkpoint file. Writes use a unique sibling
/// temporary file, flush it, and atomically rename it into place. Mutations
/// publish the in-memory state only after the durable replacement succeeds;
/// failed replacements restore the previous checkpoint or return an explicit
/// rollback failure. Cross-process policy and prompt resolution remain host
/// responsibilities.
pub struct IdentityBindingStore {
    path: PathBuf,
    registry: IdentityBindingRegistry,
    mutation_lock: StdMutex<()>,
}

impl IdentityBindingStore {
    /// Open a Rust-owned identity-binding checkpoint or an empty registry.
    pub fn open(
        path: impl AsRef<Path>,
        policy: BindingPolicy,
    ) -> Result<Self, IdentityBindingStoreError> {
        let path = path.as_ref().to_path_buf();
        validate_store_path(&path)?;
        let registry = IdentityBindingRegistry::new(policy)
            .map_err(|message| IdentityBindingStoreError::Registry(message.to_owned()))?;
        if path.exists() {
            if path.is_dir() {
                return Err(IdentityBindingStoreError::InvalidPath(path));
            }
            let checkpoint = read_checkpoint(&path)?;
            registry.restore_checkpoint(checkpoint).map_err(|message| {
                IdentityBindingStoreError::InvalidDocument {
                    path: path.clone(),
                    message: message.to_owned(),
                }
            })?;
        }
        Ok(Self {
            path,
            registry,
            mutation_lock: StdMutex::new(()),
        })
    }

    /// Return the checkpoint path owned by this store.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Return the immutable registry policy.
    pub fn policy(&self) -> &BindingPolicy {
        self.registry.policy()
    }

    /// Return a cloned record from the in-memory registry.
    pub fn get(&self, cell_id: &str, role: &str) -> Option<BindingRecord> {
        self.registry.get(cell_id, role)
    }

    /// Return deterministic metadata records from the in-memory registry.
    pub fn snapshot(&self) -> Vec<BindingRecord> {
        self.registry.snapshot()
    }

    /// Return the current in-memory mutation revision.
    pub fn revision(&self) -> u64 {
        self.registry.revision()
    }

    /// Return the current versioned metadata checkpoint.
    pub fn checkpoint(&self) -> BindingCheckpoint {
        self.registry.checkpoint()
    }

    /// Persist the current checkpoint without mutating registry state.
    pub fn persist(&self) -> Result<(), IdentityBindingStoreError> {
        let _guard = self
            .mutation_lock
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        self.persist_checkpoint_locked(&self.registry.checkpoint())
    }

    /// Reload and validate the checkpoint currently present on disk.
    pub fn reload(&self) -> Result<(), IdentityBindingStoreError> {
        let _guard = self
            .mutation_lock
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if !self.path.exists() {
            return self
                .registry
                .restore_checkpoint(BindingCheckpoint {
                    document_version: IDENTITY_BINDING_DOCUMENT_VERSION,
                    revision: 0,
                    records: Vec::new(),
                })
                .map_err(|message| IdentityBindingStoreError::Registry(message.to_owned()));
        }
        let checkpoint = read_checkpoint(&self.path)?;
        self.registry
            .restore_checkpoint(checkpoint)
            .map_err(|message| IdentityBindingStoreError::InvalidDocument {
                path: self.path.clone(),
                message: message.to_owned(),
            })
    }

    /// Durably upsert one metadata binding.
    pub fn upsert(
        &self,
        spec: BindingSpec,
        principal: &WritePrincipal,
    ) -> Result<BindingRecord, IdentityBindingStoreError> {
        let _guard = self
            .mutation_lock
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let previous = self.registry.checkpoint();
        let record = self
            .registry
            .upsert(spec, principal)
            .map_err(|message| IdentityBindingStoreError::Registry(message.to_owned()))?;
        if let Err(error) = self.persist_checkpoint_locked(&self.registry.checkpoint()) {
            return Err(self.rollback_after_failure(previous, error));
        }
        Ok(record)
    }

    /// Durably remove one metadata binding.
    pub fn unbind(
        &self,
        cell_id: &str,
        role: &str,
        principal: &WritePrincipal,
    ) -> Result<bool, IdentityBindingStoreError> {
        let _guard = self
            .mutation_lock
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let previous = self.registry.checkpoint();
        let removed = self
            .registry
            .unbind(cell_id, role, principal)
            .map_err(|message| IdentityBindingStoreError::Registry(message.to_owned()))?;
        if let Err(error) = self.persist_checkpoint_locked(&self.registry.checkpoint()) {
            return Err(self.rollback_after_failure(previous, error));
        }
        Ok(removed)
    }

    /// Durably remove all metadata bindings belonging to one Cell.
    pub fn clear_cell(
        &self,
        cell_id: &str,
        principal: &WritePrincipal,
    ) -> Result<usize, IdentityBindingStoreError> {
        let _guard = self
            .mutation_lock
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let previous = self.registry.checkpoint();
        let removed = self
            .registry
            .clear_cell(cell_id, principal)
            .map_err(|message| IdentityBindingStoreError::Registry(message.to_owned()))?;
        if let Err(error) = self.persist_checkpoint_locked(&self.registry.checkpoint()) {
            return Err(self.rollback_after_failure(previous, error));
        }
        Ok(removed)
    }

    fn persist_checkpoint_locked(
        &self,
        checkpoint: &BindingCheckpoint,
    ) -> Result<(), IdentityBindingStoreError> {
        checkpoint
            .validate(self.registry.policy())
            .map_err(|message| IdentityBindingStoreError::Registry(message.to_owned()))?;
        let bytes = serde_json::to_vec(checkpoint).map_err(|error| {
            IdentityBindingStoreError::InvalidDocument {
                path: self.path.clone(),
                message: error.to_string(),
            }
        })?;
        atomic_write(&self.path, &bytes)
    }

    fn rollback_after_failure(
        &self,
        previous: BindingCheckpoint,
        error: IdentityBindingStoreError,
    ) -> IdentityBindingStoreError {
        if let Err(rollback_error) = self.registry.restore_checkpoint(previous) {
            return IdentityBindingStoreError::RollbackFailed {
                path: self.path.clone(),
                message: format!("{error}; restore failed: {rollback_error}"),
            };
        }
        error
    }
}

fn validate_store_path(path: &Path) -> Result<(), IdentityBindingStoreError> {
    if path.as_os_str().is_empty() || path.to_string_lossy().contains('\0') {
        return Err(IdentityBindingStoreError::InvalidPath(path.to_path_buf()));
    }
    Ok(())
}

fn read_checkpoint(path: &Path) -> Result<BindingCheckpoint, IdentityBindingStoreError> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    serde_json::from_slice(&bytes).map_err(|error| IdentityBindingStoreError::InvalidDocument {
        path: path.to_path_buf(),
        message: error.to_string(),
    })
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), IdentityBindingStoreError> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| IdentityBindingStoreError::InvalidPath(path.to_path_buf()))?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    let temporary = parent.join(format!(".{file_name}.tmp-{}-{nonce}", std::process::id()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .truncate(true)
            .write(true)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, path)?;
        let directory = File::open(parent)?;
        let _ = directory.sync_all();
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result.map_err(IdentityBindingStoreError::Io)
}
