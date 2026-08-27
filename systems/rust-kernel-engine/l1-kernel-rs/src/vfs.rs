//! Rust candidate for the bounded, provider-neutral Praxis virtual file system.

use std::collections::{BTreeMap, VecDeque};
use std::fmt;
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard, PoisonError, RwLock, RwLockReadGuard, RwLockWriteGuard};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

/// Default minimum ring accepted by a mount.
pub const VFS_DEFAULT_MIN_RING: u8 = 1;
/// Default maximum number of mount points retained by the candidate table.
pub const VFS_DEFAULT_MAX_MOUNTS: usize = 64;
/// Default number of cached provider reads and virtual files retained.
pub const VFS_DEFAULT_CACHE_CAPACITY: usize = 500;
/// Default lifetime of a provider-read cache entry.
pub const VFS_DEFAULT_CACHE_TTL: Duration = Duration::from_secs(60);

/// Backing class for one virtual file-system mount.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MountType {
    /// A project directory supplied by an external provider.
    Project,
    /// A sandbox directory supplied by an external provider.
    Sandbox,
    /// A temporary directory supplied by an external provider.
    Temp,
    /// An in-memory mount owned by this candidate.
    Virtual,
    /// A kernel/system provider such as `/proc` or `/sys`.
    System,
}

impl MountType {
    /// Return the stable Python-compatible enum spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Project => "PROJECT",
            Self::Sandbox => "SANDBOX",
            Self::Temp => "TEMP",
            Self::Virtual => "VIRTUAL",
            Self::System => "SYSTEM",
        }
    }
}

/// Mount metadata crossing the adapter boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MountPoint {
    /// Absolute virtual prefix, for example `/project`.
    /// Stable mount name used as the lookup key.
    pub name: String,
    /// Provider/backing class for the mount.
    /// Virtual vs provider-backed classification.
    pub mount_type: MountType,
    /// Provider-owned real root; never opened by this candidate.
    #[serde(default)]
    /// Host-side directory backing this mount (virtual mounts leave it empty).
    pub real_path: String,
    /// Minimum agent ring permitted to access the mount.
    /// Minimum agent ring admitted to this mount.
    pub min_ring: u8,
    /// Whether writes and unlink operations are denied.
    /// Whether writes and unlinks are rejected on this mount.
    pub read_only: bool,
    /// Human-readable metadata retained for `/proc/mounts` adapters.
    #[serde(default)]
    /// Human-facing description surfaced to adapters.
    pub description: String,
}

impl MountPoint {
    /// Construct a mount with the same defaults as the Python VFS.
    pub fn new(name: impl Into<String>, mount_type: MountType) -> Self {
        Self {
            name: name.into(),
            mount_type,
            real_path: String::new(),
            min_ring: VFS_DEFAULT_MIN_RING,
            read_only: false,
            description: String::new(),
        }
    }

    /// Set the provider root used only when an external adapter resolves it.
    pub fn with_real_path(mut self, real_path: impl Into<String>) -> Self {
        self.real_path = real_path.into();
        self
    }

    /// Set the minimum ring required by this mount.
    pub const fn with_min_ring(mut self, min_ring: u8) -> Self {
        self.min_ring = min_ring;
        self
    }

    /// Mark this mount read-only.
    pub const fn with_read_only(mut self, read_only: bool) -> Self {
        self.read_only = read_only;
        self
    }

    /// Attach a description used by diagnostics.
    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }
}

/// Stable error categories returned by the VFS candidate.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum VfsErrorCode {
    /// Invalid or unsafe virtual path.
    InvalidPath,
    /// Mount prefix already exists.
    DuplicateMount,
    /// Mount table or bounded store has no capacity.
    Capacity,
    /// No mount or virtual file matched the requested path.
    NotFound,
    /// Agent ring is below the mount requirement.
    PermissionDenied,
    /// Write/unlink was attempted on a read-only mount.
    ReadOnly,
    /// A real/system provider must perform this operation outside Rust.
    ProviderRequired,
}

