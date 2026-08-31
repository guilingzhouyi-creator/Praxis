//! One-shot Rust protocol-host bootstrap coordination.
//!
//! `HostBootstrap` is the composition seam between an adapter that owns
//! deployment policy and the bounded protocol/router mechanisms. It validates
//! every requested binding before exposing the assembled host. A failed
//! preflight drops the private candidate, so callers never observe a
//! half-wired executor, command registry, or settings endpoint.

use std::collections::BTreeSet;
use std::sync::Arc;

use crate::capability::CapabilityExecutor;
use crate::contract::{CapabilityRequest, CapabilityResult};
use crate::host_authorization::{HostAuthorizationContext, MAX_HOST_ID_BYTES};
use crate::protocol_host_runtime::{ProtocolHostRuntime, ProtocolHostRuntimeConfig};
use crate::runtime::KernelRuntime;
use crate::settings_protocol::SettingsAuthorizer;

/// Maximum UTF-8 bytes retained for one host command name.
pub const MAX_HOST_COMMAND_NAME_BYTES: usize = MAX_HOST_ID_BYTES;

/// Rust runtime and authorizer pair for an explicit settings binding.
pub struct HostSettingsBinding {
    /// Rust-owned runtime that serves settings snapshots.
    pub runtime: Arc<KernelRuntime>,
    /// Host policy that authorizes settings reads and writes.
    pub authorizer: Arc<dyn SettingsAuthorizer>,
}

impl HostSettingsBinding {
    /// Build an explicit settings binding.
    pub fn new(runtime: Arc<KernelRuntime>, authorizer: Arc<dyn SettingsAuthorizer>) -> Self {
        Self {
            runtime,
            authorizer,
        }
    }
}

/// All authority-bearing inputs required for one host composition.
pub struct HostBootstrapSpec {
    /// Trusted principal/session/posture evidence.
    pub context: HostAuthorizationContext,
    /// Additional command names to register beside system commands.
    pub commands: Vec<String>,
    /// Optional capability executor; absence preserves fail-closed dispatch.
    pub executor: Option<CapabilityExecutor>,
    /// Optional settings endpoint binding.
    pub settings: Option<HostSettingsBinding>,
}

impl HostBootstrapSpec {
    /// Start a spec with no optional authorities or commands.
    pub fn new(context: HostAuthorizationContext) -> Self {
        Self {
            context,
            commands: Vec::new(),
            executor: None,
            settings: None,
        }
    }

    /// Add command names to the explicit registration set.
    pub fn with_commands(mut self, commands: Vec<String>) -> Self {
        self.commands = commands;
        self
    }

    /// Supply a capability executor through a type-erased closure.
    pub fn with_executor<F>(mut self, executor: F) -> Self
    where
        F: Fn(CapabilityRequest) -> CapabilityResult + Send + Sync + 'static,
    {
        self.executor = Some(Arc::new(executor));
        self
    }

    /// Supply the Rust settings runtime and host authorizer.
    pub fn with_settings(mut self, binding: HostSettingsBinding) -> Self {
        self.settings = Some(binding);
        self
    }
}

/// Stable preflight/assembly errors for the host bootstrap boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HostBootstrapError {
    /// The trusted context failed its bounded validation.
    InvalidContext(String),
    /// A command name is empty, over-sized, contains NUL, or is reserved.
    InvalidCommand(String),
    /// A command name appeared more than once in the spec.
    DuplicateCommand(String),
    /// The context could not be installed in the fresh router.
    ContextBinding(String),
    /// The settings endpoint could not be installed in the fresh router.
    SettingsBinding,
}

impl std::fmt::Display for HostBootstrapError {
    /// Render a stable fail-closed bootstrap diagnostic.
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidContext(message) => write!(formatter, "invalid host context: {message}"),
            Self::InvalidCommand(message) => write!(formatter, "invalid host command: {message}"),
            Self::DuplicateCommand(command) => {
                write!(formatter, "duplicate host command: {command}")
            }
            Self::ContextBinding(message) => {
                write!(formatter, "host context binding failed: {message}")
            }
            Self::SettingsBinding => write!(formatter, "settings endpoint binding failed"),
        }
    }
}

