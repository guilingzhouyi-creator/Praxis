//! JSON schema version and migration registry candidate for kernel persistence.

use std::collections::BTreeMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock, PoisonError};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Current snapshot schema version mirrored from Python3.
pub const SNAPSHOT_VERSION: u64 = 3;
/// Current checkpoint schema version mirrored from Python3.
pub const CHECKPOINT_VERSION: u64 = 2;
/// Current settings schema version mirrored from Python3.
pub const SETTINGS_VERSION: u64 = 2;
/// Current workspace schema version mirrored from Python3.
pub const WORKSPACE_VERSION: u64 = 2;
/// Current log schema version mirrored from Python3.
pub const LOG_VERSION: u64 = 2;
/// Current card registry schema version mirrored from Python3.
pub const CARD_REGISTRY_VERSION: u64 = 1;
/// Current todo table schema version mirrored from Python3.
pub const TODO_TABLE_VERSION: u64 = 1;
/// Current transaction area schema version mirrored from Python3.
pub const TRANSACTION_AREA_VERSION: u64 = 1;
/// Current dialogue session schema version mirrored from Python3.
pub const DIALOGUE_SESSION_VERSION: u64 = 1;
/// Current execution result schema version mirrored from Python3.
pub const EXECUTION_RESULT_VERSION: u64 = 1;
/// Current capability gate schema version mirrored from Python3.
pub const CAPABILITY_GATE_VERSION: u64 = 1;

/// JSON migration callback accepted by the isolated candidate.
pub type MigrationFn = Arc<dyn Fn(Value) -> Result<Value, String> + Send + Sync + 'static>;

/// Structured versioning errors.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum VersionErrorCode {
    /// A kind has no registered schema definition.
    UnknownKind,
    /// The data is not a JSON object or has an invalid `_version` value.
    InvalidData,
    /// Persisted data is newer than this candidate.
    FutureVersion,
    /// A step between two schema versions is missing.
    MissingMigration,
    /// A migration callback failed or panicked.
    MigrationFailed,
}

/// Versioning error crossing the adapter boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VersionError {
    /// Stable machine-readable category.
    pub code: VersionErrorCode,
    /// Human-readable context.
    pub message: String,
}

impl VersionError {
    fn new(code: VersionErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

/// One applied migration step in a deterministic report.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppliedMigration {
    /// Source schema version.
    pub from_version: u64,
    /// Destination schema version.
    pub to_version: u64,
    /// Human-readable migration label.
    pub label: String,
}

/// Result of checking and migrating one JSON object.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MigrationResult {
    /// Migrated or unchanged JSON object.
    pub value: Value,
    /// Steps applied in ascending version order.
    pub applied: Vec<AppliedMigration>,
}

struct MigrationStep {
    label: String,
    function: MigrationFn,
}

struct VersionEntry {
    current: u64,
    steps: BTreeMap<u64, MigrationStep>,
}

/// Thread-safe registry of schema versions and JSON migration callbacks.
pub struct VersionRegistry {
    entries: Mutex<BTreeMap<String, VersionEntry>>,
}

impl VersionRegistry {
    /// Create a registry populated with Python3's current persistence kinds.
    pub fn new() -> Self {
        let registry = Self {
            entries: Mutex::new(BTreeMap::new()),
        };
        for (kind, current) in default_kinds() {
            registry.register_kind(kind, current);
        }
        registry
    }

    /// Register or replace one kind and fill historical steps with identity migrations.
    pub fn register_kind(&self, kind: impl Into<String>, current: u64) {
        let kind = kind.into();
        let mut steps = BTreeMap::new();
        for from_version in 1..current {
            steps.insert(
                from_version,
                MigrationStep {
                    label: "identity".to_owned(),
                    function: Arc::new(Ok),
                },
            );
        }
        self.lock_entries()
            .insert(kind, VersionEntry { current, steps });
    }

    /// Register or replace one migration step.
    pub fn register_migration<F>(
        &self,
        kind: &str,
        from_version: u64,
        label: impl Into<String>,
        function: F,
    ) -> Result<(), VersionError>
    where
        F: Fn(Value) -> Result<Value, String> + Send + Sync + 'static,
    {
        let mut entries = self.lock_entries();
        let entry = entries.get_mut(kind).ok_or_else(|| {
            VersionError::new(
                VersionErrorCode::UnknownKind,
                format!("unknown kind: {kind}"),
            )
        })?;
        entry.steps.insert(
            from_version,
            MigrationStep {
                label: label.into(),
                function: Arc::new(function),
            },
        );
        Ok(())
    }

    /// Return the current version for a kind, if registered.
    pub fn current_version(&self, kind: &str) -> Option<u64> {
        self.lock_entries().get(kind).map(|entry| entry.current)
    }

    /// Stamp a JSON object with the current kind version; unknown kinds are unchanged.
    pub fn stamp(&self, value: Value, kind: &str) -> Value {
        let Some(current) = self.current_version(kind) else {
            return value;
        };
        let Value::Object(mut object) = value else {
            return value;
        };
        object.insert("_version".to_owned(), Value::from(current));
        Value::Object(object)
    }

