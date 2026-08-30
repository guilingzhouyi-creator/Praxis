//! Independent tests for the Rust settings-to-ConfigStore adapter.

use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use l1_kernel_rs::config_store::ConfigStore;
use l1_kernel_rs::settings::{
    SettingsProvider, SettingsRegistry, SettingsSource, SettingsValues, default_values,
};
use l1_kernel_rs::settings_adapter::ConfigStoreSettingsProvider;
use serde_json::json;

fn temp_root() -> std::path::PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "praxis-settings-adapter-{}-{nanos}",
        std::process::id()
    ))
}

#[test]
fn persistent_provider_overlays_defaults_and_tracks_store_revision() {
    let root = temp_root();
    let store = Arc::new(Mutex::new(
        ConfigStore::open(&root, 1).expect("fresh Rust config root"),
    ));
    let provider = Arc::new(ConfigStoreSettingsProvider::new(Arc::clone(&store)));
    let registry = SettingsRegistry::new();
    let initial = registry
        .set_provider(Arc::clone(&provider) as Arc<dyn SettingsProvider>)
        .expect("attach config provider");

    assert_eq!(initial.source, SettingsSource::Injected);
    assert_eq!(initial.revision, 0);
    assert_eq!(
        registry.get("llm.provider").expect("default provider"),
        Some(json!("ollama"))
    );
    assert!(
        store
            .lock()
            .expect("store lock")
            .settings()
            .values
            .is_empty()
    );

    let changed = registry
        .set("llm.provider", json!("rust-host"))
        .expect("persist setting");
    assert_eq!(changed.revision, 1);
    assert_eq!(
        store.lock().expect("store lock").settings().values["llm.provider"],
        json!("rust-host")
    );

    let batch = SettingsValues::from([
        ("shells.default".to_owned(), json!("bash")),
        ("runtime.adapter".to_owned(), json!("rust")),
    ]);
    let changed = registry.set_many(batch).expect("persist batch");
    assert_eq!(changed.revision, 2);
    assert_eq!(
        registry.get("runtime.adapter").expect("adapter"),
        Some(json!("rust"))
    );

    let reset = registry
        .reset("llm.provider")
        .expect("restore default setting");
    assert_eq!(reset.revision, 3);
    assert_eq!(
        registry.get("llm.provider").expect("restored provider"),
        Some(json!("ollama"))
    );
    registry.reset("runtime.adapter").expect("remove unknown");
    assert_eq!(registry.get("runtime.adapter").expect("unknown"), None);

    registry.reset_all().expect("restore all defaults");
    assert_eq!(registry.all().expect("default snapshot"), default_values());
    assert_eq!(
        store.lock().expect("store lock").settings().values,
        default_values()
    );
    std::fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn provider_handle_can_be_shared_with_runtime_configuration_owner() {
    let root = temp_root();
    let store = Arc::new(Mutex::new(
        ConfigStore::open(&root, 1).expect("fresh Rust config root"),
    ));
    let provider = ConfigStoreSettingsProvider::new(Arc::clone(&store));
    assert!(Arc::ptr_eq(&provider.store(), &store));
    provider
        .set_l2("shells.default", json!("pwsh"))
        .expect("persist L2 setting");
    let reopened = ConfigStore::open(&root, 1).expect("reopen Rust config root");
    assert_eq!(reopened.settings().values["shells.default"], json!("pwsh"));
    std::fs::remove_dir_all(root).expect("remove test root");
}