impl VfsErrorCode {
    /// Return the stable wire error code used by Python adapters.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InvalidPath => "EINVAL",
            Self::DuplicateMount => "EEXIST",
            Self::Capacity => "ENOSPC",
            Self::NotFound => "ENOENT",
            Self::PermissionDenied => "EACCES",
            Self::ReadOnly => "EROFS",
            Self::ProviderRequired => "EADAPTER",
        }
    }
}

/// Structured VFS error that can cross a language adapter unchanged.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VfsError {
    /// Stable machine-readable category.
    /// Stable errno-style classification.
    pub code: VfsErrorCode,
    /// Bounded, human-readable context.
    /// Human-readable detail; safe to cross adapters.
    pub message: String,
}

impl VfsError {
    fn new(code: VfsErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    /// Return the stable error code string.
    pub const fn error_code(&self) -> &'static str {
        self.code.as_str()
    }
}

impl fmt::Display for VfsError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.error_code(), self.message)
    }
}

impl std::error::Error for VfsError {}

/// Structured result of resolving a virtual path against one mount.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MountResolution {
    /// Matched virtual mount prefix.
    /// Name of the mount that resolved the path.
    pub mount: String,
    /// Path relative to the matched mount.
    /// Path relative to the mount root.
    pub rel: String,
    /// Provider root copied from the mount metadata.
    /// Absolute virtual root that matched.
    pub root: String,
    /// Provider path formed by joining root and rel; never opened here.
    pub real_path: String,
    /// Minimum ring required by the mount.
    pub min_ring: u8,
    /// Read-only policy copied from the mount.
    pub read_only: bool,
    /// Mount backing class.
    pub mount_type: MountType,
}

/// Provider-read result with explicit cache provenance.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReadResult {
    /// UTF-8 content supplied by a virtual store or external provider.
    /// File body served from the bounded virtual store or cache.
    pub content: String,
    /// Matched mount prefix.
    pub mount: String,
    /// Whether the content came from the bounded cache.
    /// Whether `content` came from the TTL cache rather than the store.
    pub cached: bool,
}

/// Result of a virtual write or an adapter-owned write acknowledgement.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WriteResult {
    /// Matched mount prefix.
    pub mount: String,
    /// Virtual path acknowledged by the operation.
    /// Canonical virtual path written or removed.
    pub path: String,
}

/// Result of listing a virtual directory or provider directory.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ListResult {
    /// Returned entries in deterministic lexical order.
    /// Child names under the listed virtual directory.
    pub entries: Vec<String>,
    /// Matched mount prefix.
    pub mount: String,
}

/// Bounded VFS capacities and provider-read cache policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VfsConfig {
    /// Maximum number of mount points.
    /// Hard bound on concurrent mount points.
    pub max_mounts: usize,
    /// Maximum number of provider-read cache entries.
    /// Bounded read-cache capacity in entries.
    pub cache_capacity: usize,
    /// Maximum number of virtual files.
    /// Bounded virtual-file store capacity in entries.
    pub virtual_capacity: usize,
    /// TTL for provider-read cache entries.
    /// Time-to-live applied to cached provider reads.
    pub cache_ttl: Duration,
}

impl Default for VfsConfig {
    fn default() -> Self {
        Self {
            max_mounts: VFS_DEFAULT_MAX_MOUNTS,
            cache_capacity: VFS_DEFAULT_CACHE_CAPACITY,
            virtual_capacity: VFS_DEFAULT_CACHE_CAPACITY,
            cache_ttl: VFS_DEFAULT_CACHE_TTL,
        }
    }
}

/// Bounded mount table with longest-prefix resolution.
#[derive(Debug)]
pub struct MountTable {
    capacity: usize,
    mounts: BTreeMap<String, MountPoint>,
    order: Vec<String>,
    prefixes: Vec<String>,
}

