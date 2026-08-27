//! Provider-neutral territory containment for the L1 boundary.

use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};

/// Inputs for a deterministic territory containment check.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerritoryCheck {
    /// Target path or resource.
    pub target: String,
    /// Authorized territory roots.
    #[serde(default)]
    pub bases: Vec<String>,
    /// Explicit base directory for relative paths.
    #[serde(default = "default_working_dir")]
    pub working_dir: String,
}

impl TerritoryCheck {
    /// Evaluate this check without reading the process environment or filesystem.
    pub fn evaluate(&self) -> bool {
        let working_dir = Path::new(&self.working_dir);
        is_within_at(&self.target, &self.bases, working_dir)
    }
}

/// Return whether `target` is within one of `bases` using lexical path rules.
///
/// Relative paths are interpreted relative to the current lexical directory (`.`)
/// rather than an implicitly read process working directory. Call
/// [`is_within_at`] when an adapter has an explicit working directory.
pub fn is_within(target: &str, bases: &[String]) -> bool {
    is_within_at(target, bases, Path::new("."))
}

/// Return whether `target` is within one of `bases` relative to `working_dir`.
///
/// The function performs no filesystem or symlink resolution. An empty base list
/// preserves the Python contract and matches every target; empty bases inside a
/// non-empty list are ignored. Component-aware prefix matching prevents
/// `/project/foo_secret` from matching `/project/foo`.
pub fn is_within_at(target: &str, bases: &[String], working_dir: &Path) -> bool {
    if bases.is_empty() {
        return true;
    }
    if target.is_empty() {
        return false;
    }

    let normalized_target = lexical_normalize(target, working_dir);
    bases
        .iter()
        .filter(|base| !base.is_empty())
        .map(|base| lexical_normalize(base, working_dir))
        .any(|base| normalized_target == base || normalized_target.starts_with(&base))
}

fn lexical_normalize(path: &str, working_dir: &Path) -> PathBuf {
    let raw = Path::new(path);
    let joined = if raw.is_absolute() {
        raw.to_path_buf()
    } else {
        working_dir.join(raw)
    };
    let mut normalized = PathBuf::new();
    for component in joined.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            Component::RootDir | Component::Prefix(_) | Component::Normal(_) => {
                normalized.push(component);
            }
        }
    }
    normalized
}

fn default_working_dir() -> String {
    ".".to_owned()
}
