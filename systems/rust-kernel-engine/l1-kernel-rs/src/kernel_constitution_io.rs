//! Rust-owned Constitution territory document and persistence boundary.
//!
//! This module ports the value and file responsibilities of Python's
//! `constitution_io.py` without importing Python settings or EventBus state.
//! Parsing is strict for known scalar values, rendering is deterministic, and
//! persisted replacements use a flushed sibling file plus atomic rename.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::{Display, Formatter};
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

/// Version of the Rust Constitution document contract.
pub const CONSTITUTION_IO_CONTRACT_VERSION: u32 = 1;
/// Default reputation for a blank Constitution.
pub const CONSTITUTION_DEFAULT_REPUTATION: f64 = 0.85;
/// Default token budget for a blank Constitution.
pub const CONSTITUTION_DEFAULT_TOKEN_BUDGET: u64 = 73_000;
/// Default document version for a blank Constitution.
pub const CONSTITUTION_DEFAULT_VERSION: u32 = 1;
/// Stable source label used for a blank document.
pub const CONSTITUTION_SOURCE_BLANK: &str = "blank";

/// Structured Constitution document parse/update failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConstitutionIoError {
    /// A known scalar could not be parsed.
    InvalidScalar { key: String, value: String },
    /// The reputation value is not finite or outside the inclusive [0, 1] range.
    InvalidReputation(String),
    /// The document version must be non-zero.
    InvalidVersion(String),
    /// An identity or value contains an embedded NUL.
    InvalidValue { field: String },
    /// A path was empty or contained no filename.
    InvalidPath,
    /// The document version would overflow while mutating.
    VersionExhausted,
}

impl Display for ConstitutionIoError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidScalar { key, value } => {
                write!(formatter, "invalid Constitution scalar {key}: {value}")
            }
            Self::InvalidReputation(value) => {
                write!(
                    formatter,
                    "invalid Constitution default_reputation: {value}"
                )
            }
            Self::InvalidVersion(value) => {
                write!(formatter, "invalid Constitution version: {value}")
            }
            Self::InvalidValue { field } => {
                write!(formatter, "Constitution value contains NUL: {field}")
            }
            Self::InvalidPath => formatter.write_str("Constitution path is invalid"),
            Self::VersionExhausted => formatter.write_str("Constitution version exhausted"),
        }
    }
}

impl std::error::Error for ConstitutionIoError {}

/// One changed territory set in a Constitution diff.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerritoryChange {
    /// Entries present only in the new document, sorted lexicographically.
    pub added: Vec<String>,
    /// Entries present only in the old document, sorted lexicographically.
    pub removed: Vec<String>,
}

/// Deterministic comparison of two Constitution territory documents.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerritoryDiff {
    /// Whether at least one agent's territory changed.
    pub changed: bool,
    /// Changed agent identities in sorted order.
    pub changes: BTreeMap<String, TerritoryChange>,
}

/// Territory and GateChain document represented by the Rust kernel.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TerritoryConstitution {
    /// Agent identity to territory roots.
    #[serde(default)]
    pub territories: BTreeMap<String, Vec<String>>,
    /// Gate name to human-readable rule description.
    #[serde(default)]
    pub gate_rules: BTreeMap<String, String>,
    /// Default reputation used by policy adapters.
    pub default_reputation: f64,
    /// Default token budget used by resource adapters.
    pub token_budget: u64,
    /// Monotonic document version.
    pub version: u32,
    /// Host-selected source label; not rendered into the document.
    #[serde(default)]
    pub source: String,
}

impl TerritoryConstitution {
    /// Build an empty Constitution with explicit Rust-owned defaults.
    pub fn blank(source: impl Into<String>) -> Self {
        Self {
            territories: BTreeMap::new(),
            gate_rules: BTreeMap::new(),
            default_reputation: CONSTITUTION_DEFAULT_REPUTATION,
            token_budget: CONSTITUTION_DEFAULT_TOKEN_BUDGET,
            version: CONSTITUTION_DEFAULT_VERSION,
            source: source.into(),
        }
    }

    /// Return whether no agent territory is defined.
    pub fn is_blank(&self) -> bool {
        self.territories.is_empty()
    }

