//! Independent integration tests for the Rust-owned state-store boundary.

use std::fs;
use std::sync::atomic::{AtomicU64, Ordering};

use l1_kernel_rs::lifecycle::LifecycleState;
use l1_kernel_rs::state_layout::StateAction;
use l1_kernel_rs::state_store::{CHECKPOINT_VERSION, StateStore};

static TEST_ID: AtomicU64 = AtomicU64::new(1);

fn temp_root(label: &str) -> std::path::PathBuf {
    let id = TEST_ID.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "praxis-rust-integration-{label}-{}-{id}",
        std::process::id()
    ))
}

#[test]
fn fresh_root_has_only_rust_owned_layout() {
    let root = temp_root("layout");
    let store = StateStore::open(&root, 1).expect("fresh root opens");
    assert_eq!(store.action(), StateAction::Initialize);
    assert_eq!(store.manifest().layout_version, 1);
    assert!(root.join("manifest.json").is_file());
    assert!(root.join("runtime/checkpoint.json").is_file());
    assert_eq!(store.lifecycle().state(), LifecycleState::Halted);
    drop(store);
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn checkpoint_generation_and_recovery_are_durable() {
    let root = temp_root("checkpoint");
    {
        let mut store = StateStore::open(&root, 1).expect("initialize");
        store.begin_boot().expect("begin boot");
        store.mark_active().expect("mark active");
        assert!(store.generation() >= 3);
        store.shutdown(false).expect("record unclean shutdown");
    }
    let mut store = StateStore::open(&root, 1).expect("recover root");
    assert_eq!(store.action(), StateAction::Recover);
    assert_eq!(store.lifecycle().state(), LifecycleState::Crashed);
    let generation = store.generation();
    store.recover().expect("persist recovery marker");
    assert!(store.generation() > generation);
    store.begin_boot().expect("restart after recovery");
    store.mark_active().expect("mark active after recovery");
    store.shutdown(true).expect("clean shutdown");
    drop(store);
    assert_eq!(
        StateStore::open(&root, 1).unwrap().action(),
        StateAction::Resume
    );
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn incomplete_manifest_layout_fails_closed() {
    let root = temp_root("incomplete");
    let store = StateStore::open(&root, 1).expect("initialize");
    drop(store);
    fs::remove_file(root.join("journal/events.jsonl")).expect("remove declared file");
    assert!(StateStore::open(&root, 1).is_err());
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn clean_reopen_preserves_checkpoint_contract() {
    let root = temp_root("clean");
    let store = StateStore::open(&root, 1).expect("initialize");
    assert_eq!(store.lifecycle().state(), LifecycleState::Halted);
    assert_eq!(
        store.checkpoint().expect("checkpoint").checkpoint_version,
        CHECKPOINT_VERSION
    );
    drop(store);
    let reopened = StateStore::open(&root, 1).expect("resume");
    assert_eq!(reopened.action(), StateAction::Resume);
    assert_eq!(reopened.generation(), 1);
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn unclean_shutdown_requires_explicit_recovery() {
    let root = temp_root("recover");
    {
        let mut store = StateStore::open(&root, 1).expect("initialize");
        store.begin_boot().expect("begin boot");
        store.mark_active().expect("mark active");
        store.shutdown(false).expect("record unclean shutdown");
    }
    let mut reopened = StateStore::open(&root, 1).expect("recover");
    assert_eq!(reopened.action(), StateAction::Recover);
    assert_eq!(reopened.lifecycle().state(), LifecycleState::Crashed);
    reopened.recover().expect("recover state");
    reopened.begin_boot().expect("restart after recovery");
    reopened.mark_active().expect("mark active after recovery");
    reopened.shutdown(true).expect("clean shutdown");
    drop(reopened);
    assert_eq!(
        StateStore::open(&root, 1).unwrap().action(),
        StateAction::Resume
    );
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn failed_checkpoint_write_rolls_back_lifecycle_and_generation() {
    let root = temp_root("rollback");
    let mut store = StateStore::open(&root, 1).expect("initialize");
    let previous = store.lifecycle().snapshot();
    let previous_generation = store.generation();
    let checkpoint = root.join("runtime/checkpoint.json");
    fs::remove_file(&checkpoint).expect("remove checkpoint");
    fs::create_dir(&checkpoint).expect("block checkpoint replacement");

    assert!(store.begin_boot().is_err());
    assert_eq!(store.lifecycle().snapshot(), previous);
    assert_eq!(store.generation(), previous_generation);
    let temporary_files = fs::read_dir(root.join("runtime"))
        .expect("runtime directory")
        .filter_map(Result::ok)
        .filter(|entry| {
            entry
                .file_name()
                .to_string_lossy()
                .starts_with(".checkpoint.json.tmp-")
        })
        .count();
    assert_eq!(temporary_files, 0, "failed rename must clean its temp file");

    fs::remove_dir(&checkpoint).expect("remove blocking directory");
    store
        .persist()
        .expect("retry after restoring checkpoint target");
    assert_eq!(store.generation(), previous_generation + 1);
    drop(store);
    let reopened = StateStore::open(&root, 1).expect("reopen rolled back root");
    assert_eq!(reopened.lifecycle().snapshot(), previous);
    assert_eq!(reopened.generation(), previous_generation + 1);
    fs::remove_dir_all(root).expect("remove test root");
}
