//! Cross-language vectors for the independent Rust kernel assembly boundary.

use l1_kernel_rs::assembly::{AssemblySpec, KernelAssembly};
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::ports::PortDescriptor;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct AssemblyVectors {
    state_root: String,
    config_root: String,
    expected_config_layout_version: u32,
    expected_protocol_version: u32,
    expected_terminal_contract_version: u32,
    boot_steps: Vec<BootStepSpec>,
    ports: Vec<PortDescriptor>,
    expected_boot_order: Vec<String>,
    expected_port_order: Vec<String>,
}

#[test]
fn shared_assembly_vectors_match_rust_entry_boundary() {
    let vectors: AssemblyVectors = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_assembly_vectors.json"
    ))
    .expect("valid assembly vectors");
    let assembly = KernelAssembly::assemble(
        AssemblySpec::new(vectors.state_root, vectors.boot_steps, vectors.ports)
            .with_config_root(vectors.config_root),
    )
    .expect("assembly");
    let snapshot = assembly.snapshot();
    assert_eq!(snapshot.boot_order, vectors.expected_boot_order);
    assert_eq!(
        snapshot
            .ports
            .into_iter()
            .map(|port| port.name)
            .collect::<Vec<_>>(),
        vectors.expected_port_order
    );
    assert_eq!(snapshot.lifecycle_state.as_str(), "halted");
    assert_eq!(
        snapshot.config_manifest.layout_version,
        vectors.expected_config_layout_version
    );
    assert_eq!(
        snapshot.protocol.protocol_version,
        vectors.expected_protocol_version
    );
    assert_eq!(
        snapshot.terminal.contract_version,
        vectors.expected_terminal_contract_version
    );
    assert!(assembly.is_locked());
}
