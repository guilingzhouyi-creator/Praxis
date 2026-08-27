//! Independent assembly mechanism tests for the Rust kernel.

use l1_kernel_rs::KERNEL_CONTRACT_VERSION;
use l1_kernel_rs::assembly::{AssemblyError, AssemblySpec, ConfigAssemblyError, KernelAssembly};
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::state_layout::{StateAction, StateProbe};

fn spec() -> AssemblySpec {
    AssemblySpec::new(
        "/var/lib/praxis-rs",
        vec![
            BootStepSpec::new("cell", vec!["services".to_owned()]),
            BootStepSpec::new("services", vec!["config".to_owned()]),
            BootStepSpec::new("config", Vec::new()),
        ],
        vec![
            PortDescriptor::new("process", PortKind::Process, 1),
            PortDescriptor::new("storage", PortKind::Storage, 1),
        ],
    )
}

#[test]
fn assembly_is_locked_and_deterministic() {
    let assembly = KernelAssembly::assemble(spec()).expect("assembly");
    let snapshot = assembly.snapshot();
    assert!(assembly.is_locked());
    assert_eq!(snapshot.boot_order, ["config", "services", "cell"]);
    assert_eq!(snapshot.ports[0].name, "process");
    assert_eq!(snapshot.lifecycle_state.as_str(), "halted");
}

#[test]
fn assembly_rejects_invalid_contract_or_plan() {
    let mut invalid_contract = spec();
    invalid_contract.contract_version += 1;
    assert!(matches!(
        KernelAssembly::assemble(invalid_contract),
        Err(AssemblyError::InvalidContractVersion { .. })
    ));
    let mut invalid_plan = spec();
    invalid_plan.boot_steps = vec![BootStepSpec::new("cell", vec!["missing".to_owned()])];
    assert!(matches!(
        KernelAssembly::assemble(invalid_plan),
        Err(AssemblyError::BootPlan(_))
    ));
    let mut invalid_config = spec();
    invalid_config.config_contract_version += 1;
    assert!(matches!(
        KernelAssembly::assemble(invalid_config),
        Err(AssemblyError::Config(
            ConfigAssemblyError::ContractVersion { .. }
        ))
    ));
    let mut invalid_protocol = spec();
    invalid_protocol.protocol.protocol_version += 1;
    assert!(matches!(
        KernelAssembly::assemble(invalid_protocol),
        Err(AssemblyError::Protocol(_))
    ));
    let mut invalid_terminal = spec();
    invalid_terminal.terminal.max_frame_bytes += 1;
    assert!(matches!(
        KernelAssembly::assemble(invalid_terminal),
        Err(AssemblyError::Terminal(_))
    ));
}

#[test]
fn assembly_exposes_state_decision_without_mutation() {
    let assembly = KernelAssembly::assemble(spec()).expect("assembly");
    let decision = assembly
        .state_decision(&StateProbe {
            root_exists: true,
            root_empty: false,
            manifest_version: Some(1),
            clean_shutdown: Some(false),
        })
        .expect("decision");
    assert_eq!(decision.action, StateAction::Recover);
    assert_eq!(assembly.lifecycle_state().as_str(), "halted");
    assert_eq!(KERNEL_CONTRACT_VERSION, 1);
}
