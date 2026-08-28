//! Ordered schema migration runner candidate for install-time kernel work.

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock, PoisonError};

use serde::{Deserialize, Serialize};

/// Current archive/schema version mirrored from the Python migration module.
pub const SCHEMA_VERSION: &str = "20260730.1";

/// Migration callback with no interpreter objects crossing the boundary.
pub type MigrationFn = Arc<dyn Fn() -> Result<(), String> + Send + Sync + 'static>;

/// One failed migration in a run report.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationFailure {
    /// Target version whose callback failed.
    pub version: String,
    /// Stable adapter-provided failure text.
    pub error: String,
}

/// Result of applying migrations up to a target version.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationReport {
    /// Target versions applied in order.
    pub applied: Vec<String>,
    /// First failure, if any; later migrations are not attempted.
    pub errors: Vec<MigrationFailure>,
}

struct MigrationEntry {
    version: String,
    function: MigrationFn,
}

/// Ordered migration registry matching Python's append-on-registration behavior.
pub struct MigrationRunner {
    entries: Mutex<Vec<MigrationEntry>>,
}

impl MigrationRunner {
    /// Create an empty runner.
    pub fn new() -> Self {
        Self {
            entries: Mutex::new(Vec::new()),
        }
    }

    /// Register or replace a target-version migration and keep lexical order.
    pub fn register<F>(&self, version: impl Into<String>, function: F)
    where
        F: Fn() -> Result<(), String> + Send + Sync + 'static,
    {
        let version = version.into();
        let mut entries = self.lock_entries();
        entries.push(MigrationEntry {
            version,
            function: Arc::new(function),
        });
        entries.sort_by(|left, right| left.version.cmp(&right.version));
    }

    /// Run entries strictly newer than `current` and no newer than `target`.
    pub fn run_pending(&self, current: &str, target: &str) -> MigrationReport {
        let entries = self
            .lock_entries()
            .iter()
            .map(|entry| (entry.version.clone(), Arc::clone(&entry.function)))
            .collect::<Vec<_>>();
        let mut report = MigrationReport {
            applied: Vec::new(),
            errors: Vec::new(),
        };
        for (version, function) in entries {
            if version.as_str() <= current {
                continue;
            }
            // Entries are sorted at registration, so the first version past the target stops the scan.
            if version.as_str() > target {
                break;
            }
            // Fail closed on panic: capture it and surface a stable, non-panicking error.
            let result = catch_unwind(AssertUnwindSafe(|| function()))
                .map_err(|_| "migration callback panicked".to_owned());
            match result.and_then(|result| result) {
                Ok(()) => report.applied.push(version),
                Err(error) => {
                    // Stop the run at the first error so later migrations are not attempted.
                    report.errors.push(MigrationFailure { version, error });
                    break;
                }
            }
        }
        report
    }

    /// Lock the entry list, recovering from a poisoned mutex rather than panicking.
    fn lock_entries(&self) -> MutexGuard<'_, Vec<MigrationEntry>> {
        self.entries.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for MigrationRunner {
    fn default() -> Self {
        Self::new()
    }
}

static GLOBAL_MIGRATIONS: OnceLock<Mutex<Option<Arc<MigrationRunner>>>> = OnceLock::new();

/// Initialize the process-wide runner slot on first use, returning the shared mutex.
fn global_migrations() -> &'static Mutex<Option<Arc<MigrationRunner>>> {
    GLOBAL_MIGRATIONS.get_or_init(|| Mutex::new(None))
}

/// Return the process-wide migration runner candidate.
pub fn get_migrations() -> Arc<MigrationRunner> {
    let mut slot = global_migrations()
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    Arc::clone(slot.get_or_insert_with(|| Arc::new(MigrationRunner::new())))
}

/// Register a migration on the process-wide runner.
pub fn register_migration<F>(version: impl Into<String>, function: F)
where
    F: Fn() -> Result<(), String> + Send + Sync + 'static,
{
    get_migrations().register(version, function);
}

/// Run global migrations against the current schema target.
pub fn run_pending(current: &str) -> MigrationReport {
    get_migrations().run_pending(current, SCHEMA_VERSION)
}

/// Reset global migration state for test isolation.
pub fn reset_migrations() {
    *global_migrations()
        .lock()
        .unwrap_or_else(PoisonError::into_inner) = None;
}
