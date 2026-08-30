//! Independent settings-facade tests for the Rust kernel.

use std::sync::{Arc, Mutex};

use l1_kernel_rs::settings::{
    MAX_SETTING_KEY_BYTES, MAX_SETTINGS, ProviderSnapshot, SettingsError, SettingsProvider,
    SettingsRegistry, SettingsSource, SettingsValues, default_values,
};
use serde_json::{Value, json};

#[derive(Default)]
struct FakeProvider {
    values: Mutex<SettingsValues>,
    calls: Mutex<Vec<String>>,
}

impl FakeProvider {
    fn new(values: SettingsValues) -> Self {
        Self {
            values: Mutex::new(values),
            calls: Mutex::new(Vec::new()),
        }
    }

    fn calls(&self) -> Vec<String> {
        self.calls.lock().expect("calls lock").clone()
    }
}

impl SettingsProvider for FakeProvider {
    fn snapshot(&self) -> Result<ProviderSnapshot, String> {
        Ok(ProviderSnapshot {
            revision: self.calls.lock().expect("calls lock").len() as u64,
            values: self.values.lock().expect("values lock").clone(),
        })
    }

    fn set(&self, key: &str, value: Value) -> Result<(), String> {
        self.calls
            .lock()
            .expect("calls lock")
            .push(format!("set:{key}"));
        self.values
            .lock()
            .expect("values lock")
            .insert(key.to_owned(), value);
        Ok(())
    }

    fn set_many(&self, values: &SettingsValues) -> Result<(), String> {
        self.calls
            .lock()
            .expect("calls lock")
            .push("set_many".to_owned());
        self.values
            .lock()
            .expect("values lock")
            .extend(values.clone());
        Ok(())
    }

    fn reset(&self, key: &str) -> Result<(), String> {
        self.calls
            .lock()
            .expect("calls lock")
            .push(format!("reset:{key}"));
        self.values.lock().expect("values lock").remove(key);
        Ok(())
    }

    fn reset_all(&self) -> Result<(), String> {
        self.calls
            .lock()
            .expect("calls lock")
            .push("reset_all".to_owned());
        self.values.lock().expect("values lock").clear();
        Ok(())
    }
}

#[test]
fn fallback_defaults_support_read_category_and_reset() {
    let registry = SettingsRegistry::new();
    assert_eq!(
        registry.get("llm.provider").expect("provider"),
        Some(json!("ollama"))
    );
    assert_eq!(
        registry
            .category("prompt.inject.")
            .expect("prompt category")
            .len(),
        6
    );
    let changed = registry
        .set("llm.provider", json!("mock"))
        .expect("fallback write");
    assert_eq!(changed.source, SettingsSource::Fallback);
    assert_eq!(changed.revision, 1);
    registry.reset("llm.provider").expect("reset provider");
    assert_eq!(
        registry.get("llm.provider").expect("provider"),
        Some(json!("ollama"))
    );
    registry
        .set("test.unknown", json!(true))
        .expect("unknown write");
    registry.reset("test.unknown").expect("unknown reset");
    assert_eq!(registry.get("test.unknown").expect("unknown"), None);
}

#[test]
fn fallback_batch_is_transactional_and_reset_all_restores_defaults() {
    let registry = SettingsRegistry::new();
    let mut values = SettingsValues::new();
    values.insert("prompt.inject.memory".to_owned(), json!(false));
    values.insert("runtime.mode".to_owned(), json!("test"));
    let snapshot = registry.set_many(values).expect("batch write");
    assert_eq!(snapshot.revision, 1);
    assert!(!registry.prompt_injection_enabled("memory"));
    registry.reset_all().expect("reset all");
    assert!(registry.prompt_injection_enabled("memory"));
    assert_eq!(registry.get("runtime.mode").expect("runtime mode"), None);
}