    /// Parse the supported Constitution Markdown value contract.
    ///
    /// Unknown keys and comments are ignored like the Python reference, while
    /// known scalar values are rejected rather than silently defaulted.
    pub fn parse(text: &str, source: impl Into<String>) -> Result<Self, ConstitutionIoError> {
        let mut constitution = Self::blank(source);
        for raw_line in text.lines() {
            let line = raw_line.trim();
            if line.is_empty() {
                continue;
            }
            if let Some(raw_version) = line.strip_prefix("# Version:") {
                let value = raw_version.trim();
                let parsed =
                    value
                        .parse::<u32>()
                        .map_err(|_| ConstitutionIoError::InvalidScalar {
                            key: "version".to_owned(),
                            value: value.to_owned(),
                        })?;
                if parsed == 0 {
                    return Err(ConstitutionIoError::InvalidVersion(value.to_owned()));
                }
                constitution.version = parsed;
                continue;
            }
            if line.starts_with('#') {
                if line.contains('\0') {
                    return Err(ConstitutionIoError::InvalidValue {
                        field: "document".to_owned(),
                    });
                }
                continue;
            }
            let Some((raw_key, raw_value)) = line.split_once(':') else {
                continue;
            };
            let key = raw_key.trim();
            let value = raw_value.trim();
            if key.is_empty() || key.contains('\0') || value.contains('\0') {
                return Err(ConstitutionIoError::InvalidValue {
                    field: key.to_owned(),
                });
            }
            if key.starts_with("agent_") {
                constitution.territories.insert(
                    key.to_owned(),
                    value
                        .split(',')
                        .map(str::trim)
                        .filter(|territory| !territory.is_empty())
                        .map(str::to_owned)
                        .collect(),
                );
            } else if key.starts_with('G') && key.len() <= 3 {
                constitution
                    .gate_rules
                    .insert(key.to_owned(), value.to_owned());
            } else {
                match key {
                    "default_reputation" => {
                        let parsed = value.parse::<f64>().map_err(|_| {
                            ConstitutionIoError::InvalidScalar {
                                key: key.to_owned(),
                                value: value.to_owned(),
                            }
                        })?;
                        if !parsed.is_finite() || !(0.0..=1.0).contains(&parsed) {
                            return Err(ConstitutionIoError::InvalidReputation(value.to_owned()));
                        }
                        constitution.default_reputation = parsed;
                    }
                    "token_budget" => {
                        constitution.token_budget = value.parse::<u64>().map_err(|_| {
                            ConstitutionIoError::InvalidScalar {
                                key: key.to_owned(),
                                value: value.to_owned(),
                            }
                        })?;
                    }
                    "version" => {
                        let parsed = value.parse::<u32>().map_err(|_| {
                            ConstitutionIoError::InvalidScalar {
                                key: key.to_owned(),
                                value: value.to_owned(),
                            }
                        })?;
                        if parsed == 0 {
                            return Err(ConstitutionIoError::InvalidVersion(value.to_owned()));
                        }
                        constitution.version = parsed;
                    }
                    _ => {}
                }
            }
        }
        constitution.validate()?;
        Ok(constitution)
    }

    /// Render a deterministic Constitution Markdown document.
    pub fn render(&self) -> Result<String, ConstitutionIoError> {
        self.validate()?;
        let mut output = String::with_capacity(
            128 + self.territories.len().saturating_mul(48)
                + self.gate_rules.len().saturating_mul(48),
        );
        output.push_str("# NOMOS Constitution\n");
        output.push_str(&format!("# Version: {}\n\n", self.version));
        output.push_str("# Territory definitions\n");
        for (agent_id, territories) in &self.territories {
            output.push_str(agent_id);
            output.push_str(": ");
            output.push_str(&territories.join(", "));
            output.push('\n');
        }
        output.push_str("\n# GateChain rules\n");
        for (gate, description) in &self.gate_rules {
            output.push_str(gate);
            output.push_str(": ");
            output.push_str(description);
            output.push('\n');
        }
        output.push_str("\n# Defaults\n");
        output.push_str(&format!(
            "default_reputation: {}\n",
            self.default_reputation
        ));
        output.push_str(&format!("token_budget: {}\n", self.token_budget));
        Ok(output)
    }

