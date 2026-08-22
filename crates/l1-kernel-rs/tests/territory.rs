//! Independent territory containment tests for the Rust kernel.

use std::path::Path;

use l1_kernel_rs::territory::{TerritoryCheck, is_within, is_within_at};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct TerritoryVector {
    target: String,
    bases: Vec<String>,
    #[serde(default)]
    working_dir: String,
    expected: bool,
}

#[test]
fn boundary_matching_is_component_aware() {
    assert!(is_within(
        "/project/foo/main.py",
        &["/project/foo".to_owned()]
    ));
    assert!(!is_within(
        "/project/foo_secret/main.py",
        &["/project/foo".to_owned()]
    ));
    assert!(is_within("/etc/passwd", &["/".to_owned()]));
}

#[test]
fn explicit_working_directory_is_deterministic() {
    let check = TerritoryCheck {
        target: "src/../src/main.rs".to_owned(),
        bases: vec!["src".to_owned()],
        working_dir: "/workspace/praxis".to_owned(),
    };
    assert!(check.evaluate());
    assert!(!is_within_at(
        "src/main.rs",
        &["/workspace/praxis/src".to_owned()],
        Path::new("/workspace/other")
    ));
}

#[test]
fn shared_territory_vectors_match_python_reference() {
    let vectors: Vec<TerritoryVector> = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_territory_vectors.json"
    ))
    .expect("territory fixture must be valid JSON");
    for vector in vectors {
        let working_dir = if vector.working_dir.is_empty() {
            "."
        } else {
            vector.working_dir.as_str()
        };
        let actual = is_within_at(&vector.target, &vector.bases, Path::new(working_dir));
        assert_eq!(
            actual, vector.expected,
            "territory vector target {}",
            vector.target
        );
    }
}
