//! Cross-language vectors for the independent Rust kernel assembly boundary.

use l1_kernel_rs::assembly::{AssemblySpec, KernelAssembly};
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::ports::PortDescriptor;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct AssemblyVectors {
    state_root: String,
    boot_steps: Vec<BootStepSpec>,
    ports: Vec<PortDescriptor>,
    expected_boot_order: Vec<String>,
    expected_port_order: Vec<String>,
}

#[test]
fn shared_assembly_vectors_match_rust_entry_boundary() {
    let vectors: AssemblyVectors = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_assembly_vectors.json"
    ))
    .expect("valid assembly vectors");
    let assembly = KernelAssembly::assemble(AssemblySpec::new(
        vectors.state_root,
        vectors.boot_steps,
        vectors.ports,
    ))
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
    assert!(assembly.is_locked());
}
