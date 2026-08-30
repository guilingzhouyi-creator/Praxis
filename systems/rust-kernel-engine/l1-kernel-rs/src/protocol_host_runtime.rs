//! Explicit Rust protocol-host runtime composition for the clean-break kernel.
//!
//! This module joins the bounded JSONL gate with [`HostRouter`] while keeping
//! runtime ownership and authorization host-injected. It is an adapter seam,
//! not a production default: settings remain unbound until the caller supplies
//! a Rust runtime and a trusted [`SettingsAuthorizer`].

use std::sync::Arc;

use crate::host_dispatch::{HostRouter, RouterConfig};
use crate::protocol::Message;
use crate::protocol_host::{ProtocolHost, ProtocolHostConfig, ProtocolHostError};
use crate::runtime::KernelRuntime;
use crate::settings_protocol::SettingsAuthorizer;

/// Configuration for one composed protocol-host runtime.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProtocolHostRuntimeConfig {
    /// JSONL frame and retained protocol bounds.
    pub protocol: ProtocolHostConfig,
    /// Router buffer and dispatch bounds.
    pub router: RouterConfig,
}

impl Default for ProtocolHostRuntimeConfig {
    /// Use bounded protocol and router defaults without enabling any runtime
    /// executor or settings authority.
    fn default() -> Self {
        Self {
            protocol: ProtocolHostConfig::default(),
            router: RouterConfig::default(),
        }
    }
}

/// One accepted line after protocol decoding and router dispatch.
#[derive(Debug, Clone, PartialEq)]
pub struct RoutedLine {
    /// The decoded inbound envelope.
    pub request: Message,
    /// Result/event responses produced by the router, including a structured
    /// denial when dispatch reports a protocol-level routing violation.
    pub responses: Vec<Message>,
    /// Transport acknowledgement emitted for every decoded inbound envelope.
    pub ack: Message,
}

/// Composed Rust protocol host with explicit router/runtime seams.
pub struct ProtocolHostRuntime {
    protocol: ProtocolHost,
    router: HostRouter,
}

impl ProtocolHostRuntime {
    /// Construct a host runtime with explicit protocol and router limits.
    ///
    /// No command executor, settings endpoint, L3 upstream, or production
    /// runtime is inferred by this constructor.
    pub fn new(config: ProtocolHostRuntimeConfig) -> Self {
        Self {
            protocol: ProtocolHost::new(config.protocol),
            router: HostRouter::new(config.router),
        }
    }

    /// Return the immutable JSONL protocol gate.
    pub const fn protocol(&self) -> ProtocolHost {
        self.protocol
    }

    /// Return the router seam used by host boot adapters.
    pub const fn router(&self) -> &HostRouter {
        &self.router
    }

    /// Register a command executor selected by an explicit host adapter.
    pub fn register_executor<F>(&self, executor: F)
    where
        F: Fn(crate::contract::CapabilityRequest) -> crate::contract::CapabilityResult
            + Send
            + Sync
            + 'static,
    {
        self.router.register_executor(executor);
    }

    /// Register one command name selected by an explicit host adapter.
    pub fn register_command(&self, name: impl Into<String>) {
        self.router.register_command(name);
    }

    /// Bind Rust-owned runtime settings and trusted host authorization.
    ///
    /// The binding is deliberately opt-in and can only be installed once.
    /// `false` means another endpoint is already bound.
    pub fn register_settings_endpoint(
        &self,
        runtime: Arc<KernelRuntime>,
        authorizer: Arc<dyn SettingsAuthorizer>,
    ) -> bool {
        self.router.register_settings_endpoint(runtime, authorizer)
    }

    /// Route one bounded JSONL line through protocol validation and dispatch.
    ///
    /// Protocol decode/size failures remain transport errors. Router failures
    /// are converted into a denial response plus ack so a client never stalls
    /// on a semantic routing violation.
    pub fn route_line(&self, line: &str) -> Result<RoutedLine, ProtocolHostError> {
        let request = self.protocol.decode_line(line)?;
        Ok(self.route_message(request))
    }

    /// Route an already-decoded message through the same response/ack policy.
    ///
    /// This method is useful for non-stdio adapters that have already applied
    /// their own byte framing while retaining the Rust router semantics.
    pub fn route_message(&self, request: Message) -> RoutedLine {
        let responses = match self.router.route(request.clone()) {
            Ok(responses) => responses,
            Err(error) => vec![self.router.error_envelope_for(&request, &error.to_string())],
        };
        let ack = self.router.ack_envelope(&request);
        RoutedLine {
            request,
            responses,
            ack,
        }
    }
}

impl Default for ProtocolHostRuntime {
    /// Create a bounded host runtime with all execution authorities unwired.
    fn default() -> Self {
        Self::new(ProtocolHostRuntimeConfig::default())
    }
}
