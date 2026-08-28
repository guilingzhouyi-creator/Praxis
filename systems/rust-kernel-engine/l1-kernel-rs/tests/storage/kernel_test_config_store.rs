//! Independent integration tests for the Rust-owned configuration store.

use std::fs;

use l1_kernel_rs::config_store::{
    CONFIG_DOCUMENT_VERSION, CONFIG_FILE, CONFIG_MANIFEST_FILE, ConfigDocument, ConfigEntry,
    ConfigError, ConfigLayoutManifest, ConfigStore,
};
use serde_json::json;

fn temp_root(name: &str) -> std::path::PathBuf {
    let root = std::env::temp_dir().join(format!(
        "praxis-rs-config-integration-{name}-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&root);
    root
}

#[test]
fn fresh_root_is_rust_owned_and_reopens_with_values() {
    let root = temp_root("resume");
    let mut store = ConfigStore::open(&root, 1).expect("fresh config root");
    store
        .set_config("scheduler.max_workers", json!(4))
        .expect("config write");
    assert!(root.join(CONFIG_MANIFEST_FILE).is_file());
    assert!(root.join(CONFIG_FILE).is_file());
    drop(store);

    let reopened = ConfigStore::open(&root, 1).expect("matching config root resumes");
    assert_eq!(reopened.config().values["scheduler.max_workers"], json!(4));
    assert_eq!(reopened.config().revision, 1);
    let _ = fs::remove_dir_all(root);
}

#[test]
fn foreign_root_fails_closed_before_mutation() {
    let root = temp_root("foreign");
    fs::create_dir_all(&root).expect("root");
    fs::write(root.join("python-settings.json"), b"{}").expect("foreign data");
    assert!(matches!(
        ConfigStore::open(&root, 1),
        Err(ConfigError::ForeignRoot(_))
    ));
    assert!(!root.join(CONFIG_MANIFEST_FILE).exists());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn precreated_empty_root_is_initialized_and_invalid_key_is_rejected() {
    let root = temp_root("empty");
    fs::create_dir_all(&root).expect("precreated root");
    let mut store = ConfigStore::open(&root, 1).expect("empty root initializes");
    assert!(store.set_config("", json!(true)).is_err());
    assert!(store.config().values.is_empty());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn manifest_is_sorted_and_rejects_unsafe_entries() {
    let manifest = ConfigLayoutManifest::new(
        "/tmp/praxis-config",
        1,
        vec![
            ConfigEntry {
                path: "settings.json".to_owned(),
            },
            ConfigEntry {
                path: "config.json".to_owned(),
            },
        ],
    )
    .expect("manifest");
    assert_eq!(manifest.entries[0].path, "config.json");
    assert!(
        ConfigLayoutManifest::new(
            "/tmp/praxis-config",
            1,
            vec![ConfigEntry {
                path: "../escape".to_owned(),
            }]
        )
        .is_err()
    );
}

#[test]
fn future_documents_fail_closed_on_reopen() {
    let root = temp_root("future");
    let store = ConfigStore::open(&root, 1).expect("fresh config root");
    drop(store);
    let future = ConfigDocument {
        document_version: CONFIG_DOCUMENT_VERSION + 1,
        ..ConfigDocument::default()
    };
    fs::write(
        root.join(CONFIG_FILE),
        serde_json::to_vec(&future).expect("future document serializes"),
    )
    .expect("future document writes");
    assert!(matches!(
        ConfigStore::open(&root, 1),
        Err(ConfigError::UnsupportedDocument(version)) if version == CONFIG_DOCUMENT_VERSION + 1
    ));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn failed_document_write_keeps_in_memory_revision_and_value_unchanged() {
    let root = temp_root("rollback");
    let mut store = ConfigStore::open(&root, 1).expect("fresh config root");
    let previous = store.config().clone();
    let config = root.join(CONFIG_FILE);
    fs::remove_file(&config).expect("remove config");
    fs::create_dir(&config).expect("block config replacement");

    assert!(store.set_config("scheduler.max_workers", json!(8)).is_err());
    assert_eq!(store.config(), &previous);

    fs::remove_dir(&config).expect("remove blocking directory");
    store
        .set_config("scheduler.max_workers", json!(8))
        .expect("retry after restoring config target");
    assert_eq!(store.config().revision, previous.revision + 1);
    assert_eq!(store.config().values["scheduler.max_workers"], json!(8));
    drop(store);
    let reopened = ConfigStore::open(&root, 1).expect("reopen config root");
    assert_eq!(reopened.config().values["scheduler.max_workers"], json!(8));
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn paired_mutation_rolls_back_first_document_when_second_write_fails() {
    let root = temp_root("paired-rollback");
    let mut store = ConfigStore::open(&root, 1).expect("fresh config root");
    let previous_config = store.config().clone();
    let previous_settings = store.settings().clone();
    let previous_config_bytes = fs::read(root.join(CONFIG_FILE)).expect("config bytes");
    let settings = root.join("settings.json");
    fs::remove_file(&settings).expect("remove settings file");
    fs::create_dir(&settings).expect("block settings replacement");

    assert!(
        store
            .set_config_and_setting(
                "scheduler.max_workers",
                json!(8),
                "terminal.preferred",
                json!("bash"),
            )
            .is_err()
    );
    assert_eq!(store.config(), &previous_config);
    assert_eq!(store.settings(), &previous_settings);
    assert_eq!(
        fs::read(root.join(CONFIG_FILE)).expect("rolled-back config bytes"),
        previous_config_bytes
    );
    assert_eq!(
        fs::read_dir(&root)
            .expect("root entries")
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".config.json.tmp-")
            })
            .count(),
        0,
        "failed paired write must clean staged config files"
    );

    fs::remove_dir(&settings).expect("remove settings blocker");
    store
        .set_config_and_setting(
            "scheduler.max_workers",
            json!(8),
            "terminal.preferred",
            json!("bash"),
        )
        .expect("paired retry");
    assert_eq!(store.config().revision, 1);
    assert_eq!(store.settings().revision, 1);
    assert_eq!(store.config().values["scheduler.max_workers"], json!(8));
    assert_eq!(store.settings().values["terminal.preferred"], json!("bash"));
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn failed_rename_removes_config_temporary_file() {
    let root = temp_root("rename-cleanup");
    let mut store = ConfigStore::open(&root, 1).expect("fresh config root");
    let config = root.join(CONFIG_FILE);
    fs::remove_file(&config).expect("remove config");
    fs::create_dir(&config).expect("block config replacement");

    assert!(store.set_config("scheduler.max_workers", json!(8)).is_err());
    assert_eq!(
        fs::read_dir(&root)
            .expect("root entries")
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".config.json.tmp-")
            })
            .count(),
        0,
        "failed rename must clean its temporary file"
    );
    fs::remove_dir(&config).expect("remove config blocker");
    fs::remove_dir_all(root).expect("remove test root");
}
