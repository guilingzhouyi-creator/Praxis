//! Rust-owned configuration root for the clean-break kernel.
//!
//! The store uses a small JSON-only layout owned by the new Rust build. It
//! deliberately does not parse `praxis.yaml`, import Python settings, execute
//! migrations, or expose provider policy. Hosts supply the root and values;
//! each document update is flushed and atomically renamed.

use std::collections::BTreeMap;
use std::fmt::{Display, Formatter};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Version of the Rust-owned configuration layout.
pub const CONFIG_LAYOUT_VERSION: u32 = 1;
/// Version of persisted configuration documents.
pub const CONFIG_DOCUMENT_VERSION: u32 = 1;
/// Manifest filename under a configuration root.
pub const CONFIG_MANIFEST_FILE: &str = "manifest.json";
/// Kernel configuration document filename.
pub const CONFIG_FILE: &str = "config.json";
/// Runtime settings document filename.
pub const SETTINGS_FILE: &str = "settings.json";

/// A file owned by the Rust configuration root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConfigEntry {
    /// Canonical path relative to the configuration root.
    /// Config-relative path key.
    pub path: String,
}

/// Versioned manifest for a fresh Rust configuration root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConfigLayoutManifest {
    /// Layout schema version.
    /// Layout schema version of the store.
    pub layout_version: u32,
    /// Kernel contract version associated with the root.
    /// Contract version this root was created under.
    pub contract_version: u32,
    /// Host-selected configuration root.
    /// Canonical config root path.
    pub config_root: String,
    /// Deterministically ordered owned files.
    /// Declared config entries (sorted by path).
    pub entries: Vec<ConfigEntry>,
}

impl ConfigLayoutManifest {
    /// Build the minimal Rust-owned configuration layout.
    pub fn fresh(
        config_root: impl Into<String>,
        contract_version: u32,
    ) -> Result<Self, ConfigError> {
        Self::new(
            config_root,
            contract_version,
            vec![
                ConfigEntry {
                    path: CONFIG_FILE.to_owned(),
                },
                ConfigEntry {
                    path: SETTINGS_FILE.to_owned(),
                },
            ],
        )
    }

    /// Validate and normalize an explicit manifest.
    pub fn new(
        config_root: impl Into<String>,
        contract_version: u32,
        mut entries: Vec<ConfigEntry>,
    ) -> Result<Self, ConfigError> {
        let config_root = config_root.into();
        if config_root.trim().is_empty() || config_root.contains('\0') {
            return Err(ConfigError::InvalidRoot);
        }
        if entries.is_empty() {
            return Err(ConfigError::EmptyLayout);
        }
        entries.sort_by(|left, right| left.path.cmp(&right.path));
        for pair in entries.windows(2) {
            if pair[0].path == pair[1].path {
                return Err(ConfigError::DuplicateEntry(pair[0].path.clone()));
            }
        }
        for entry in &entries {
            if !is_safe_relative_path(&entry.path) {
                return Err(ConfigError::InvalidPath(entry.path.clone()));
            }
        }
        Ok(Self {
            layout_version: CONFIG_LAYOUT_VERSION,
            contract_version,
            config_root,
            entries,
        })
    }

    /// Validate the layout version fail-closed.
    fn validate_version(&self) -> Result<(), ConfigError> {
        if self.layout_version != CONFIG_LAYOUT_VERSION {
            return Err(ConfigError::UnsupportedLayout(self.layout_version));
        }
        Ok(())
    }
}

/// One versioned JSON document in the Rust-owned configuration root.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ConfigDocument {
    /// Document schema version.
    /// Values-document schema version.
    pub document_version: u32,
    /// Monotonic document revision.
    /// Monotonic mutation counter.
    pub revision: u64,
    /// Flat, typed JSON values selected by the Rust host.
    /// Key/value map with deterministic order.
    pub values: BTreeMap<String, Value>,
}

impl Default for ConfigDocument {
    /// Create a default config document.
    fn default() -> Self {
        Self {
            document_version: CONFIG_DOCUMENT_VERSION,
            revision: 0,
            values: BTreeMap::new(),
        }
    }
}

