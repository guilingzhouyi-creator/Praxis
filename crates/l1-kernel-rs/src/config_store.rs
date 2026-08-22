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
    pub path: String,
}

/// Versioned manifest for a fresh Rust configuration root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConfigLayoutManifest {
    /// Layout schema version.
    pub layout_version: u32,
    /// Kernel contract version associated with the root.
    pub contract_version: u32,
    /// Host-selected configuration root.
    pub config_root: String,
    /// Deterministically ordered owned files.
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
    pub document_version: u32,
    /// Monotonic document revision.
    pub revision: u64,
    /// Flat, typed JSON values selected by the Rust host.
    pub values: BTreeMap<String, Value>,
}

impl Default for ConfigDocument {
    fn default() -> Self {
        Self {
            document_version: CONFIG_DOCUMENT_VERSION,
            revision: 0,
            values: BTreeMap::new(),
        }
    }
}

impl ConfigDocument {
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
}

impl Display for ConfigError {
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
    pub fn set_config(&mut self, key: impl Into<String>, value: Value) -> Result<(), ConfigError> {
        let key = key.into();
        validate_key(&key)?;
        self.config.values.insert(key, value);
        self.config.revision = self.config.revision.saturating_add(1);
        self.persist_document(CONFIG_FILE, &self.config.clone())
    }

    /// Set one runtime setting and persist the document.
    pub fn set_setting(&mut self, key: impl Into<String>, value: Value) -> Result<(), ConfigError> {
        let key = key.into();
        validate_key(&key)?;
        self.settings.values.insert(key, value);
        self.settings.revision = self.settings.revision.saturating_add(1);
        self.persist_document(SETTINGS_FILE, &self.settings.clone())
    }

    /// Persist both documents as separate atomic updates.
    pub fn persist(&self) -> Result<(), ConfigError> {
        self.persist_document(CONFIG_FILE, &self.config)?;
        self.persist_document(SETTINGS_FILE, &self.settings)
    }

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
}

fn is_safe_relative_path(path: &str) -> bool {
    !path.trim().is_empty()
        && !path.starts_with('/')
        && !path.contains('\\')
        && !path
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
}

fn is_empty_directory(path: &Path) -> Result<bool, ConfigError> {
    Ok(path.is_dir() && path.read_dir()?.next().is_none())
}

fn validate_key(key: &str) -> Result<(), ConfigError> {
    if key.trim().is_empty() || key.contains('\0') {
        return Err(ConfigError::InvalidKey(key.to_owned()));
    }
    Ok(())
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, ConfigError> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    serde_json::from_slice(&bytes).map_err(|error| ConfigError::InvalidDocument {
        path: path.to_path_buf(),
        message: error.to_string(),
    })
}

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
    fs::rename(&temp, path)?;
    if let Ok(directory) = File::open(parent) {
        let _ = directory.sync_all();
    }
    Ok(())
}
