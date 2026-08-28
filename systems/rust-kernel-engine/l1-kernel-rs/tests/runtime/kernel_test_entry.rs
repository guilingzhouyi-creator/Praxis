//! Independent tests for the explicit Rust kernel entry coordinator.

use std::time::{Duration, SystemTime, UNIX_EPOCH};

use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::entry::{
    ENTRY_CONTRACT_VERSION, EntryError, EntryOperation, EntryRequest, EntryRuntimeConfig, execute,
};
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::recovery::RecoveryAction;
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig};
use l1_kernel_rs::state_layout::StateAction;
use l1_kernel_rs::state_store::StateStore;
use l1_kernel_rs::worker::WorkerConfig;

fn temp_root(label: &str) -> std::path::PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "praxis-kernel-entry-{label}-{}-{nanos}",
        std::process::id()
    ))
}

fn request(root: &std::path::Path, operation: EntryOperation) -> EntryRequest {
    EntryRequest {
        contract_version: ENTRY_CONTRACT_VERSION,
        assembly: AssemblySpec::new(
            root.to_string_lossy(),
            vec![
                BootStepSpec::new("state", Vec::new()),
                BootStepSpec::new("runtime", vec!["state".to_owned()]),
            ],
            vec![PortDescriptor::new("worker", PortKind::Worker, 1)],
        ),
        runtime: EntryRuntimeConfig {
            max_processes: 2,
            shard_count: 2,
            min_workers: 1,
            max_workers: 1,
            queue_size: 2,
            idle_timeout_ms: 20,
            shutdown_timeout_ms: 1_000,
        },
        operation,
        recovery_ack: None,
    }
}

#[test]
fn inspect_is_explicit_and_does_not_boot_runtime() {
    let root = temp_root("inspect");
    let report = execute(request(&root, EntryOperation::Inspect)).expect("inspect");
    assert_eq!(report.recovery.action, RecoveryAction::Fresh);
    assert!(!report.recovery_acknowledged);
    assert!(report.boot.is_none());
    assert!(report.shutdown.is_none());
    assert_eq!(report.recovery.lifecycle.as_str(), "halted");
    std::fs::remove_dir_all(root).expect("remove root");
}

#[test]
fn boot_once_returns_active_and_clean_halted_snapshots() {
    let root = temp_root("boot");
    let report = execute(request(&root, EntryOperation::BootOnce)).expect("boot once");
    assert_eq!(report.recovery.action, RecoveryAction::Fresh);
    assert_eq!(
        report.boot.expect("boot snapshot").lifecycle.as_str(),
        "active"
    );
    assert_eq!(
        report
            .shutdown
            .expect("shutdown snapshot")
            .lifecycle
            .as_str(),
        "halted"
    );
    let reopened = KernelRuntime::open_persistent(
        AssemblySpec::new(
            root.to_string_lossy(),
            vec![
                BootStepSpec::new("state", Vec::new()),
                BootStepSpec::new("runtime", vec!["state".to_owned()]),
            ],
            vec![PortDescriptor::new("worker", PortKind::Worker, 1)],
        ),
        RuntimeConfig::new(2, 2, WorkerConfig::new(1, 1, 2, Duration::from_millis(20))),
        &root,
    )
    .expect("reopen clean root");
    assert_eq!(
        reopened.recovery_decision().expect("decision").action,
        RecoveryAction::ResumeClean
    );
    assert!(root.join("config/manifest.json").is_file());
    assert!(root.join("config/config.json").is_file());
    assert!(root.join("config/settings.json").is_file());
    std::fs::remove_dir_all(root).expect("remove root");
}

#[test]
fn entry_rejects_foreign_config_root_before_boot() {
    let root = temp_root("foreign-state");
    let foreign = temp_root("foreign-config");
    std::fs::create_dir_all(&foreign).expect("foreign config root");
    std::fs::write(foreign.join("python-settings.json"), b"{}").expect("foreign settings");
    let mut request = request(&root, EntryOperation::BootOnce);
    request.assembly = request.assembly.with_config_root(foreign.to_string_lossy());

    let result = execute(request);
    assert!(matches!(
        result,
        Err(EntryError::Runtime(message)) if message.contains("config root is not Rust-owned")
    ));
    let state_store = StateStore::open(&root, 1).expect("state root remains reusable");
    assert_eq!(state_store.action(), StateAction::Resume);
    assert_eq!(state_store.lifecycle().state().as_str(), "halted");
    std::fs::remove_dir_all(root).expect("remove state root");
    std::fs::remove_dir_all(foreign).expect("remove foreign config root");
}

#[test]
fn unclean_root_requires_the_current_recovery_decision() {
    let root = temp_root("recovery");
    let initial = KernelRuntime::open_persistent(
        request(&root, EntryOperation::Inspect).assembly,
        RuntimeConfig::new(2, 2, WorkerConfig::new(1, 1, 2, Duration::from_millis(20))),
        &root,
    )
    .expect("open root");
    initial.boot().expect("boot");
    initial
        .checkpoint_execution(false)
        .expect("unclean checkpoint");
    drop(initial);

    let missing = execute(request(&root, EntryOperation::Inspect));
    let decision = match missing {
        Err(EntryError::RecoveryRequired(decision)) => decision,
        other => panic!("expected recovery requirement, got {other:?}"),
    };
    let mut stale_request = request(&root, EntryOperation::BootOnce);
    let mut stale = decision.clone();
    stale.generation = stale.generation.saturating_sub(1);
    stale_request.recovery_ack = Some(stale);
    assert_eq!(
        execute(stale_request),
        Err(EntryError::RecoveryDecisionStale)
    );

    let mut accepted_request = request(&root, EntryOperation::BootOnce);
    accepted_request.recovery_ack = Some(decision);
    let report = execute(accepted_request).expect("acknowledged recovery");
    assert!(report.recovery_acknowledged);
    assert_eq!(
        report.shutdown.expect("clean shutdown").lifecycle.as_str(),
        "halted"
    );
    std::fs::remove_dir_all(root).expect("remove root");
}

#[test]
fn invalid_runtime_values_fail_before_creating_state() {
    let root = temp_root("invalid");
    let mut request = request(&root, EntryOperation::Inspect);
    request.runtime.queue_size = 0;
    assert!(matches!(
        execute(request),
        Err(EntryError::InvalidConfig(_))
    ));
    assert!(!root.exists());
}
