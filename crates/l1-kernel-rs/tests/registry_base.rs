//! Independent metadata-registry mechanism tests for the Rust kernel.

use l1_kernel_rs::registry_base::{MapRegistry, RegisterableSpec, RegistryStats};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Debug, Deserialize)]
struct RegistryVector {
    allow_overwrite: bool,
    registrations: Vec<RegisterableSpec>,
    expected_register: Vec<bool>,
    expected_names: Vec<String>,
    category: String,
    expected_category_names: Vec<String>,
    get: Vec<GetVector>,
    expected_stats: RegistryStats,
    expected_public: Vec<Value>,
}

#[derive(Debug, Deserialize)]
struct GetVector {
    name: String,
    expected: Option<RegisterableSpec>,
}

#[test]
fn callbacks_run_only_after_success() {
    let registry = MapRegistry::default();
    let register_count = std::sync::Arc::new(std::sync::Mutex::new(0_u32));
    let unregister_count = std::sync::Arc::new(std::sync::Mutex::new(0_u32));
    let register_count_ref = std::sync::Arc::clone(&register_count);
    registry.set_on_register(move |_, _| {
        *register_count_ref.lock().unwrap() += 1;
    });
    let unregister_count_ref = std::sync::Arc::clone(&unregister_count);
    registry.set_on_unregister(move |_| {
        *unregister_count_ref.lock().unwrap() += 1;
    });
    assert!(registry.register(RegisterableSpec::new("x"), "code"));
    assert!(!registry.register(RegisterableSpec::new("x"), "code"));
    assert!(registry.unregister("x"));
    assert!(!registry.unregister("x"));
    assert_eq!(*register_count.lock().unwrap(), 1);
    assert_eq!(*unregister_count.lock().unwrap(), 1);
}

#[test]
fn public_view_excludes_private_metadata_and_truncates_description() {
    let mut spec = RegisterableSpec::new("x");
    spec.description = "x".repeat(250);
    spec.metadata.insert("secret".to_owned(), json!(true));
    let public = spec.to_dict();
    assert_eq!(public["description"].as_str().unwrap().chars().count(), 200);
    assert!(public.get("metadata").is_none());
}

#[test]
fn shared_registry_vectors_match_python_reference() {
    let vector: RegistryVector = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_registry_base_vectors.json"
    ))
    .expect("registry fixture must be valid JSON");
    let registry = MapRegistry::new(vector.allow_overwrite);
    let actual_register = vector
        .registrations
        .iter()
        .map(|spec| registry.register(spec.clone(), "fixture"))
        .collect::<Vec<_>>();
    assert_eq!(actual_register, vector.expected_register);
    assert_eq!(registry.all_names(), vector.expected_names);
    assert_eq!(
        registry
            .list_items(&vector.category)
            .into_iter()
            .map(|spec| spec.name)
            .collect::<Vec<_>>(),
        vector.expected_category_names
    );
    for lookup in vector.get {
        assert_eq!(registry.get(&lookup.name), lookup.expected);
    }
    assert_eq!(registry.stats(), vector.expected_stats);
    assert_eq!(
        registry
            .list_items("")
            .into_iter()
            .map(|spec| spec.to_dict())
            .collect::<Vec<_>>(),
        vector.expected_public
    );
}