    /// Update one agent's territory and advance the document version.
    pub fn update_territory(
        &mut self,
        agent_id: impl Into<String>,
        territories: Vec<String>,
    ) -> Result<(), ConstitutionIoError> {
        let agent_id = agent_id.into();
        validate_agent_id(&agent_id)?;
        validate_territories(&territories)?;
        self.territories.insert(agent_id, territories);
        self.bump_version()
    }

    /// Merge agent territory proposals and return accepted identities.
    pub fn merge_proposal(
        &mut self,
        proposal: &BTreeMap<String, Vec<String>>,
    ) -> Result<Vec<String>, ConstitutionIoError> {
        let mut accepted = Vec::new();
        let mut next = self.clone();
        for (agent_id, territories) in proposal {
            if !agent_id.starts_with("agent_") {
                continue;
            }
            validate_agent_id(agent_id)?;
            validate_territories(territories)?;
            next.territories
                .insert(agent_id.clone(), territories.clone());
            accepted.push(agent_id.clone());
        }
        if !accepted.is_empty() {
            next.bump_version()?;
            *self = next;
        }
        Ok(accepted)
    }

    /// Compare territory assignments with deterministic added/removed lists.
    pub fn diff(&self, other: &Self) -> TerritoryDiff {
        let identities = self
            .territories
            .keys()
            .chain(other.territories.keys())
            .cloned()
            .collect::<BTreeSet<_>>();
        let mut changes = BTreeMap::new();
        for identity in identities {
            let old = self
                .territories
                .get(&identity)
                .into_iter()
                .flatten()
                .cloned()
                .collect::<BTreeSet<_>>();
            let new = other
                .territories
                .get(&identity)
                .into_iter()
                .flatten()
                .cloned()
                .collect::<BTreeSet<_>>();
            let added = new.difference(&old).cloned().collect::<Vec<_>>();
            let removed = old.difference(&new).cloned().collect::<Vec<_>>();
            if !added.is_empty() || !removed.is_empty() {
                changes.insert(identity, TerritoryChange { added, removed });
            }
        }
        TerritoryDiff {
            changed: !changes.is_empty(),
            changes,
        }
    }

    fn validate(&self) -> Result<(), ConstitutionIoError> {
        if !self.default_reputation.is_finite() || !(0.0..=1.0).contains(&self.default_reputation) {
            return Err(ConstitutionIoError::InvalidReputation(
                self.default_reputation.to_string(),
            ));
        }
        if self.version == 0 {
            return Err(ConstitutionIoError::InvalidVersion("0".to_owned()));
        }
        for (agent_id, territories) in &self.territories {
            validate_agent_id(agent_id)?;
            validate_territories(territories)?;
        }
        for (gate, description) in &self.gate_rules {
            if gate.is_empty() || description.contains('\0') {
                return Err(ConstitutionIoError::InvalidValue {
                    field: gate.clone(),
                });
            }
        }
        Ok(())
    }

    fn bump_version(&mut self) -> Result<(), ConstitutionIoError> {
        self.version = self
            .version
            .checked_add(1)
            .ok_or(ConstitutionIoError::VersionExhausted)?;
        Ok(())
    }
}

/// Filesystem-backed Rust Constitution store.
pub struct ConstitutionStore {
    path: PathBuf,
    document: Mutex<TerritoryConstitution>,
}

