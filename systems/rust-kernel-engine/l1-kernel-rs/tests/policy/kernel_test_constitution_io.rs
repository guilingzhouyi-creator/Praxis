//! Independent Constitution document and persistence tests for the Rust kernel.

use std::collections::BTreeMap;
use std::fs;
use std::sync::Arc;
use std::thread;
use std::time::{SystemTime, UNIX_EPOCH};

use l1_kernel_rs::constitution_io::{
    CONSTITUTION_DEFAULT_REPUTATION, CONSTITUTION_DEFAULT_TOKEN_BUDGET,
    CONSTITUTION_DEFAULT_VERSION, ConstitutionIoError, ConstitutionStore, ConstitutionStoreError,
    TerritoryConstitution,
};

fn temp_root(label: &str) -> std::path::PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "praxis-rs-constitution-{label}-{}-{nanos}",
        std::process::id()
    ))
}

#[test]
fn blank_defaults_and_rendering_are_deterministic() {
    let mut document = TerritoryConstitution::blank("test");
    document
        .territories
        .insert("agent_b".to_owned(), vec!["/z".to_owned(), "/a".to_owned()]);
    document
        .territories
        .insert("agent_a".to_owned(), vec!["/a".to_owned()]);
    document
        .gate_rules
        .insert("G2".to_owned(), "identity".to_owned());
    document
        .gate_rules
        .insert("G1".to_owned(), "workspace".to_owned());

    assert_eq!(document.default_reputation, CONSTITUTION_DEFAULT_REPUTATION);
    assert_eq!(document.token_budget, CONSTITUTION_DEFAULT_TOKEN_BUDGET);
    assert_eq!(document.version, CONSTITUTION_DEFAULT_VERSION);
    assert!(!document.is_blank());
    assert_eq!(
        document.render().expect("render"),
        "# NOMOS Constitution\n\
# Version: 1\n\
\n\
# Territory definitions\n\
agent_a: /a\n\
agent_b: /z, /a\n\
\n\
# GateChain rules\n\
G1: workspace\n\
G2: identity\n\
\n\
# Defaults\n\
default_reputation: 0.85\n\
token_budget: 73000\n"
    );
}

#[test]
fn parser_accepts_valid_sections_and_ignores_unknown_keys() {
    let text = "\
# comment\n\
agent_b: /z, /a\n\
agent_a: /project\n\
G2: identity_verification\n\
default_reputation: 0.9\n\
token_budget: 4200\n\
version: 7\n\
unknown: ignored\n\
not a mapping\n";
    let document = TerritoryConstitution::parse(text, "fixture").expect("parse");
    assert_eq!(document.source, "fixture");
    assert_eq!(
        document.territories["agent_b"],
        vec!["/z".to_owned(), "/a".to_owned()]
    );
    assert_eq!(document.gate_rules["G2"], "identity_verification");
    assert_eq!(document.default_reputation, 0.9);
    assert_eq!(document.token_budget, 4200);
    assert_eq!(document.version, 7);
}

#[test]
fn malformed_known_values_fail_closed() {
    assert!(matches!(
        TerritoryConstitution::parse("default_reputation: nope", "test"),
        Err(ConstitutionIoError::InvalidScalar { key, .. }) if key == "default_reputation"
    ));
    assert!(matches!(
        TerritoryConstitution::parse("default_reputation: 1.1", "test"),
        Err(ConstitutionIoError::InvalidReputation(_))
    ));
    assert!(matches!(
        TerritoryConstitution::parse("token_budget: -1", "test"),
        Err(ConstitutionIoError::InvalidScalar { key, .. }) if key == "token_budget"
    ));
    assert!(matches!(
        TerritoryConstitution::parse("version: 0", "test"),
        Err(ConstitutionIoError::InvalidVersion(_))
    ));
    assert!(matches!(
        TerritoryConstitution::parse("agent_a: /ok\0", "test"),
        Err(ConstitutionIoError::InvalidValue { field }) if field == "agent_a"
    ));
}

