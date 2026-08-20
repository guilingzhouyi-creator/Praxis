//! Rust-owned kernel assembly boundary for the clean-break build.
//!
//! `KernelAssembly` validates the declarative boot plan, fresh state layout,
//! port metadata, and lifecycle starting state. It intentionally performs no
//! filesystem, configuration, network, subprocess, or provider side effects.

use serde::{Deserialize, Serialize};

use crate::KERNEL_CONTRACT_VERSION;
use crate::boot::{BootPlan, BootPlanError, BootStepSpec};
use crate::lifecycle::{LifecycleRegistry, LifecycleState};
use crate::ports::{PortDescriptor, PortRegistry, PortRegistryError};
use crate::state_layout::{
    STATE_LAYOUT_VERSION, StateAction, StateDecision, StateLayoutError, StateLayoutManifest,
    StateProbe, decide_state_action,
};

/// Version of the declarative Rust assembly snapshot.
pub const ASSEMBLY_VERSION: u32 = 1;

/// Input to the independent Rust assembly boundary.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssemblySpec {
    /// Contract version expected by all assembled mechanisms.
    pub contract_version: u32,
    /// Host-selected Rust state root.
    pub state_root: String,
    /// Declarative boot steps.
    pub boot_steps: Vec<BootStepSpec>,
    /// Declarative provider metadata.
    pub ports: Vec<PortDescriptor>,
}

impl AssemblySpec {
    /// Create a minimal clean-break assembly specification for a host.
    pub fn new(
        state_root: impl Into<String>,
        boot_steps: Vec<BootStepSpec>,
        ports: Vec<PortDescriptor>,
    ) -> Self {
        Self {
            contract_version: KERNEL_CONTRACT_VERSION,
            state_root: state_root.into(),
            boot_steps,
            ports,
        }
    }
}

/// Structured assembly validation errors.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssemblyError {
    /// Contract version is unsupported by this build.
    InvalidContractVersion { expected: u32, actual: u32 },
    /// State layout validation failed.
    StateLayout(StateLayoutError),
    /// Boot plan validation failed.
    BootPlan(BootPlanError),
    /// Port metadata validation failed.
    Ports(PortRegistryError),
}

/// Stable snapshot emitted by the independent Rust assembly boundary.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssemblySnapshot {
    /// Assembly snapshot version.
    pub assembly_version: u32,
    /// Kernel contract version.
    pub contract_version: u32,
    /// State layout version.
    pub state_layout_version: u32,
    /// Rust-owned state root selected by the host.
    pub state_root: String,
    /// Dependency-first boot order.
    pub boot_order: Vec<String>,
    /// Locked port declarations in registration order.
    pub ports: Vec<PortDescriptor>,
    /// Initial lifecycle state.
    pub lifecycle_state: LifecycleState,
}

/// Validated independent Rust kernel assembly.
pub struct KernelAssembly {
    manifest: StateLayoutManifest,
    boot_plan: BootPlan,
    ports: PortRegistry,
    lifecycle: LifecycleRegistry,
}

impl KernelAssembly {
    /// Validate and assemble a clean-break Rust kernel boundary.
    pub fn assemble(spec: AssemblySpec) -> Result<Self, AssemblyError> {
        if spec.contract_version != KERNEL_CONTRACT_VERSION {
            return Err(AssemblyError::InvalidContractVersion {
                expected: KERNEL_CONTRACT_VERSION,
                actual: spec.contract_version,
            });
        }
        let manifest = StateLayoutManifest::fresh(spec.state_root, spec.contract_version)
            .map_err(AssemblyError::StateLayout)?;

        let mut boot_plan = BootPlan::new();
        for step in spec.boot_steps {
            boot_plan
                .register(step, false)
                .map_err(AssemblyError::BootPlan)?;
        }
        boot_plan.resolve_order().map_err(AssemblyError::BootPlan)?;
        boot_plan.lock();

        let mut ports = PortRegistry::new();
        for descriptor in spec.ports {
            ports
                .register(descriptor, false)
                .map_err(AssemblyError::Ports)?;
        }
        ports.lock();

        Ok(Self {
            manifest,
            boot_plan,
            ports,
            lifecycle: LifecycleRegistry::new(),
        })
    }

    /// Return the deterministic snapshot without executing any step.
    pub fn snapshot(&self) -> AssemblySnapshot {
        AssemblySnapshot {
            assembly_version: ASSEMBLY_VERSION,
            contract_version: self.manifest.contract_version,
            state_layout_version: self.manifest.layout_version,
            state_root: self.manifest.state_root.clone(),
            boot_order: self
                .boot_plan
                .resolve_order()
                .expect("validated assembly boot plan remains valid"),
            ports: self.ports.snapshot(),
            lifecycle_state: self.lifecycle.state(),
        }
    }

    /// Select a state action from a host probe without applying side effects.
    pub fn state_decision(&self, probe: &StateProbe) -> Result<StateDecision, StateLayoutError> {
        decide_state_action(probe, STATE_LAYOUT_VERSION)
    }

    /// Return whether boot metadata is locked before provider wiring.
    pub fn is_locked(&self) -> bool {
        self.boot_plan.is_locked() && self.ports.is_locked()
    }

    /// Return the initial lifecycle state.
    pub fn lifecycle_state(&self) -> LifecycleState {
        self.lifecycle.state()
    }

    /// Return the assembly's state action type for callers that only need the enum.
    pub fn state_action(&self, probe: &StateProbe) -> Result<StateAction, StateLayoutError> {
        self.state_decision(probe).map(|decision| decision.action)
    }
}

#[cfg(test)]
mod tests {
    use super::{AssemblyError, AssemblySpec, KernelAssembly};
    use crate::KERNEL_CONTRACT_VERSION;
    use crate::boot::BootStepSpec;
    use crate::ports::{PortDescriptor, PortKind};
    use crate::state_layout::{StateAction, StateProbe};

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
}