    /// Check and apply all pending migrations in order.
    pub fn check_and_migrate(
        &self,
        value: Value,
        kind: &str,
    ) -> Result<MigrationResult, VersionError> {
        let mut value = value;
        let current = {
            let entries = self.lock_entries();
            let Some(entry) = entries.get(kind) else {
                return Ok(MigrationResult {
                    value,
                    applied: Vec::new(),
                });
            };
            entry.current
        };
        let mut object = match value {
            Value::Object(object) => object,
            other => {
                return Err(VersionError::new(
                    VersionErrorCode::InvalidData,
                    format!("{kind} persistence must be a JSON object, got {other}"),
                ));
            }
        };
        let file_version = read_version(&object, kind)?;
        if file_version > current {
            return Err(VersionError::new(
                VersionErrorCode::FutureVersion,
                format!("{kind} file version {file_version} > current {current}"),
            ));
        }
        if file_version == current {
            return Ok(MigrationResult {
                value: Value::Object(object),
                applied: Vec::new(),
            });
        }

        let mut applied = Vec::new();
        for from_version in file_version..current {
            let step = {
                let entries = self.lock_entries();
                let entry = entries.get(kind).expect("kind checked above");
                let step = entry.steps.get(&from_version).ok_or_else(|| {
                    VersionError::new(
                        VersionErrorCode::MissingMigration,
                        format!(
                            "no migration {kind} v{from_version} -> v{}",
                            from_version + 1
                        ),
                    )
                })?;
                (step.label.clone(), Arc::clone(&step.function))
            };
            let old_value = Value::Object(object);
            let migrated =
                catch_unwind(AssertUnwindSafe(|| (step.1)(old_value))).map_err(|_| {
                    VersionError::new(
                        VersionErrorCode::MigrationFailed,
                        format!("migration {kind} v{from_version} panicked"),
                    )
                })?;
            object = migrated
                .map_err(|error| {
                    VersionError::new(
                        VersionErrorCode::MigrationFailed,
                        format!("migration {kind} v{from_version} failed: {error}"),
                    )
                })?
                .as_object()
                .cloned()
                .ok_or_else(|| {
                    VersionError::new(
                        VersionErrorCode::InvalidData,
                        format!("migration {kind} v{from_version} returned a non-object"),
                    )
                })?;
            object.insert("_version".to_owned(), Value::from(from_version + 1));
            applied.push(AppliedMigration {
                from_version,
                to_version: from_version + 1,
                label: step.0,
            });
        }
        value = Value::Object(object);
        Ok(MigrationResult { value, applied })
    }

    fn lock_entries(&self) -> MutexGuard<'_, BTreeMap<String, VersionEntry>> {
        self.entries.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for VersionRegistry {
    fn default() -> Self {
        Self::new()
    }
}

/// Stamp a JSON object with the global registry's current kind version.
pub fn stamp(value: Value, kind: &str) -> Value {
    get_versioning().stamp(value, kind)
}

/// Check and migrate a JSON object through the global registry.
pub fn check_and_migrate(value: Value, kind: &str) -> Result<MigrationResult, VersionError> {
    get_versioning().check_and_migrate(value, kind)
}

/// Register a migration on the global registry.
pub fn register_migration<F>(
    kind: &str,
    from_version: u64,
    label: impl Into<String>,
    function: F,
) -> Result<(), VersionError>
where
    F: Fn(Value) -> Result<Value, String> + Send + Sync + 'static,
{
    get_versioning().register_migration(kind, from_version, label, function)
}

static GLOBAL_VERSIONING: OnceLock<Mutex<Option<Arc<VersionRegistry>>>> = OnceLock::new();

fn global_versioning() -> &'static Mutex<Option<Arc<VersionRegistry>>> {
    GLOBAL_VERSIONING.get_or_init(|| Mutex::new(None))
}

/// Return the process-wide schema registry candidate.
pub fn get_versioning() -> Arc<VersionRegistry> {
    let mut slot = global_versioning()
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    Arc::clone(slot.get_or_insert_with(|| Arc::new(VersionRegistry::new())))
}

/// Reset the process-wide schema registry for test isolation.
pub fn reset_versioning() {
    *global_versioning()
        .lock()
        .unwrap_or_else(PoisonError::into_inner) = None;
}

fn read_version(object: &Map<String, Value>, kind: &str) -> Result<u64, VersionError> {
    let Some(value) = object.get("_version") else {
        return Ok(0);
    };
    value.as_u64().ok_or_else(|| {
        VersionError::new(
            VersionErrorCode::InvalidData,
            format!("{kind} _version must be a non-negative integer"),
        )
    })
}