impl ConfigDocument {
    /// Validate the document version and fields fail-closed.
    fn validate(&self) -> Result<(), ConfigError> {
        if self.document_version != CONFIG_DOCUMENT_VERSION {
            return Err(ConfigError::UnsupportedDocument(self.document_version));
        }
        for key in self.values.keys() {
            validate_key(key)?;
        }
        Ok(())
    }
}

/// Structured configuration store failure.
#[derive(Debug)]
pub enum ConfigError {
    /// Filesystem operation failed.
    Io(io::Error),
    /// Root path is invalid.
    InvalidRoot,
    /// A relative entry is unsafe or unsupported.
    InvalidPath(String),
    /// The layout contains no owned files.
    EmptyLayout,
    /// An entry occurs more than once.
    DuplicateEntry(String),
    /// A future or incompatible layout version was found.
    UnsupportedLayout(u32),
    /// A future or incompatible document version was found.
    UnsupportedDocument(u32),
    /// A configuration key is empty or contains an embedded NUL.
    InvalidKey(String),
    /// A persisted document failed to decode or validate.
    InvalidDocument { path: PathBuf, message: String },
    /// A non-directory path was supplied as the root.
    RootNotDirectory(PathBuf),
    /// A non-Rust or migration-required root was found.
    ForeignRoot(PathBuf),
    /// A paired document update could not restore the first replacement.
    RollbackFailed { path: PathBuf, message: String },
}

impl Display for ConfigError {
    /// Render a config error as a human-readable message.
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "config store I/O failed: {error}"),
            Self::InvalidRoot => write!(formatter, "config root is invalid"),
            Self::InvalidPath(path) => write!(formatter, "config path is invalid: {path}"),
            Self::EmptyLayout => write!(formatter, "config layout is empty"),
            Self::DuplicateEntry(path) => write!(formatter, "duplicate config entry: {path}"),
            Self::UnsupportedLayout(version) => {
                write!(formatter, "unsupported config layout: {version}")
            }
            Self::UnsupportedDocument(version) => {
                write!(formatter, "unsupported config document: {version}")
            }
            Self::InvalidKey(key) => write!(formatter, "config key is invalid: {key}"),
            Self::InvalidDocument { path, message } => {
                write!(
                    formatter,
                    "invalid config document {}: {message}",
                    path.display()
                )
            }
            Self::RootNotDirectory(path) => write!(
                formatter,
                "config root is not a directory: {}",
                path.display()
            ),
            Self::ForeignRoot(path) => write!(
                formatter,
                "config root is not Rust-owned: {}",
                path.display()
            ),
            Self::RollbackFailed { path, message } => write!(
                formatter,
                "config pair rollback failed for {}: {message}",
                path.display()
            ),
        }
    }
}

impl std::error::Error for ConfigError {}

impl From<io::Error> for ConfigError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

/// Filesystem-backed Rust configuration store.
pub struct ConfigStore {
    root: PathBuf,
    manifest: ConfigLayoutManifest,
    config: ConfigDocument,
    settings: ConfigDocument,
}

impl ConfigStore {
    /// Open a fresh Rust root or resume a matching root.
    ///
    /// # Errors
    ///
    /// RootNotDirectory for a non-directory; ForeignRoot when the layout
    /// manifest is missing, unreadable, or written by a different contract;
    /// UnsupportedLayout/InvalidPath/DuplicateEntry during manifest load.
    pub fn open(root: impl AsRef<Path>, contract_version: u32) -> Result<Self, ConfigError> {
        let root = root.as_ref().to_path_buf();
        if root.exists() && !root.is_dir() {
            return Err(ConfigError::RootNotDirectory(root));
        }
        if !root.exists() || is_empty_directory(&root)? {
            return Self::initialize(root, contract_version);
        }
        let manifest_path = root.join(CONFIG_MANIFEST_FILE);
        if !manifest_path.is_file() {
            return Err(ConfigError::ForeignRoot(root));
        }
        let manifest: ConfigLayoutManifest = read_json(&manifest_path)?;
        manifest.validate_version()?;
        if manifest.contract_version != contract_version
            || manifest.config_root != root.to_string_lossy()
        {
            return Err(ConfigError::ForeignRoot(root));
        }
        let expected =
            ConfigLayoutManifest::fresh(root.to_string_lossy().to_string(), contract_version)?;
        if manifest.entries != expected.entries {
            return Err(ConfigError::ForeignRoot(root));
        }
        let config: ConfigDocument = read_json(&root.join(CONFIG_FILE))?;
        let settings: ConfigDocument = read_json(&root.join(SETTINGS_FILE))?;
        config.validate()?;
        settings.validate()?;
        Ok(Self {
            root,
            manifest,
            config,
            settings,
        })
    }

