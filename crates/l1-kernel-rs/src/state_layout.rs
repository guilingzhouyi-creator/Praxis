//! Rust-owned state layout and fresh-state recovery decisions.
//!
//! This candidate defines only the versioned layout manifest and the
//! observation-to-decision boundary. It does not create directories, read
//! files, import Python3 state, or perform migration side effects.

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

/// Version of the clean-break Rust state layout manifest.
pub const STATE_LAYOUT_VERSION: u32 = 1;

/// One path that the Rust kernel owns under its state root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StateEntry {
    /// Canonical slash-separated path relative to the state root.
    pub path: String,
    /// Whether the path is a directory or a file.
    pub kind: StateEntryKind,
}

impl StateEntry {
    /// Build a directory entry.
    pub fn directory(path: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            kind: StateEntryKind::Directory,
        }
    }

    /// Build a file entry.
    pub fn file(path: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            kind: StateEntryKind::File,
        }
    }
}

/// Entry kind in a state layout manifest.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StateEntryKind {
    /// A directory that must exist before files below it are created.
    Directory,
    /// A regular state file owned by the Rust build.
    File,
}

/// Versioned manifest for a fresh Rust-owned state root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StateLayoutManifest {
    /// Layout schema version.
    pub layout_version: u32,
    /// Kernel contract version associated with this layout.
    pub contract_version: u32,
    /// Host-selected root; the adapter owns path discovery.
    pub state_root: String,
    /// Deterministically ordered relative entries.
    pub entries: Vec<StateEntry>,
}

/// Errors raised while validating a layout manifest or probe.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StateLayoutError {
    /// The state root is empty or contains an embedded NUL.
    InvalidRoot,
    /// A relative entry path is malformed or escapes the state root.
    InvalidPath { path: String },
    /// A path occurs more than once in the manifest.
    DuplicatePath { path: String },
    /// A file or directory parent is not declared as a directory.
    MissingParent { path: String, parent: String },
    /// A manifest cannot be empty because it would not protect state ownership.
    EmptyLayout,
    /// An observation is internally contradictory.
    InvalidProbe,
}

impl StateLayoutManifest {
    /// Create and validate a manifest from explicit entries.
    pub fn new(
        state_root: impl Into<String>,
        contract_version: u32,
        mut entries: Vec<StateEntry>,
    ) -> Result<Self, StateLayoutError> {
        let state_root = state_root.into();
        validate_root(&state_root)?;
        if entries.is_empty() {
            return Err(StateLayoutError::EmptyLayout);
        }

        entries.sort_by(|left, right| {
            left.path
                .cmp(&right.path)
                .then_with(|| entry_kind_rank(left.kind).cmp(&entry_kind_rank(right.kind)))
        });
        let mut seen = BTreeSet::new();
        let directories = entries
            .iter()
            .filter(|entry| entry.kind == StateEntryKind::Directory)
            .map(|entry| entry.path.as_str())
            .collect::<BTreeSet<_>>();
        for entry in &entries {
            validate_relative_path(&entry.path)?;
            if !seen.insert(entry.path.clone()) {
                return Err(StateLayoutError::DuplicatePath {
                    path: entry.path.clone(),
                });
            }
            let mut parent = String::new();
            let components = entry.path.split('/').collect::<Vec<_>>();
            for component in &components[..components.len().saturating_sub(1)] {
                if !parent.is_empty() {
                    parent.push('/');
                }
                parent.push_str(component);
                if !directories.contains(parent.as_str()) {
                    return Err(StateLayoutError::MissingParent {
                        path: entry.path.clone(),
                        parent,
                    });
                }
            }
        }

        Ok(Self {
            layout_version: STATE_LAYOUT_VERSION,
            contract_version,
            state_root,
            entries,
        })
    }

    /// Build the initial clean-break layout used by the future Rust kernel.
    pub fn fresh(
        state_root: impl Into<String>,
        contract_version: u32,
    ) -> Result<Self, StateLayoutError> {
        Self::new(
            state_root,
            contract_version,
            vec![
                StateEntry::directory("audit"),
                StateEntry::directory("journal"),
                StateEntry::directory("runtime"),
                StateEntry::directory("snapshots"),
                StateEntry::directory("tmp"),
                StateEntry::file("audit/events.jsonl"),
                StateEntry::file("journal/events.jsonl"),
                StateEntry::file("lifecycle.json"),
                StateEntry::file("manifest.json"),
                StateEntry::file("runtime/checkpoint.json"),
            ],
        )
    }

