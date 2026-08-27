//! Independent tests for the read-only Rust kernel entry preflight.

use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::preflight::{PreflightDisposition, PreflightRequest, inspect};
use l1_kernel_rs::state_layout::{StateAction, StateProbe};

fn request(probe: StateProbe) -> PreflightRequest {
    PreflightRequest {
        assembly: AssemblySpec::new(
            "/var/lib/praxis-rs",
            vec![
                BootStepSpec::new("cell", vec!["services".to_owned()]),
                BootStepSpec::new("services", vec!["config".to_owned()]),
                BootStepSpec::new("config", Vec::new()),
            ],
            vec![PortDescriptor::new("process", PortKind::Process, 1)],
        ),
        state_probe: probe,
    }
}

#[test]
fn preflight_is_deterministic_and_side_effect_free() {
    let report = inspect(request(StateProbe {
        root_exists: true,
        root_empty: false,
        manifest_version: Some(1),
        clean_shutdown: Some(true),
    }))
    .expect("preflight");
    assert_eq!(report.state_decision.action, StateAction::Resume);
    assert_eq!(report.disposition, PreflightDisposition::Ready);
    assert_eq!(report.assembly.boot_order, ["config", "services", "cell"]);
    assert_eq!(report.assembly.lifecycle_state.as_str(), "halted");
}

#[test]
fn preflight_exposes_recovery_without_booting() {
    let report = inspect(request(StateProbe {
        root_exists: true,
        root_empty: false,
        manifest_version: Some(1),
        clean_shutdown: Some(false),
    }))
    .expect("preflight");
    assert_eq!(report.state_decision.action, StateAction::Recover);
    assert_eq!(report.disposition, PreflightDisposition::RecoveryRequired);
    assert_eq!(report.assembly.lifecycle_state.as_str(), "halted");
}

#[test]
fn preflight_rejects_invalid_assembly_before_state_mutation() {
    let mut request = request(StateProbe {
        root_exists: false,
        root_empty: false,
        manifest_version: None,
        clean_shutdown: None,
    });
    request.assembly.boot_steps = vec![BootStepSpec::new("cell", vec!["missing".to_owned()])];
    assert!(inspect(request).is_err());
}