    /// Return the Rust-owned configuration root.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Return the validated layout manifest.
    pub const fn manifest(&self) -> &ConfigLayoutManifest {
        &self.manifest
    }

    /// Return the kernel configuration document.
    pub const fn config(&self) -> &ConfigDocument {
        &self.config
    }

    /// Return the runtime settings document.
    pub const fn settings(&self) -> &ConfigDocument {
        &self.settings
    }

    /// Set one kernel configuration value and persist the document.
    ///
    /// # Errors
    ///
    /// InvalidKey when the key escapes the config/ namespace.
    pub fn set_config(&mut self, key: impl Into<String>, value: Value) -> Result<(), ConfigError> {
        let key = key.into();
        validate_key(&key)?;
        let mut next = self.config.clone();
        next.values.insert(key, value);
        next.revision = next.revision.saturating_add(1);
        self.persist_document(CONFIG_FILE, &next)?;
        self.config = next;
        Ok(())
    }

    /// Set one runtime setting and persist the document.
    ///
    /// # Errors
    ///
    /// InvalidKey when the key escapes the settings/ namespace.
    pub fn set_setting(&mut self, key: impl Into<String>, value: Value) -> Result<(), ConfigError> {
        let key = key.into();
        validate_key(&key)?;
        let mut next = self.settings.clone();
        next.values.insert(key, value);
        next.revision = next.revision.saturating_add(1);
        self.persist_document(SETTINGS_FILE, &next)?;
        self.settings = next;
        Ok(())
    }

    /// Atomically replace one config value and one setting value as a pair.
    ///
    /// The two documents are staged before either in-memory field changes.
    /// If the second filesystem replacement fails, the first replacement is
    /// restored from its prior bytes and both in-memory documents remain
    /// unchanged. This is the only paired mutation surface; independent
    /// `set_config` and `set_setting` calls intentionally remain independent.
    ///
    /// # Errors
    ///
    /// InvalidKey when either key is empty or contains an embedded NUL;
    /// RollbackFailed when the second write fails and the first write cannot
    /// be restored.
    pub fn set_config_and_setting(
        &mut self,
        config_key: impl Into<String>,
        config_value: Value,
        setting_key: impl Into<String>,
        setting_value: Value,
    ) -> Result<(), ConfigError> {
        let config_key = config_key.into();
        let setting_key = setting_key.into();
        validate_key(&config_key)?;
        validate_key(&setting_key)?;

        let mut next_config = self.config.clone();
        next_config.values.insert(config_key, config_value);
        next_config.revision = next_config.revision.saturating_add(1);
        let mut next_settings = self.settings.clone();
        next_settings.values.insert(setting_key, setting_value);
        next_settings.revision = next_settings.revision.saturating_add(1);

        self.persist_documents(&next_config, &next_settings)?;
        self.config = next_config;
        self.settings = next_settings;
        Ok(())
    }

    /// Persist both documents as separate atomic updates.
    ///
    /// # Errors
    ///
    /// Io/serialization failures surfaced as ConfigError. If the second
    /// replacement fails, the first replacement is restored before returning.
    pub fn persist(&self) -> Result<(), ConfigError> {
        self.persist_documents(&self.config, &self.settings)
    }

    /// Initialize the config store at a root path.
    fn initialize(root: PathBuf, contract_version: u32) -> Result<Self, ConfigError> {
        fs::create_dir_all(&root)?;
        let manifest =
            ConfigLayoutManifest::fresh(root.to_string_lossy().to_string(), contract_version)?;
        let store = Self {
            root,
            manifest,
            config: ConfigDocument::default(),
            settings: ConfigDocument::default(),
        };
        let manifest_bytes =
            serde_json::to_vec(&store.manifest).map_err(|error| ConfigError::InvalidDocument {
                path: store.root.join(CONFIG_MANIFEST_FILE),
                message: error.to_string(),
            })?;
        atomic_write(&store.root.join(CONFIG_MANIFEST_FILE), &manifest_bytes)?;
        store.persist()?;
        Ok(store)
    }