impl MountTable {
    /// Create an empty table with an explicit mount bound.
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity,
            mounts: BTreeMap::new(),
            order: Vec::new(),
            prefixes: Vec::new(),
        }
    }

    /// Insert one mount, rebuilding the longest-prefix lookup index.
    ///
    /// # Errors
    ///
    /// - [`VfsErrorCode::DuplicateMount`] when `point.name` already exists;
    /// - [`VfsErrorCode::Capacity`] when the table reached its bound.
    pub fn mount(&mut self, point: MountPoint) -> Result<(), VfsError> {
        validate_path(&point.name, true)?;
        if self.mounts.contains_key(&point.name) {
            return Err(VfsError::new(
                VfsErrorCode::DuplicateMount,
                format!("mount point '{}' already exists", point.name),
            ));
        }
        if self.mounts.len() >= self.capacity {
            return Err(VfsError::new(
                VfsErrorCode::Capacity,
                format!("mount table capacity {} reached", self.capacity),
            ));
        }
        self.order.push(point.name.clone());
        self.mounts.insert(point.name.clone(), point);
        self.rebuild_prefixes();
        Ok(())
    }

    /// Remove one mount and return its metadata.
    ///
    /// # Errors
    ///
    /// [`VfsErrorCode::NotFound`] when no mount carries `name`.
    pub fn unmount(&mut self, name: &str) -> Result<MountPoint, VfsError> {
        let point = self.mounts.remove(name).ok_or_else(|| {
            VfsError::new(
                VfsErrorCode::NotFound,
                format!("mount point '{name}' not found"),
            )
        })?;
        self.order.retain(|entry| entry != name);
        self.rebuild_prefixes();
        Ok(point)
    }

    /// Resolve a path using the most specific matching mount prefix.
    ///
    /// # Errors
    ///
    /// [`VfsErrorCode::NotFound`] when no mount prefix matches `path`.
    pub fn resolve(&self, path: &str) -> Result<MountResolution, VfsError> {
        validate_path(path, false)?;
        for prefix in &self.prefixes {
            if !path_matches(prefix, path) {
                continue;
            }
            let point = self
                .mounts
                .get(prefix)
                .expect("prefix index must only contain mounted points");
            let rel = relative_path(prefix, path);
            let real_path = if point.real_path.is_empty() {
                String::new()
            } else {
                PathBuf::from(&point.real_path)
                    .join(&rel)
                    .to_string_lossy()
                    .into_owned()
            };
            return Ok(MountResolution {
                mount: point.name.clone(),
                rel,
                root: point.real_path.clone(),
                real_path,
                min_ring: point.min_ring,
                read_only: point.read_only,
                mount_type: point.mount_type,
            });
        }
        Err(VfsError::new(
            VfsErrorCode::NotFound,
            format!("no mount for '{path}'"),
        ))
    }

    /// Return mounts in registration order for diagnostics.
    pub fn mounts(&self) -> Vec<MountPoint> {
        self.order
            .iter()
            .filter_map(|name| self.mounts.get(name).cloned())
            .collect()
    }

    /// Return the current number of mounts.
    pub fn len(&self) -> usize {
        self.mounts.len()
    }

    /// Return whether the table has no mounts.
    pub fn is_empty(&self) -> bool {
        self.mounts.is_empty()
    }

    fn rebuild_prefixes(&mut self) {
        self.prefixes = self.mounts.keys().cloned().collect();
        self.prefixes
            .sort_by(|left, right| right.len().cmp(&left.len()).then_with(|| left.cmp(right)));
    }
}

#[derive(Debug)]
struct CacheEntry {
    content: String,
    expires_at: Instant,
}

#[derive(Debug)]
struct BoundedTextStore {
    capacity: usize,
    values: BTreeMap<String, String>,
    order: VecDeque<String>,
}

impl BoundedTextStore {
    fn new(capacity: usize) -> Self {
        Self {
            capacity,
            values: BTreeMap::new(),
            order: VecDeque::new(),
        }
    }

    fn insert(&mut self, path: String, content: String) {
        if self.capacity == 0 {
            return;
        }
        if self.values.contains_key(&path) {
            self.order.retain(|entry| entry != &path);
        }
        self.values.insert(path.clone(), content);
        self.order.push_back(path);
        self.prune();
    }

    fn get(&self, path: &str) -> Option<String> {
        self.values.get(path).cloned()
    }

    fn remove(&mut self, path: &str) {
        self.values.remove(path);
        self.order.retain(|entry| entry != path);
    }

    fn prune(&mut self) {
        while self.values.len() > self.capacity {
            if let Some(path) = self.order.pop_front() {
                self.values.remove(&path);
            } else {
                break;
            }
        }
    }