    /// Return the serialized manifest after re-validating its invariants.
    pub fn encode(&self) -> Result<Vec<u8>, StateLayoutError> {
        Self::new(
            self.state_root.clone(),
            self.contract_version,
            self.entries.clone(),
        )
        .and_then(|validated| {
            serde_json::to_vec(&validated).map_err(|_| StateLayoutError::InvalidProbe)
        })
    }

    /// Decode and validate a manifest supplied by a host adapter.
    pub fn decode(bytes: &[u8]) -> Result<Self, StateLayoutError> {
        let manifest: Self =
            serde_json::from_slice(bytes).map_err(|_| StateLayoutError::InvalidProbe)?;
        if manifest.layout_version != STATE_LAYOUT_VERSION {
            return Err(StateLayoutError::InvalidProbe);
        }
        Self::new(
            manifest.state_root,
            manifest.contract_version,
            manifest.entries,
        )
    }
}

/// Host-observed facts used to select a side-effect-free state action.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StateProbe {
    /// Whether the state root exists.
    pub root_exists: bool,
    /// Whether an existing root contains no entries.
    pub root_empty: bool,
    /// Version read from the Rust manifest, if present.
    pub manifest_version: Option<u32>,
    /// Clean-shutdown flag read from the Rust lifecycle record, if present.
    pub clean_shutdown: Option<bool>,
}

/// Side-effect-free action selected from a state probe.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StateAction {
    /// Create the manifest and required entries in a new or empty root.
    Initialize,
    /// Continue from a version-matched clean state.
    Resume,
    /// Open a version-matched state after an unclean shutdown.
    Recover,
    /// Run a versioned migration before opening the state.
    Migrate,
    /// Refuse to mutate an ambiguous or incompatible root.
    Reject,
}

/// Stable reason attached to a state action.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StateReason {
    /// No root exists yet.
    MissingRoot,
    /// The host supplied an empty root.
    EmptyRoot,
    /// The root is version-matched and clean.
    CleanState,
    /// The root is version-matched but was not shut down cleanly.
    UncleanShutdown,
    /// The root is older than the current layout.
    OlderLayout,
    /// The root advertises a layout newer than this build.
    FutureLayout,
    /// A non-empty root has no Rust manifest.
    MissingManifest,
    /// A version-matched root does not expose a clean-shutdown result.
    MissingCleanShutdown,
}

/// Decision returned by [`decide_state_action`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct StateDecision {
    /// Selected action.
    pub action: StateAction,
    /// Stable explanation for audit/adapter reporting.
    pub reason: StateReason,
}

/// Select initialization, resume, recovery, migration, or rejection.
pub fn decide_state_action(
    probe: &StateProbe,
    current_layout_version: u32,
) -> Result<StateDecision, StateLayoutError> {
    validate_probe(probe)?;
    if !probe.root_exists {
        return Ok(StateDecision {
            action: StateAction::Initialize,
            reason: StateReason::MissingRoot,
        });
    }
    if probe.root_empty {
        return Ok(StateDecision {
            action: StateAction::Initialize,
            reason: StateReason::EmptyRoot,
        });
    }
    let Some(version) = probe.manifest_version else {
        return Ok(StateDecision {
            action: StateAction::Reject,
            reason: StateReason::MissingManifest,
        });
    };
    if version > current_layout_version {
        return Ok(StateDecision {
            action: StateAction::Reject,
            reason: StateReason::FutureLayout,
        });
    }
    if version < current_layout_version {
        return Ok(StateDecision {
            action: StateAction::Migrate,
            reason: StateReason::OlderLayout,
        });
    }
    match probe.clean_shutdown {
        Some(true) => Ok(StateDecision {
            action: StateAction::Resume,
            reason: StateReason::CleanState,
        }),
        Some(false) => Ok(StateDecision {
            action: StateAction::Recover,
            reason: StateReason::UncleanShutdown,
        }),
        None => Ok(StateDecision {
            action: StateAction::Reject,
            reason: StateReason::MissingCleanShutdown,
        }),
    }
}

fn validate_root(root: &str) -> Result<(), StateLayoutError> {
    if root.trim().is_empty() || root.contains('\0') {
        return Err(StateLayoutError::InvalidRoot);
    }
    Ok(())
}

