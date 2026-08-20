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
            if version.as_str() > target {
                break;
            }
            let result = catch_unwind(AssertUnwindSafe(|| function()))
                .map_err(|_| "migration callback panicked".to_owned());
            match result.and_then(|result| result) {
                Ok(()) => report.applied.push(version),
                Err(error) => {
                    report.errors.push(MigrationFailure { version, error });
                    break;
                }
            }
        }
        report
    }

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

#[cfg(test)]
mod tests {
    use super::{MigrationRunner, SCHEMA_VERSION, reset_migrations, run_pending};
    use std::sync::{Arc, Mutex};

    #[test]
    fn pending_migrations_are_sorted_and_bounded_by_target() {
        let runner = MigrationRunner::new();
        let mut calls = Vec::new();
        runner.register("20260731.1", || Ok(()));
        runner.register("20260730.2", || Ok(()));
        runner.register("20260801.1", || Ok(()));
        let report = runner.run_pending("20260730.1", "20260731.1");
        calls.extend(report.applied.clone());
        assert_eq!(calls, vec!["20260730.2", "20260731.1"]);
        assert!(report.errors.is_empty());
    }

    #[test]
    fn failure_stops_later_migrations_and_panic_is_structured() {
        let runner = MigrationRunner::new();
        runner.register("20260731.1", || Err("disk unavailable".to_owned()));
        runner.register("20260732.1", || panic!("unexpected"));
        let report = runner.run_pending("20260730.1", "20260732.1");
        assert!(report.applied.is_empty());
        assert_eq!(report.errors[0].version, "20260731.1");
        assert_eq!(report.errors[0].error, "disk unavailable");

        let panic_runner = MigrationRunner::new();
        panic_runner.register("20260732.1", || panic!("unexpected"));
        let panic_report = panic_runner.run_pending("20260731.1", "20260732.1");
        assert_eq!(panic_report.errors[0].version, "20260732.1");
        assert_eq!(panic_report.errors[0].error, "migration callback panicked");
    }

    #[test]
    fn duplicate_versions_run_in_registration_order() {
        let runner = MigrationRunner::new();
        let calls = Arc::new(Mutex::new(Vec::new()));
        let first_calls = Arc::clone(&calls);
        runner.register("20260731.1", move || {
            first_calls.lock().unwrap().push("first");
            Ok(())
        });
        let second_calls = Arc::clone(&calls);
        runner.register("20260731.1", move || {
            second_calls.lock().unwrap().push("second");
            Ok(())
        });
        let report = runner.run_pending("20260730.1", "20260731.1");
        assert_eq!(report.applied, vec!["20260731.1", "20260731.1"]);
        assert_eq!(*calls.lock().unwrap(), vec!["first", "second"]);
    }

    #[test]
    fn global_runner_can_be_reset() {
        reset_migrations();
        let report = run_pending(SCHEMA_VERSION);
        assert!(report.applied.is_empty());
        assert!(report.errors.is_empty());
        reset_migrations();
    }
}