    fn len(&self) -> usize {
        self.values.len()
    }
}

#[derive(Debug)]
struct CacheStore {
    capacity: usize,
    ttl: Duration,
    values: BTreeMap<String, CacheEntry>,
    order: VecDeque<String>,
}

impl CacheStore {
    fn new(capacity: usize, ttl: Duration) -> Self {
        Self {
            capacity,
            ttl,
            values: BTreeMap::new(),
            order: VecDeque::new(),
        }
    }

    fn get(&mut self, path: &str, now: Instant) -> Option<String> {
        let entry = self.values.get(path)?;
        if now >= entry.expires_at {
            self.remove(path);
            return None;
        }
        Some(entry.content.clone())
    }

    fn insert(&mut self, path: String, content: String, now: Instant) {
        if self.capacity == 0 || self.ttl.is_zero() {
            return;
        }
        if self.values.contains_key(&path) {
            self.order.retain(|entry| entry != &path);
        }
        self.values.insert(
            path.clone(),
            CacheEntry {
                content,
                expires_at: now + self.ttl,
            },
        );
        self.order.push_back(path);
        self.prune(now);
    }

    fn remove(&mut self, path: &str) {
        self.values.remove(path);
        self.order.retain(|entry| entry != path);
    }

    fn remove_prefix(&mut self, prefix: &str) {
        let paths = self
            .values
            .keys()
            .filter(|path| path_matches(prefix, path))
            .cloned()
            .collect::<Vec<_>>();
        for path in paths {
            self.remove(&path);
        }
    }

    fn prune(&mut self, now: Instant) {
        let expired = self
            .values
            .iter()
            .filter(|(_, entry)| now >= entry.expires_at)
            .map(|(path, _)| path.clone())
            .collect::<Vec<_>>();
        for path in expired {
            self.remove(&path);
        }
        while self.values.len() > self.capacity {
            if let Some(path) = self.order.pop_front() {
                self.values.remove(&path);
            } else {
                break;
            }
        }
    }

    fn len(&self) -> usize {
        self.values.len()
    }
}

/// Thread-safe VFS mechanism with bounded mount, cache, and virtual stores.
pub struct Vfs {
    mounts: RwLock<MountTable>,
    cache: Mutex<CacheStore>,
    virtual_files: Mutex<BoundedTextStore>,
}

impl Vfs {
    /// Create a candidate using the default bounds and cache TTL.
    pub fn new() -> Self {
        Self::with_config(VfsConfig::default())
    }

    /// Create a candidate from explicit bounded deployment values.
    pub fn with_config(config: VfsConfig) -> Self {
        Self {
            mounts: RwLock::new(MountTable::new(config.max_mounts)),
            cache: Mutex::new(CacheStore::new(config.cache_capacity, config.cache_ttl)),
            virtual_files: Mutex::new(BoundedTextStore::new(config.virtual_capacity)),
        }
    }

    /// Register a mount point.
    ///
    /// # Errors
    ///
    /// - [`VfsErrorCode::DuplicateMount`] when `point.name` already exists;
    /// - [`VfsErrorCode::Capacity`] when the table reached its bound.
    pub fn mount(&self, point: MountPoint) -> Result<MountPoint, VfsError> {
        let mut table = self.write_mounts();
        table.mount(point.clone())?;
        Ok(point)
    }

    /// Remove a mount and invalidate all cached content below it.
    ///
    /// # Errors
    ///
    /// [`VfsErrorCode::NotFound`] when no mount carries `name`.
    pub fn unmount(&self, name: &str) -> Result<MountPoint, VfsError> {
        let point = self.write_mounts().unmount(name)?;
        self.lock_cache().remove_prefix(name);
        Ok(point)
    }

    /// Return a structured mount resolution without accessing the provider.
    ///
    /// # Errors
    ///
    /// [`VfsErrorCode::NotFound`] when no mount prefix matches `path`.
    pub fn resolve_mount(&self, path: &str) -> Result<MountResolution, VfsError> {
        self.read_mounts().resolve(path)
    }

    /// Return all mounts in registration order.
    pub fn mounts(&self) -> Vec<MountPoint> {
        self.read_mounts().mounts()
    }