    /// Persist a document atomically to disk.
    fn persist_document(
        &self,
        filename: &str,
        document: &ConfigDocument,
    ) -> Result<(), ConfigError> {
        document.validate()?;
        let bytes = serde_json::to_vec(document).map_err(|error| ConfigError::InvalidDocument {
            path: self.root.join(filename),
            message: error.to_string(),
        })?;
        atomic_write(&self.root.join(filename), &bytes)
    }

    fn persist_documents(
        &self,
        config: &ConfigDocument,
        settings: &ConfigDocument,
    ) -> Result<(), ConfigError> {
        config.validate()?;
        settings.validate()?;
        let config_bytes =
            serde_json::to_vec(config).map_err(|error| ConfigError::InvalidDocument {
                path: self.root.join(CONFIG_FILE),
                message: error.to_string(),
            })?;
        let settings_bytes =
            serde_json::to_vec(settings).map_err(|error| ConfigError::InvalidDocument {
                path: self.root.join(SETTINGS_FILE),
                message: error.to_string(),
            })?;
        let config_path = self.root.join(CONFIG_FILE);
        let previous_config = read_optional(&config_path)?;
        atomic_write(&config_path, &config_bytes)?;
        if let Err(error) = atomic_write(&self.root.join(SETTINGS_FILE), &settings_bytes) {
            if let Err(rollback_error) = restore_optional(&config_path, previous_config.as_deref())
            {
                return Err(ConfigError::RollbackFailed {
                    path: config_path,
                    message: format!("{error}; restore failed: {rollback_error}"),
                });
            }
            return Err(error);
        }
        Ok(())
    }
}

/// Accept safe relative paths without traversal components.
fn is_safe_relative_path(path: &str) -> bool {
    !path.trim().is_empty()
        && !path.starts_with('/')
        && !path.contains('\\')
        && !path
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
}

/// Return whether a directory exists and is empty.
fn is_empty_directory(path: &Path) -> Result<bool, ConfigError> {
    Ok(path.is_dir() && path.read_dir()?.next().is_none())
}

/// Reject empty or NUL-containing config keys fail-closed.
fn validate_key(key: &str) -> Result<(), ConfigError> {
    if key.trim().is_empty() || key.contains('\0') {
        return Err(ConfigError::InvalidKey(key.to_owned()));
    }
    Ok(())
}

/// Read and deserialize a JSON file.
fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, ConfigError> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    serde_json::from_slice(&bytes).map_err(|error| ConfigError::InvalidDocument {
        path: path.to_path_buf(),
        message: error.to_string(),
    })
}

fn read_optional(path: &Path) -> Result<Option<Vec<u8>>, ConfigError> {
    match fs::read(path) {
        Ok(bytes) => Ok(Some(bytes)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(ConfigError::Io(error)),
    }
}

fn restore_optional(path: &Path, previous: Option<&[u8]>) -> Result<(), io::Error> {
    match previous {
        Some(bytes) => restore_file(path, bytes),
        None => match fs::remove_file(path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(error),
        },
    }
}

fn restore_file(path: &Path, bytes: &[u8]) -> Result<(), io::Error> {
    let parent = path.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "config document has no parent")
    })?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "invalid config filename"))?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    let temporary = parent.join(format!(
        ".{file_name}.rollback-{}-{nonce}",
        std::process::id()
    ));
    let mut file = OpenOptions::new()
        .create_new(true)
        .truncate(true)
        .write(true)
        .open(&temporary)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    if let Err(error) = fs::rename(&temporary, path) {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }
    if let Ok(directory) = File::open(parent) {
        let _ = directory.sync_all();
    }
    Ok(())
}

/// Write bytes atomically via a temporary file and rename.
fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), ConfigError> {
    let parent = path.parent().ok_or(ConfigError::InvalidRoot)?;
    fs::create_dir_all(parent)?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    let temp = parent.join(format!(
        ".{}.tmp-{}",
        path.file_name().unwrap_or_default().to_string_lossy(),
        stamp
    ));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    if let Err(error) = fs::rename(&temp, path) {
        let _ = fs::remove_file(&temp);
        return Err(ConfigError::Io(error));
    }
    if let Ok(directory) = File::open(parent) {
        let _ = directory.sync_all();
    }
    Ok(())
}
