//! Cross-language vectors for Rust port values and declarative registration.

use l1_kernel_rs::ports::{
    Endpoint, InputActivitySnapshot, Message, PortDescriptor, PortKind, PortRegistry, PortResult,
};
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Deserialize)]
struct PortVectors {
    descriptors: Vec<PortDescriptor>,
    expected_order: Vec<String>,
    values: Values,
}

#[derive(Debug, Deserialize)]
struct Values {
    result_ok: PortResult,
    endpoint: Endpoint,
    message: Message,
    input_activity: InputActivitySnapshot,
}

#[test]
fn shared_port_vectors_match_rust_boundary() {
    let vectors: PortVectors = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_port_vectors.json"
    ))
    .expect("valid port vectors");
    let mut registry = PortRegistry::new();
    for descriptor in vectors.descriptors {
        registry.register(descriptor, false).expect("descriptor");
    }
    assert_eq!(
        registry
            .snapshot()
            .into_iter()
            .map(|descriptor| descriptor.name)
            .collect::<Vec<_>>(),
        vectors.expected_order
    );
    assert!(vectors.values.endpoint.validate().is_ok());
    assert!(vectors.values.message.validate().is_ok());
    assert!(vectors.values.input_activity.validate().is_ok());
    assert_eq!(
        serde_json::to_value(vectors.values.result_ok).expect("result json"),
        Value::Object(
            [
                ("success".to_owned(), Value::Bool(true)),
                ("error".to_owned(), Value::String(String::new())),
                ("data".to_owned(), Value::Object(Default::default()))
            ]
            .into_iter()
            .collect()
        )
    );
    assert_eq!(PortKind::Process, PortKind::Process);
}