    /// Read a virtual file; real/system reads remain provider-owned.
    ///
    /// # Errors
    ///
    /// - [`VfsErrorCode::PermissionDenied`] when `agent_ring` is below the
    ///   mount requirement;
    /// - [`VfsErrorCode::ProviderRequired`] when the resolution is
    ///   provider-backed (real reads stay host-owned);
    /// - [`VfsErrorCode::NotFound`] when the virtual file does not exist.
    pub fn read(&self, path: &str, agent_ring: u8) -> Result<ReadResult, VfsError> {
        let resolution = self.authorize(path, agent_ring, false)?;
        if resolution.mount_type != MountType::Virtual {
            return Err(provider_required("read", &resolution));
        }
        let content = self
            .lock_virtual()
            .get(path)
            .ok_or_else(|| not_found(path))?;
        Ok(ReadResult {
            content,
            mount: resolution.mount,
            cached: false,
        })
    }

    /// Write a virtual file; real/system writes remain provider-owned.
    pub fn write(
        &self,
        path: &str,
        content: impl Into<String>,
        agent_ring: u8,
    ) -> Result<WriteResult, VfsError> {
        let resolution = self.authorize(path, agent_ring, true)?;
        if resolution.mount_type != MountType::Virtual {
            return Err(provider_required("write", &resolution));
        }
        self.lock_cache().remove(path);
        self.lock_virtual().insert(path.to_owned(), content.into());
        Ok(WriteResult {
            mount: resolution.mount,
            path: path.to_owned(),
        })
    }

    /// Delete a virtual file; real/system unlink remains provider-owned.
    ///
    /// # Errors
    ///
    /// NotFound when absent; ReadOnly on read-only mounts; ProviderRequired off virtual storage.
    pub fn unlink(&self, path: &str, agent_ring: u8) -> Result<WriteResult, VfsError> {
        let resolution = self.authorize(path, agent_ring, true)?;
        if resolution.mount_type != MountType::Virtual {
            return Err(provider_required("unlink", &resolution));
        }
        {
            let mut files = self.lock_virtual();
            if files.get(path).is_none() {
                return Err(not_found(path));
            }
            files.remove(path);
        }
        self.lock_cache().remove(path);
        Ok(WriteResult {
            mount: resolution.mount,
            path: path.to_owned(),
        })
    }

    /// List virtual descendants; external providers supply real listings.
    ///
    /// # Errors
    ///
    /// NotFound when the directory does not exist; ProviderRequired off virtual storage.
    pub fn list_dir(&self, path: &str, agent_ring: u8) -> Result<ListResult, VfsError> {
        let resolution = self.authorize(path, agent_ring, false)?;
        if resolution.mount_type != MountType::Virtual {
            return Err(provider_required("list_dir", &resolution));
        }
        let files = self.lock_virtual();
        let mut entries = files
            .values
            .keys()
            .filter(|entry| path_matches(path, entry))
            .cloned()
            .collect::<Vec<_>>();
        entries.sort();
        Ok(ListResult {
            entries,
            mount: resolution.mount,
        })
    }

    /// Accept content from an external provider and apply the VFS cache policy.
    pub fn read_from_provider(
        &self,
        path: &str,
        content: impl Into<String>,
        agent_ring: u8,
    ) -> Result<ReadResult, VfsError> {
        let resolution = self.authorize(path, agent_ring, false)?;
        if resolution.mount_type == MountType::Virtual {
            return Err(VfsError::new(
                VfsErrorCode::ProviderRequired,
                "virtual mounts must use the in-memory store",
            ));
        }
        let mut cache = self.lock_cache();
        if let Some(cached) = cache.get(path, Instant::now()) {
            return Ok(ReadResult {
                content: cached,
                mount: resolution.mount,
                cached: true,
            });
        }
        let content = content.into();
        cache.insert(path.to_owned(), content.clone(), Instant::now());
        Ok(ReadResult {
            content,
            mount: resolution.mount,
            cached: false,
        })
    }

