//! Independent device-table tests for the Rust kernel.

use l1_kernel_rs::device::{DeviceConfig, DeviceRecord, DeviceTable};
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Deserialize)]
struct DeviceVector {
    config: DeviceConfig,
    operations: Vec<Operation>,
}

#[derive(Debug, Deserialize)]
struct Operation {
    op: String,
    name: Option<String>,
    now: Option<f64>,
    success: Option<bool>,
    count: Option<u64>,
    device: Option<DeviceRecord>,
    health: Option<String>,
    expected: Value,
}

#[test]
fn shared_device_vectors_match_python_reference() {
    let vector: DeviceVector = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_device_vectors.json"
    ))
    .expect("device fixture must be valid JSON");
    let table = DeviceTable::new(vector.config);
    for operation in vector.operations {
        let name = operation.name.as_deref().unwrap_or_default();
        let actual = match operation.op.as_str() {
            "register" => Value::from(table.register(operation.device.expect("device"))),
            "check_rate" => table.check_rate(name, operation.now.expect("now")),
            "record_call" => {
                table.record_call(
                    name,
                    operation.success.unwrap_or(true),
                    operation.now.expect("now"),
                );
                Value::Null
            }
            "record_many" => {
                for _ in 0..operation.count.expect("count") {
                    table.record_call(
                        name,
                        operation.success.unwrap_or(true),
                        operation.now.expect("now"),
                    );
                }
                Value::Null
            }
            "refresh_health" => {
                table.refresh_health();
                Value::Null
            }
            "set_health" => Value::from(table.set_health(name, operation.health.expect("health"))),
            "list" => Value::from(table.list(None)),
            "stats" => table.stats(),
            "unregister" => Value::from(table.unregister(name)),
            other => panic!("unknown device vector operation: {other}"),
        };
        assert_eq!(actual, operation.expected, "operation {}", operation.op);
    }
}