impl std::error::Error for HostBootstrapError {}

/// Stable report of one fully assembled host.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HostBootstrapReport {
    /// Trusted principal installed in the router.
    pub principal: String,
    /// Session bound to the trusted context.
    pub session_id: String,
    /// Number of additional commands installed.
    pub command_count: usize,
    /// Whether a capability executor was explicitly wired.
    pub executor_wired: bool,
    /// Whether settings were explicitly wired.
    pub settings_wired: bool,
    /// Strict context requirement enabled by this bootstrap.
    pub requires_host_context: bool,
}

/// One-shot host composition result.
pub struct HostBootstrap {
    runtime: ProtocolHostRuntime,
    context: HostAuthorizationContext,
    report: HostBootstrapReport,
}

impl HostBootstrap {
    /// Validate and assemble a strict host runtime in one operation.
    ///
    /// All validation occurs before any private router mutation. The returned
    /// host requires a bound trusted context for authority-bearing dispatch;
    /// no production authority is inferred when optional bindings are absent.
    pub fn new(
        config: ProtocolHostRuntimeConfig,
        spec: HostBootstrapSpec,
    ) -> Result<Self, HostBootstrapError> {
        validate_spec(&spec)?;
        let router = config.router.with_required_host_context();
        let runtime = ProtocolHostRuntime::new(ProtocolHostRuntimeConfig { router, ..config });
        let context = spec.context;
        if !runtime
            .bind_authorization_context(context.clone())
            .map_err(|error| HostBootstrapError::ContextBinding(error.to_owned()))?
        {
            return Err(HostBootstrapError::ContextBinding(
                "context already bound in fresh router".to_owned(),
            ));
        }
        for command in &spec.commands {
            runtime.register_command(command.clone());
        }
        if let Some(executor) = spec.executor {
            runtime.register_executor_arc(executor);
        }
        let settings_wired = if let Some(settings) = spec.settings {
            if !runtime.register_settings_endpoint(settings.runtime, settings.authorizer) {
                return Err(HostBootstrapError::SettingsBinding);
            }
            true
        } else {
            false
        };
        let report = HostBootstrapReport {
            principal: context.principal.clone(),
            session_id: context.session_id.clone(),
            command_count: spec.commands.len(),
            executor_wired: runtime.router().has_executor(),
            settings_wired,
            requires_host_context: runtime.router().config().requires_host_context(),
        };
        Ok(Self {
            runtime,
            context,
            report,
        })
    }

    /// Return the assembled protocol host.
    pub fn runtime(&self) -> &ProtocolHostRuntime {
        &self.runtime
    }

    /// Return the trusted context copied into this host.
    pub fn context(&self) -> &HostAuthorizationContext {
        &self.context
    }

    /// Return the deterministic assembly report.
    pub fn report(&self) -> &HostBootstrapReport {
        &self.report
    }

    /// Consume the coordinator and return the assembled host.
    pub fn into_runtime(self) -> ProtocolHostRuntime {
        self.runtime
    }
}

fn validate_spec(spec: &HostBootstrapSpec) -> Result<(), HostBootstrapError> {
    spec.context
        .validate()
        .map_err(|error| HostBootstrapError::InvalidContext(error.to_owned()))?;
    let mut seen = BTreeSet::new();
    for command in &spec.commands {
        if command.trim().is_empty() {
            return Err(HostBootstrapError::InvalidCommand(
                "command name must be non-empty".to_owned(),
            ));
        }
        if command.len() > MAX_HOST_COMMAND_NAME_BYTES {
            return Err(HostBootstrapError::InvalidCommand(
                "command name exceeds the configured bound".to_owned(),
            ));
        }
        if command.contains('\0') {
            return Err(HostBootstrapError::InvalidCommand(
                "command name must not contain NUL".to_owned(),
            ));
        }
        if crate::host_dispatch::SYSTEM_COMMANDS.contains(&command.as_str()) {
            return Err(HostBootstrapError::InvalidCommand(format!(
                "command is reserved for system dispatch: {command}"
            )));
        }
        if !seen.insert(command) {
            return Err(HostBootstrapError::DuplicateCommand(command.clone()));
        }
    }
    Ok(())
}