    /// Accept a directory listing from an external provider.
    pub fn list_from_provider(
        &self,
        path: &str,
        entries: impl IntoIterator<Item = String>,
        agent_ring: u8,
    ) -> Result<ListResult, VfsError> {
        let resolution = self.authorize(path, agent_ring, false)?;
        if resolution.mount_type == MountType::Virtual {
            return Err(VfsError::new(
                VfsErrorCode::ProviderRequired,
                "virtual mounts must use the in-memory store",
            ));
        }
        let mut entries = entries.into_iter().collect::<Vec<_>>();
        entries.sort();
        Ok(ListResult {
            entries,
            mount: resolution.mount,
        })
    }

    /// Invalidate one cache path and all descendants.
    ///
    /// # Errors
    ///
    /// Infallible best-effort invalidation; misses are silently ignored.
    pub fn invalidate_cache(&self, path: &str) -> Result<(), VfsError> {
        validate_path(path, false)?;
        self.lock_cache().remove_prefix(path);
        Ok(())
    }

    /// Return bounded-store sizes for health and benchmark reporting.
    pub fn stats(&self) -> VfsStats {
        VfsStats {
            mounts: self.read_mounts().len(),
            cached_reads: self.lock_cache().len(),
            virtual_files: self.lock_virtual().len(),
        }
    }

    fn authorize(
        &self,
        path: &str,
        agent_ring: u8,
        write: bool,
    ) -> Result<MountResolution, VfsError> {
        let resolution = self.resolve_mount(path)?;
        if agent_ring < resolution.min_ring {
            return Err(VfsError::new(
                VfsErrorCode::PermissionDenied,
                format!("ring too low for mount '{}'", resolution.mount),
            ));
        }
        if write && resolution.read_only {
            return Err(VfsError::new(
                VfsErrorCode::ReadOnly,
                format!("mount '{}' is read-only", resolution.mount),
            ));
        }
        Ok(resolution)
    }

    fn read_mounts(&self) -> RwLockReadGuard<'_, MountTable> {
        self.mounts.read().unwrap_or_else(PoisonError::into_inner)
    }

    fn write_mounts(&self) -> RwLockWriteGuard<'_, MountTable> {
        self.mounts.write().unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_cache(&self) -> MutexGuard<'_, CacheStore> {
        self.cache.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_virtual(&self) -> MutexGuard<'_, BoundedTextStore> {
        self.virtual_files
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for Vfs {
    fn default() -> Self {
        Self::new()
    }
}

/// Bounded VFS counts used by health and performance adapters.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct VfsStats {
    /// Number of registered mounts.
    pub mounts: usize,
    /// Number of live provider-read cache entries.
    pub cached_reads: usize,
    /// Number of live virtual files.
    pub virtual_files: usize,
}

fn validate_path(path: &str, mount_name: bool) -> Result<(), VfsError> {
    if path.is_empty() || !path.starts_with('/') || path.contains('\0') {
        return Err(VfsError::new(
            VfsErrorCode::InvalidPath,
            format!("path must be absolute: '{path}'"),
        ));
    }
    if mount_name && path.len() > 1 && path.ends_with('/') {
        return Err(VfsError::new(
            VfsErrorCode::InvalidPath,
            format!("mount name must not end with '/': '{path}'"),
        ));
    }
    if path.split('/').any(|component| component == "..") {
        return Err(VfsError::new(
            VfsErrorCode::InvalidPath,
            format!("parent traversal is forbidden: '{path}'"),
        ));
    }
    Ok(())
}

fn path_matches(prefix: &str, path: &str) -> bool {
    prefix == "/"
        || path == prefix
        || path
            .strip_prefix(prefix)
            .is_some_and(|suffix| suffix.starts_with('/'))
}

fn relative_path(prefix: &str, path: &str) -> String {
    if prefix == "/" {
        return path.trim_start_matches('/').to_owned();
    }
    path.strip_prefix(prefix)
        .unwrap_or_default()
        .trim_start_matches('/')
        .to_owned()
}

fn not_found(path: &str) -> VfsError {
    VfsError::new(VfsErrorCode::NotFound, format!("file not found: '{path}'"))
}

fn provider_required(operation: &str, resolution: &MountResolution) -> VfsError {
    VfsError::new(
        VfsErrorCode::ProviderRequired,
        format!(
            "{operation} for '{}' requires '{}' provider",
            resolution.mount,
            resolution.mount_type.as_str()
        ),
    )
}
