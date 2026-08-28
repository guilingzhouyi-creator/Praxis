//! Rust-owned kernel assembly boundary for the clean-break build.
//!
//! `KernelAssembly` validates the declarative boot plan, fresh state layout,
//! port metadata, and lifecycle starting state. It intentionally performs no
//! filesystem, configuration, network, subprocess, or provider side effects.

use serde::{Deserialize, Serialize};

use crate::KERNEL_CONTRACT_VERSION;
use crate::boot::{BootPlan, BootPlanError, BootStepSpec};
use crate::config_store::{ConfigError, ConfigLayoutManifest};
use crate::lifecycle::{LifecycleRegistry, LifecycleState};
use crate::ports::{PortDescriptor, PortRegistry, PortRegistryError};
use crate::protocol::{ProtocolDescriptor, ProtocolDescriptorError};
use crate::state_layout::{
    STATE_LAYOUT_VERSION, StateAction, StateDecision, StateLayoutError, StateLayoutManifest,
    StateProbe, decide_state_action,
};
use crate::terminal::{TerminalContractDescriptor, TerminalContractError};

/// Version of the declarative Rust assembly snapshot.
pub const ASSEMBLY_VERSION: u32 = 1;

/// Input to the independent Rust assembly boundary.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssemblySpec {
    /// Contract version expected by all assembled mechanisms.
    pub contract_version: u32,
    /// Host-selected Rust state root.
    pub state_root: String,
    /// Host-selected Rust configuration root.
    pub config_root: String,
    /// Contract version declared by the configuration root.
    pub config_contract_version: u32,
    /// Retained wire protocol descriptor.
    pub protocol: ProtocolDescriptor,
    /// Terminal substrate descriptor carried by the kernel.
    pub terminal: TerminalContractDescriptor,
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
            config_root: String::new(),
            config_contract_version: KERNEL_CONTRACT_VERSION,
            protocol: ProtocolDescriptor::current(),
            terminal: TerminalContractDescriptor::current(),
            boot_steps,
            ports,
        }
    }

    /// Override the independent Rust configuration root.
    pub fn with_config_root(mut self, config_root: impl Into<String>) -> Self {
        self.config_root = config_root.into();
        self
    }

    /// Override the config manifest contract for fail-closed tests or hosts.
    pub const fn with_config_contract_version(mut self, version: u32) -> Self {
        self.config_contract_version = version;
        self
    }

    /// Supply an explicit protocol descriptor.
    pub fn with_protocol(mut self, protocol: ProtocolDescriptor) -> Self {
        self.protocol = protocol;
        self
    }

    /// Supply an explicit terminal descriptor.
    pub fn with_terminal(mut self, terminal: TerminalContractDescriptor) -> Self {
        self.terminal = terminal;
        self
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
    /// Rust configuration manifest metadata is invalid or divergent.
    Config(ConfigAssemblyError),
    /// Boot plan validation failed.
    BootPlan(BootPlanError),
    /// Port metadata validation failed.
    Ports(PortRegistryError),
    /// Retained protocol metadata is unsupported.
    Protocol(ProtocolDescriptorError),
    /// Terminal substrate metadata is unsupported.
    Terminal(TerminalContractError),
}

/// Configuration metadata failures that can cross the declarative assembly seam.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConfigAssemblyError {
    /// The configuration root is invalid.
    InvalidRoot,
    /// A configuration entry is invalid.
    InvalidPath(String),
    /// The layout contains no entries.
    EmptyLayout,
    /// A configuration entry is duplicated.
    DuplicateEntry(String),
    /// The requested config contract does not match this kernel.
    ContractVersion { expected: u32, actual: u32 },
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
    /// Complete Rust-owned configuration manifest metadata.
    pub config_manifest: ConfigLayoutManifest,
    /// Retained protocol descriptor.
    pub protocol: ProtocolDescriptor,
    /// Terminal substrate descriptor.
    pub terminal: TerminalContractDescriptor,
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
    config_manifest: ConfigLayoutManifest,
    boot_plan: BootPlan,
    ports: PortRegistry,
    protocol: ProtocolDescriptor,
    terminal: TerminalContractDescriptor,
    lifecycle: LifecycleRegistry,
}

impl KernelAssembly {
    /// Validate and assemble a clean-break Rust kernel boundary.
    ///
    /// # Errors
    ///
    /// AssemblyError when spec/config/protocol/terminal descriptors diverge or metadata mismatches — fail-closed by design.
    pub fn assemble(spec: AssemblySpec) -> Result<Self, AssemblyError> {
        if spec.contract_version != KERNEL_CONTRACT_VERSION {
            return Err(AssemblyError::InvalidContractVersion {
                expected: KERNEL_CONTRACT_VERSION,
                actual: spec.contract_version,
            });
        }
        let manifest = StateLayoutManifest::fresh(spec.state_root, spec.contract_version)
            .map_err(AssemblyError::StateLayout)?;
        let config_root = if spec.config_root.is_empty() {
            format!("{}/config", manifest.state_root)
        } else {
            spec.config_root
        };
        let config_manifest =
            ConfigLayoutManifest::fresh(config_root, spec.config_contract_version)
                .map_err(map_config_error)?;
        if config_manifest.contract_version != KERNEL_CONTRACT_VERSION {
            return Err(AssemblyError::Config(
                ConfigAssemblyError::ContractVersion {
                    expected: KERNEL_CONTRACT_VERSION,
                    actual: config_manifest.contract_version,
                },
            ));
        }
        spec.protocol.validate().map_err(AssemblyError::Protocol)?;
        spec.terminal.validate().map_err(AssemblyError::Terminal)?;

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
            config_manifest,
            boot_plan,
            ports,
            protocol: spec.protocol,
            terminal: spec.terminal,
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
            config_manifest: self.config_manifest.clone(),
            protocol: self.protocol.clone(),
            terminal: self.terminal.clone(),
            boot_order: self
                .boot_plan
                .resolve_order()
                .expect("validated assembly boot plan remains valid"),
            ports: self.ports.snapshot(),
            lifecycle_state: self.lifecycle.state(),
        }
    }

    /// Select a state action from a host probe without applying side effects.
    ///
    /// # Errors
    ///
    /// AssemblyError when the layout probe cannot classify the root.
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
    ///
    /// # Errors
    ///
    /// AssemblyError when the decision maps to no executable action.
    pub fn state_action(&self, probe: &StateProbe) -> Result<StateAction, StateLayoutError> {
        self.state_decision(probe).map(|decision| decision.action)
    }
}

fn map_config_error(error: ConfigError) -> AssemblyError {
    let mapped = match error {
        ConfigError::InvalidRoot => ConfigAssemblyError::InvalidRoot,
        ConfigError::InvalidPath(path) => ConfigAssemblyError::InvalidPath(path),
        ConfigError::EmptyLayout => ConfigAssemblyError::EmptyLayout,
        ConfigError::DuplicateEntry(path) => ConfigAssemblyError::DuplicateEntry(path),
        ConfigError::UnsupportedLayout(_)
        | ConfigError::UnsupportedDocument(_)
        | ConfigError::InvalidKey(_)
        | ConfigError::InvalidDocument { .. }
        | ConfigError::RootNotDirectory(_)
        | ConfigError::ForeignRoot(_)
        | ConfigError::RollbackFailed { .. }
        | ConfigError::Io(_) => ConfigAssemblyError::InvalidRoot,
    };
    AssemblyError::Config(mapped)
}