impl ConstitutionStore {
    /// Open an existing Markdown document or an in-memory blank document.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ConstitutionStoreError> {
        let path = path.as_ref().to_path_buf();
        validate_path(&path)?;
        let document = match fs::read_to_string(&path) {
            Ok(text) => TerritoryConstitution::parse(text.as_str(), path.to_string_lossy())
                .map_err(ConstitutionStoreError::Document)?,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                TerritoryConstitution::blank(CONSTITUTION_SOURCE_BLANK)
            }
            Err(error) => return Err(ConstitutionStoreError::Io(error)),
        };
        Ok(Self {
            path,
            document: Mutex::new(document),
        })
    }

    /// Return the selected Constitution path.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Return a defensive document snapshot.
    pub fn document(&self) -> TerritoryConstitution {
        self.document
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    /// Replace and durably save a document atomically.
    pub fn replace_and_save(
        &self,
        document: TerritoryConstitution,
    ) -> Result<(), ConstitutionStoreError> {
        let mut current = self.document.lock().unwrap_or_else(PoisonError::into_inner);
        let rendered = document
            .render()
            .map_err(ConstitutionStoreError::Document)?;
        write_atomic(&self.path, rendered.as_bytes())?;
        *current = document;
        Ok(())
    }

    /// Update one territory and save only after the complete mutation succeeds.
    pub fn update_territory_and_save(
        &self,
        agent_id: impl Into<String>,
        territories: Vec<String>,
    ) -> Result<TerritoryConstitution, ConstitutionStoreError> {
        let mut current = self.document.lock().unwrap_or_else(PoisonError::into_inner);
        let mut next = current.clone();
        next.update_territory(agent_id, territories)
            .map_err(ConstitutionStoreError::Document)?;
        let rendered = next.render().map_err(ConstitutionStoreError::Document)?;
        write_atomic(&self.path, rendered.as_bytes())?;
        *current = next.clone();
        Ok(next)
    }

    /// Merge accepted proposals and save the resulting document atomically.
    pub fn merge_proposal_and_save(
        &self,
        proposal: &BTreeMap<String, Vec<String>>,
    ) -> Result<(Vec<String>, TerritoryConstitution), ConstitutionStoreError> {
        let mut current = self.document.lock().unwrap_or_else(PoisonError::into_inner);
        let mut next = current.clone();
        let accepted = next
            .merge_proposal(proposal)
            .map_err(ConstitutionStoreError::Document)?;
        if !accepted.is_empty() {
            let rendered = next.render().map_err(ConstitutionStoreError::Document)?;
            write_atomic(&self.path, rendered.as_bytes())?;
            *current = next.clone();
        }
        Ok((accepted, next))
    }
}

/// Filesystem failures at the Constitution store boundary.
#[derive(Debug)]
pub enum ConstitutionStoreError {
    /// Filesystem operation failed.
    Io(io::Error),
    /// The selected path is invalid.
    Path(ConstitutionIoError),
    /// Parsing, rendering, or mutation failed.
    Document(ConstitutionIoError),
}

impl Display for ConstitutionStoreError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "Constitution store I/O failed: {error}"),
            Self::Path(error) => write!(formatter, "Constitution store path rejected: {error}"),
            Self::Document(error) => write!(formatter, "Constitution document rejected: {error}"),
        }
    }
}

impl std::error::Error for ConstitutionStoreError {}

fn validate_agent_id(agent_id: &str) -> Result<(), ConstitutionIoError> {
    if agent_id.trim().is_empty() || !agent_id.starts_with("agent_") || agent_id.contains('\0') {
        return Err(ConstitutionIoError::InvalidValue {
            field: "agent_id".to_owned(),
        });
    }
    Ok(())
}

fn validate_territories(territories: &[String]) -> Result<(), ConstitutionIoError> {
    if territories.iter().any(|territory| territory.contains('\0')) {
        return Err(ConstitutionIoError::InvalidValue {
            field: "territory".to_owned(),
        });
    }
    Ok(())
}

fn validate_path(path: &Path) -> Result<(), ConstitutionStoreError> {
    if path.as_os_str().is_empty() || path.file_name().is_none() {
        return Err(ConstitutionStoreError::Path(
            ConstitutionIoError::InvalidPath,
        ));
    }
    Ok(())
}

fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), ConstitutionStoreError> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty());
    let parent = parent.unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(ConstitutionStoreError::Io)?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    let file_name =
        path.file_name()
            .and_then(|name| name.to_str())
            .ok_or(ConstitutionStoreError::Path(
                ConstitutionIoError::InvalidPath,
            ))?;
    let temporary = parent.join(format!(".{file_name}.tmp-{}-{stamp}", std::process::id()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .truncate(true)
            .write(true)
            .open(&temporary)
            .map_err(ConstitutionStoreError::Io)?;
        file.write_all(bytes).map_err(ConstitutionStoreError::Io)?;
        file.flush().map_err(ConstitutionStoreError::Io)?;
        file.sync_all().map_err(ConstitutionStoreError::Io)?;
        drop(file);
        fs::rename(&temporary, path).map_err(ConstitutionStoreError::Io)?;
        if let Ok(directory) = fs::File::open(parent) {
            let _ = directory.sync_all();
        }
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}