#[test]
fn provider_is_validated_and_receives_all_mutations() {
    let provider = Arc::new(FakeProvider::new(
        [("llm.provider".to_owned(), json!("rust-host"))]
            .into_iter()
            .collect(),
    ));
    let registry = SettingsRegistry::new();
    let attached = registry
        .set_provider(Arc::clone(&provider) as Arc<dyn SettingsProvider>)
        .expect("attach provider");
    assert_eq!(attached.source, SettingsSource::Injected);
    assert_eq!(
        registry.get("llm.provider").expect("provider"),
        Some(json!("rust-host"))
    );
    assert_eq!(
        registry.all().expect("provider all")["llm.provider"],
        json!("rust-host")
    );
    registry
        .set_l2("shells.default", json!("bash"))
        .expect("l2 set");
    registry
        .set_many(
            [("ci.review.enabled".to_owned(), json!(false))]
                .into_iter()
                .collect(),
        )
        .expect("provider batch");
    registry.reset("shells.default").expect("provider reset");
    registry.reset_all().expect("provider reset all");
    assert_eq!(
        provider.calls(),
        vec![
            "set:shells.default",
            "set_many",
            "reset:shells.default",
            "reset_all"
        ]
    );
    registry.clear_provider();
    assert_eq!(
        registry.get("llm.provider").expect("fallback provider"),
        Some(json!("ollama"))
    );
}

#[test]
fn malformed_provider_and_invalid_identities_fail_closed() {
    let registry = SettingsRegistry::new();
    assert!(matches!(
        registry.get("\0",),
        Err(SettingsError::InvalidKey(key)) if key == "\0"
    ));
    assert!(matches!(
        registry.category(&"x".repeat(MAX_SETTING_KEY_BYTES + 1)),
        Err(SettingsError::InvalidKey(_))
    ));
    let oversized: SettingsValues = (0..=MAX_SETTINGS)
        .map(|index| (format!("setting.{index}"), json!(index)))
        .collect();
    let provider = Arc::new(FakeProvider::new(oversized));
    assert!(matches!(
        registry.set_provider(provider as Arc<dyn SettingsProvider>),
        Err(SettingsError::InvalidProviderSnapshot(_))
    ));
    assert_eq!(
        registry.snapshot().expect("fallback snapshot").source,
        SettingsSource::Fallback
    );
}

#[test]
fn prompt_injection_defaults_to_enabled_for_missing_or_non_boolean_values() {
    let registry = SettingsRegistry::new();
    assert!(registry.prompt_injection_enabled("missing"));
    registry
        .set("prompt.inject.memory", json!("invalid"))
        .expect("write malformed value");
    assert!(registry.prompt_injection_enabled("memory"));
}

#[test]
fn provider_panics_are_contained_as_explicit_failures() {
    struct PanickingProvider;

    impl SettingsProvider for PanickingProvider {
        fn snapshot(&self) -> Result<ProviderSnapshot, String> {
            panic!("snapshot panic");
        }

        fn set(&self, _key: &str, _value: Value) -> Result<(), String> {
            panic!("set panic");
        }

        fn set_many(&self, _values: &SettingsValues) -> Result<(), String> {
            panic!("set_many panic");
        }

        fn reset(&self, _key: &str) -> Result<(), String> {
            panic!("reset panic");
        }

        fn reset_all(&self) -> Result<(), String> {
            panic!("reset_all panic");
        }
    }

    let registry = SettingsRegistry::new();
    assert!(matches!(
        registry.set_provider(Arc::new(PanickingProvider)),
        Err(SettingsError::Provider(message)) if message.contains("panicked during snapshot")
    ));
    let provider = Arc::new(FakeProvider::new(default_values()));
    registry
        .set_provider(Arc::clone(&provider) as Arc<dyn SettingsProvider>)
        .expect("attach provider");
    let panicking = Arc::new(PanickingProvider);
    assert!(registry.set_provider(panicking).is_err());
}

#[test]
fn default_values_match_expected_semantic_surface() {
    let defaults = default_values();
    assert_eq!(defaults["llm.model"], json!("codellama:7b"));
    assert_eq!(defaults["engineering_debug.mode"], json!("auto"));
    assert_eq!(
        defaults["engineering_debug.marker_file"],
        json!(".praxis/debug_mode.flag")
    );
    assert_eq!(defaults.len(), 60);
}