#[test]
fn update_merge_and_diff_preserve_versions_and_sorted_changes() {
    let mut old = TerritoryConstitution::blank("old");
    old.update_territory("agent_a", vec!["/project".to_owned(), "/shared".to_owned()])
        .expect("update");
    let old_version = old.version;

    let mut new = old.clone();
    new.update_territory(
        "agent_a",
        vec!["/project".to_owned(), "/workspace".to_owned()],
    )
    .expect("update");
    new.update_territory("agent_b", vec!["/tmp".to_owned()])
        .expect("update");
    let diff = old.diff(&new);
    assert!(diff.changed);
    assert_eq!(diff.changes["agent_a"].added, vec!["/workspace".to_owned()]);
    assert_eq!(diff.changes["agent_a"].removed, vec!["/shared".to_owned()]);
    assert_eq!(diff.changes["agent_b"].added, vec!["/tmp".to_owned()]);
    assert!(diff.changes["agent_b"].removed.is_empty());

    let proposal = BTreeMap::from([
        ("agent_c".to_owned(), vec!["/c".to_owned()]),
        ("external".to_owned(), vec!["/ignored".to_owned()]),
    ]);
    let accepted = new.merge_proposal(&proposal).expect("merge");
    assert_eq!(accepted, vec!["agent_c".to_owned()]);
    assert_eq!(new.version, old_version + 3);
    assert_eq!(new.territories["agent_c"], vec!["/c".to_owned()]);
}

#[test]
fn store_persists_atomic_document_and_reopens() {
    let root = temp_root("persist");
    fs::create_dir_all(&root).expect("root");
    let path = root.join(".praxis-rules.md");
    let store = ConstitutionStore::open(&path).expect("open blank store");
    let updated = store
        .update_territory_and_save("agent_a", vec!["/project".to_owned()])
        .expect("save update");
    assert_eq!(updated.version, 2);
    assert!(path.is_file());
    drop(store);

    let reopened = ConstitutionStore::open(&path).expect("reopen");
    let document = reopened.document();
    assert_eq!(document.territories["agent_a"], vec!["/project".to_owned()]);
    assert_eq!(document.version, 2);
    assert_eq!(document.source, path.to_string_lossy());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn failed_atomic_replace_keeps_memory_and_cleans_temporary_file() {
    let root = temp_root("rollback");
    fs::create_dir_all(&root).expect("root");
    let path = root.join(".praxis-rules.md");
    let store = ConstitutionStore::open(&path).expect("open");
    let previous = store.document();
    fs::create_dir(&path).expect("block destination rename");

    let error = store
        .update_territory_and_save("agent_a", vec!["/project".to_owned()])
        .expect_err("destination directory rejects atomic rename");
    assert!(matches!(error, ConstitutionStoreError::Io(_)));
    assert_eq!(store.document(), previous);
    assert_eq!(
        fs::read_dir(&root)
            .expect("root entries")
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with("..praxis-rules.md.tmp-")
            })
            .count(),
        0
    );

    fs::remove_dir(&path).expect("remove blocker");
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn invalid_replacement_keeps_memory_and_disk_unchanged() {
    let root = temp_root("invalid-replace");
    fs::create_dir_all(&root).expect("root");
    let path = root.join(".praxis-rules.md");
    let store = ConstitutionStore::open(&path).expect("open");
    let previous = store.document();
    let mut invalid = previous.clone();
    invalid.default_reputation = f64::NAN;

    let error = store
        .replace_and_save(invalid)
        .expect_err("invalid replacement");
    assert!(matches!(
        error,
        ConstitutionStoreError::Document(ConstitutionIoError::InvalidReputation(_))
    ));
    assert_eq!(store.document(), previous);
    assert!(!path.exists());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn concurrent_updates_keep_disk_and_memory_versions_aligned() {
    let root = temp_root("concurrent");
    fs::create_dir_all(&root).expect("root");
    let path = root.join(".praxis-rules.md");
    let store = Arc::new(ConstitutionStore::open(&path).expect("open"));
    let mut workers = Vec::new();
    for index in 0..8 {
        let store = Arc::clone(&store);
        workers.push(thread::spawn(move || {
            let agent = format!("agent_{index}");
            store
                .update_territory_and_save(agent, vec![format!("/unit/{index}")])
                .expect("concurrent update");
        }));
    }
    for worker in workers {
        worker.join().expect("worker");
    }

    let document = store.document();
    assert_eq!(document.version, 9);
    assert_eq!(document.territories.len(), 8);
    drop(store);
    let reopened = ConstitutionStore::open(&path).expect("reopen");
    assert_eq!(reopened.document().version, 9);
    assert_eq!(reopened.document().territories.len(), 8);
    fs::remove_dir_all(root).expect("cleanup");
}