fn default_kinds() -> [(&'static str, u64); 6] {
    [
        ("snapshot", SNAPSHOT_VERSION),
        ("checkpoint", CHECKPOINT_VERSION),
        ("card_registry", CARD_REGISTRY_VERSION),
        ("todo_table", TODO_TABLE_VERSION),
        ("transaction_area", TRANSACTION_AREA_VERSION),
        ("capability_gate", CAPABILITY_GATE_VERSION),
    ]
}

#[cfg(test)]
mod tests {
    use super::{
        CHECKPOINT_VERSION, SNAPSHOT_VERSION, VersionErrorCode, VersionRegistry, check_and_migrate,
        reset_versioning, stamp,
    };
    use serde_json::json;

    fn fixture() -> serde_json::Value {
        serde_json::from_str(include_str!(
            "../../../tests/fixtures/kernel_versioning_vectors.json"
        ))
        .expect("versioning fixture must be valid JSON")
    }

    #[test]
    fn stamp_and_same_version_preserve_json_contract() {
        let registry = VersionRegistry::new();
        let stamped = registry.stamp(json!({"key": "value"}), "snapshot");
        assert_eq!(stamped["_version"], SNAPSHOT_VERSION);
        let checked = registry
            .check_and_migrate(stamped.clone(), "snapshot")
            .unwrap();
        assert_eq!(checked.value, stamped);
        assert!(checked.applied.is_empty());
    }

    #[test]
    fn custom_steps_apply_in_order_and_set_each_version() {
        let registry = VersionRegistry::new();
        registry.register_kind("custom", 3);
        registry
            .register_migration("custom", 1, "one", |mut value| {
                value["one"] = json!(true);
                Ok(value)
            })
            .unwrap();
        registry
            .register_migration("custom", 2, "two", |mut value| {
                value["two"] = json!(true);
                Ok(value)
            })
            .unwrap();
        let result = registry
            .check_and_migrate(json!({"_version": 1}), "custom")
            .unwrap();
        assert_eq!(result.value["_version"], 3);
        assert_eq!(result.value["one"], true);
        assert_eq!(result.value["two"], true);
        assert_eq!(result.applied.len(), 2);
    }

    #[test]
    fn future_unknown_and_invalid_data_fail_closed() {
        let registry = VersionRegistry::new();
        assert_eq!(
            registry
                .check_and_migrate(json!({"_version": 99}), "snapshot")
                .unwrap_err()
                .code,
            VersionErrorCode::FutureVersion
        );
        let unknown = registry
            .check_and_migrate(json!({"_version": 1}), "unknown")
            .unwrap();
        assert_eq!(unknown.value["_version"], 1);
        assert_eq!(
            registry
                .check_and_migrate(json!({"_version": -1}), "snapshot")
                .unwrap_err()
                .code,
            VersionErrorCode::InvalidData
        );
        assert_eq!(
            registry
                .register_migration("ghost", 1, "nope", Ok)
                .unwrap_err()
                .code,
            VersionErrorCode::UnknownKind
        );
    }

    #[test]
    fn migration_failures_and_non_object_results_are_structured() {
        let registry = VersionRegistry::new();
        registry.register_kind("custom", 2);
        registry
            .register_migration("custom", 1, "bad", |_| Err("boom".to_owned()))
            .unwrap();
        assert_eq!(
            registry
                .check_and_migrate(json!({"_version": 1}), "custom")
                .unwrap_err()
                .code,
            VersionErrorCode::MigrationFailed
        );
        registry
            .register_migration("custom", 1, "scalar", |_| Ok(json!(1)))
            .unwrap();
        assert_eq!(
            registry
                .check_and_migrate(json!({"_version": 1}), "custom")
                .unwrap_err()
                .code,
            VersionErrorCode::InvalidData
        );
    }

    #[test]
    fn global_registry_can_be_reset() {
        reset_versioning();
        assert_eq!(
            stamp(json!({}), "checkpoint")["_version"],
            CHECKPOINT_VERSION
        );
        let result =
            check_and_migrate(json!({"_version": CHECKPOINT_VERSION}), "checkpoint").unwrap();
        assert!(result.applied.is_empty());
        reset_versioning();
    }

    #[test]
    fn shared_versioning_vectors_match_python_reference() {
        let registry = VersionRegistry::new();
        let vectors = fixture();
        for case in vectors["cases"].as_array().unwrap() {
            let kind = case["kind"].as_str().unwrap();
            let input = case["input"].clone();
            match case["case"].as_str().unwrap() {
                "stamp_snapshot" => {
                    assert_eq!(registry.stamp(input, kind), case["expect"]);
                }
                "checkpoint_identity_migration" | "unknown_kind" => {
                    let result = registry.check_and_migrate(input, kind).unwrap();
                    assert_eq!(result.value, case["expect"]);
                    assert_eq!(
                        serde_json::to_value(result.applied).unwrap(),
                        case["applied"]
                    );
                }
                "future_version" | "missing_zero_migration" => {
                    let error = registry.check_and_migrate(input, kind).unwrap_err();
                    let expected = match case["error"].as_str().unwrap() {
                        "FUTURE_VERSION" => VersionErrorCode::FutureVersion,
                        "MISSING_MIGRATION" => VersionErrorCode::MissingMigration,
                        other => panic!("unexpected fixture error: {other}"),
                    };
                    assert_eq!(error.code, expected);
                }
                other => panic!("unexpected versioning fixture case: {other}"),
            }
        }
        assert_eq!(registry.current_version("settings"), None);
        assert_eq!(registry.current_version("workspace"), None);
    }
}