fn validate_relative_path(path: &str) -> Result<(), StateLayoutError> {
    if path.is_empty()
        || path.starts_with('/')
        || path.starts_with('\\')
        || path.contains('\\')
        || path.contains('\0')
        || path
            .split('/')
            .any(|component| component.is_empty() || component == "." || component == "..")
    {
        return Err(StateLayoutError::InvalidPath {
            path: path.to_owned(),
        });
    }
    Ok(())
}

const fn entry_kind_rank(kind: StateEntryKind) -> u8 {
    match kind {
        StateEntryKind::Directory => 0,
        StateEntryKind::File => 1,
    }
}

fn validate_probe(probe: &StateProbe) -> Result<(), StateLayoutError> {
    if !probe.root_exists {
        if probe.root_empty || probe.manifest_version.is_some() || probe.clean_shutdown.is_some() {
            return Err(StateLayoutError::InvalidProbe);
        }
        return Ok(());
    }
    if probe.root_empty && (probe.manifest_version.is_some() || probe.clean_shutdown.is_some()) {
        return Err(StateLayoutError::InvalidProbe);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        STATE_LAYOUT_VERSION, StateAction, StateEntry, StateLayoutError, StateLayoutManifest,
        StateProbe, StateReason, decide_state_action,
    };

    #[test]
    fn fresh_manifest_is_sorted_and_round_trips() {
        let manifest = StateLayoutManifest::fresh("/var/lib/praxis-rs", 1).expect("layout");
        assert_eq!(manifest.layout_version, STATE_LAYOUT_VERSION);
        assert_eq!(manifest.entries[0], StateEntry::directory("audit"));
        assert_eq!(
            manifest.entries.last().expect("last"),
            &StateEntry::directory("tmp")
        );
        assert!(
            manifest
                .entries
                .contains(&StateEntry::file("runtime/checkpoint.json"))
        );
        let restored =
            StateLayoutManifest::decode(&manifest.encode().expect("encode")).expect("decode");
        assert_eq!(restored, manifest);
    }

    #[test]
    fn malformed_entries_fail_closed() {
        assert!(matches!(
            StateLayoutManifest::new("/tmp/state", 1, vec![]),
            Err(StateLayoutError::EmptyLayout)
        ));
        assert!(matches!(
            StateLayoutManifest::new("/tmp/state", 1, vec![StateEntry::file("../escape")]),
            Err(StateLayoutError::InvalidPath { .. })
        ));
        assert!(matches!(
            StateLayoutManifest::new(
                "/tmp/state",
                1,
                vec![StateEntry::file("audit/events.jsonl")]
            ),
            Err(StateLayoutError::MissingParent { .. })
        ));
    }

    #[test]
    fn state_actions_are_explicit_and_fail_closed() {
        let cases = [
            (
                StateProbe {
                    root_exists: false,
                    root_empty: false,
                    manifest_version: None,
                    clean_shutdown: None,
                },
                StateAction::Initialize,
                StateReason::MissingRoot,
            ),
            (
                StateProbe {
                    root_exists: true,
                    root_empty: true,
                    manifest_version: None,
                    clean_shutdown: None,
                },
                StateAction::Initialize,
                StateReason::EmptyRoot,
            ),
            (
                StateProbe {
                    root_exists: true,
                    root_empty: false,
                    manifest_version: None,
                    clean_shutdown: None,
                },
                StateAction::Reject,
                StateReason::MissingManifest,
            ),
            (
                StateProbe {
                    root_exists: true,
                    root_empty: false,
                    manifest_version: Some(0),
                    clean_shutdown: None,
                },
                StateAction::Migrate,
                StateReason::OlderLayout,
            ),
            (
                StateProbe {
                    root_exists: true,
                    root_empty: false,
                    manifest_version: Some(2),
                    clean_shutdown: Some(true),
                },
                StateAction::Reject,
                StateReason::FutureLayout,
            ),
            (
                StateProbe {
                    root_exists: true,
                    root_empty: false,
                    manifest_version: Some(1),
                    clean_shutdown: Some(false),
                },
                StateAction::Recover,
                StateReason::UncleanShutdown,
            ),
        ];
        for (probe, action, reason) in cases {
            let decision = decide_state_action(&probe, 1).expect("decision");
            assert_eq!(decision.action, action);
            assert_eq!(decision.reason, reason);
        }
    }
}
