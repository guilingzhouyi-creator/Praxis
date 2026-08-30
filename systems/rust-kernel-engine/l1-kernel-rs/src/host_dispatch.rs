//! Kind-by-kind host dispatch boundary for the Rust protocol host.
//!
//! The dispatch layer is the wire boundary of the future Rust protocol host.
//! It routes a decoded v1 envelope KIND-BY-KIND while keeping the L1/L2
//! authority rules (see docs/architecture/l2-shell-engine.md rulings):
//! R4 — host-derived authorization fields never travel on the wire and are
//! rejected before routing; ring/danger MAY be declared as gate inputs but
//! confer no approval. R7 — gate denials, unregistered commands, and
//! unwired executors produce `result{success:false}` envelopes (recorded in
//! the session outbox); only protocol-level violations (banned fields,
//! outbound-only kinds, buffer overflow) fail at the transport layer.
//! L1-side operations resolve through the capability gate after gatechain
//! ring/danger adjudication; intent and L3A traffic passes through to an
//! opaque L3 upstream pipe; ack and control messages resolve through the
//! session and outbox registries.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use serde_json::Value;

use crate::audit::AuditLog;
use crate::capability::CapabilityAuthority;
use crate::contract::{CapabilityRequest, CapabilityResult, JsonObject, JsonValue};
use crate::gatechain::{GateChain, GatePolicy, GateRequest};
use crate::host_authorization::HostAuthorizationContext;
use crate::outbox_registry::OutboxRegistry;
use crate::protocol::{MAX_SAFE_SEQUENCE, Message, MessageKind, ProtocolError, SessionCursor};
use crate::runtime::KernelRuntime;
use crate::session_identity::SessionIdentity;
use crate::session_lifecycle::{SessionLifecycle, SessionRegistry};
use crate::settings_protocol::{
    RuntimeSettingsEndpoint, SETTINGS_GET_COMMAND, SETTINGS_SET_COMMAND, SettingsAuthorizer,
    SettingsEndpointError,
};

/// Default bounded pending-intent queue capacity when no upstream is wired.
pub const DEFAULT_INTENT_BUFFER_CAP: usize = 1024;
/// Capability name under which system-class commands are adjudicated.
pub const SYSTEM_TOOL: &str = "__system";
/// Ring at or above which a system command requires explicit risk approval.
pub const SYSTEM_RING_RISK: u8 = 3;
/// System-class command names resolved through the gatechain.
pub const SYSTEM_COMMANDS: [&str; 5] = ["__system", "status", "health", "ps", "fs"];
/// Host-derived authorization fields banned from inbound payloads (R4):
/// approval authority is adapter-injected, never wire-declared.
pub const HOST_DERIVED_FIELDS: [&str; 4] = [
    "approved",
    "pre_approved",
    "full_power",
    "harness_auto_approved",
];
/// Default terminal identifier for a control attach without a binding.
pub const DEFAULT_TERMINAL_ID: &str = "terminal";
/// Default process identifier for a control attach without a binding.
pub const DEFAULT_PROCESS_ID: &str = "process";

/// Opaque passthrough to an L3 authority pipe.
pub trait L3Upstream: Send + Sync {
    /// Forward one intent envelope to the L3 authority.
    fn forward(&self, message: Message) -> Result<(), ProtocolError>;
}

/// Data-only configuration for the host dispatch router.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RouterConfig {
    intent_buffer_cap: usize,
    require_host_context: bool,
}

impl RouterConfig {
    /// Build a configuration with a positive pending-intent buffer capacity.
    ///
    /// # Errors
    ///
    /// Returns `Err` when `intent_buffer_cap` is zero — an intent buffer
    /// that cannot hold anything would silently drop upstream traffic.
    pub fn new(intent_buffer_cap: usize) -> Result<Self, &'static str> {
        if intent_buffer_cap == 0 {
            return Err("intent buffer capacity must be positive");
        }
        Ok(Self {
            intent_buffer_cap,
            require_host_context: false,
        })
    }

    /// Return the configured pending-intent buffer capacity.
    pub const fn intent_buffer_cap(self) -> usize {
        self.intent_buffer_cap
    }

    /// Return whether authority-bearing dispatch requires host context.
    pub const fn requires_host_context(self) -> bool {
        self.require_host_context
    }

    /// Require a trusted host authorization context for dispatch.
    pub const fn with_required_host_context(mut self) -> Self {
        self.require_host_context = true;
        self
    }
}

impl Default for RouterConfig {
    /// Apply the default router configuration.
    fn default() -> Self {
        Self {
            intent_buffer_cap: DEFAULT_INTENT_BUFFER_CAP,
            require_host_context: false,
        }
    }
}

/// Kind-by-kind dispatch router for the Rust protocol host.
pub struct HostRouter {
    config: RouterConfig,
    authority: Arc<CapabilityAuthority>,
    gatechain: Arc<GateChain>,
    audit: Arc<AuditLog>,
    sessions: Mutex<SessionRegistry>,
    outboxes: Mutex<OutboxRegistry>,
    registered: Mutex<BTreeSet<String>>,
    pending_intents: Mutex<VecDeque<Message>>,
    upstream: Mutex<Option<Arc<dyn L3Upstream>>>,
    settings_endpoint: Mutex<Option<Arc<RuntimeSettingsEndpoint>>>,
    authorization_contexts: Mutex<BTreeMap<String, HostAuthorizationContext>>,
    /// Per-session response sequence counters (R2): monotonic per session,
    /// never process-global.
    response_seqs: Mutex<BTreeMap<String, u64>>,
}

impl HostRouter {
    /// Build a router with an explicit configuration.
    ///
    /// The capability authority starts UNWIRED: every command is answered
    /// with a fail-closed denial envelope until a boot adapter registers an
    /// executor via [`Self::register_executor`] (R7).
    pub fn new(config: RouterConfig) -> Self {
        let audit = Arc::new(AuditLog::new());
        let authority = Arc::new(CapabilityAuthority::with_audit(Arc::clone(&audit)));
        let gatechain = GateChain::with_policy(GatePolicy {
            escalation_danger: SYSTEM_RING_RISK,
            ..GatePolicy::default()
        });
        gatechain.register_tools([SYSTEM_TOOL]);
        let registered = BTreeSet::from_iter(SYSTEM_COMMANDS.iter().map(|name| (*name).to_owned()));
        Self {
            config,
            authority,
            gatechain: Arc::new(gatechain),
            audit,
            sessions: Mutex::new(SessionRegistry::new()),
            outboxes: Mutex::new(OutboxRegistry::new()),
            registered: Mutex::new(registered),
            pending_intents: Mutex::new(VecDeque::new()),
            upstream: Mutex::new(None),
            settings_endpoint: Mutex::new(None),
            authorization_contexts: Mutex::new(BTreeMap::new()),
            response_seqs: Mutex::new(BTreeMap::new()),
        }
    }

    /// Return the immutable router configuration.
    pub const fn config(&self) -> RouterConfig {
        self.config
    }

    /// Return whether a capability executor is currently wired.
    pub fn has_executor(&self) -> bool {
        self.authority.has_executor()
    }

    /// Route one decoded envelope by kind, returning any outbound responses.
    ///
    /// # Errors
    ///
    /// Returns [`ProtocolError::InvalidContract`] when host-derived
    /// authorization fields appear inbound (R4), a control payload violates
    /// its contract (unknown resume target, missing detach `view_id`), or the
    /// kind is outbound-only (`event` / `result` / `stream_chunk`, R7).
    /// Gate denials are deliberately NOT errors: they travel back as
    /// `result{success:false}` envelopes recorded in the session outbox.
    pub fn route(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        match message.kind {
            MessageKind::Command | MessageKind::Control => reject_host_derived(&message.payload)?,
            _ => {}
        }
        match message.kind {
            MessageKind::Command => {
                let name = message
                    .payload
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if matches!(name, SETTINGS_GET_COMMAND | SETTINGS_SET_COMMAND) {
                    self.dispatch_settings(message)
                } else if SYSTEM_COMMANDS.contains(&name) {
                    self.dispatch_system(message)
                } else {
                    self.dispatch_command(message)
                }
            }
            MessageKind::Control => self.route_control(&message),
            MessageKind::Ack => self.route_ack(message),
            MessageKind::Intent => self.route_intent(message),
            MessageKind::Event => Err(outbound_only("event")),
            MessageKind::Result => Err(outbound_only("result")),
            MessageKind::StreamChunk => Err(outbound_only("stream_chunk")),
        }
    }

    /// Dispatch one system-class command through gatechain ring adjudication.
    ///
    /// # Errors
    ///
    /// Only protocol-contract violations return `Err` (R4/R7); ring/danger
    /// denials resolve to `result{success:false}` envelopes plus an audit row.
    pub fn dispatch_system(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let name = message
            .payload
            .get("name")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .ok_or_else(|| {
                ProtocolError::InvalidContract(
                    "command payload requires a non-empty name".to_owned(),
                )
            })?;
        let wire_ring = system_ring(&message.payload);
        let (agent_id, context) = self.authority_principal(&message.session_id)?;
        let ring = context.as_ref().map_or(wire_ring, |value| value.ring);
        let danger = system_danger(&message.payload, ring);
        let mut gate_request = GateRequest::new(SYSTEM_TOOL, agent_id.clone());
        gate_request.interactive = true;
        gate_request.interactive_ring = ring;
        gate_request.danger_override = Some(danger);
        // R4: approval authority is adapter-injected only — a boot adapter
        // may set gate_request.pre_approved/full_power from identity or
        // posture state; it can never originate from this wire payload.
        gate_request.timestamp = Some(message.ts);
        let verdict = self.gatechain.check(&gate_request);
        if !verdict.allowed {
            let reason = format!(
                "system command {name} blocked by gatechain ({})",
                verdict.decision.as_str()
            );
            self.audit_dispatch("system", &agent_id, &name, ring, false, &reason);
            let response = self.denial_envelope(&message, &reason);
            self.lock_outboxes()
                .append(&message.session_id, response.clone());
            return Ok(vec![response]);
        }
        self.audit_dispatch("system", &agent_id, &name, ring, true, "");
        let request = CapabilityRequest {
            agent_id,
            name: name.clone(),
            args: command_args(&message.payload),
            domain: String::new(),
            nature: String::new(),
            interactive: true,
        };
        let result = self.authority.invoke(request);
        let response = self.response_envelope(&message, &result);
        self.lock_outboxes()
            .append(&message.session_id, response.clone());
        Ok(vec![response])
    }

    /// Dispatch one command envelope through the capability gate.
    ///
    /// # Errors
    ///
    /// Only protocol-contract violations return `Err`; capability/gate
    /// denials resolve to `result{success:false}` envelopes plus audit rows.
    pub fn dispatch_command(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let name = message
            .payload
            .get("name")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .ok_or_else(|| {
                ProtocolError::InvalidContract(
                    "command payload requires a non-empty name".to_owned(),
                )
            })?;
        if SYSTEM_COMMANDS.contains(&name.as_str()) {
            let (agent_id, _context) = self.authority_principal(&message.session_id)?;
            let reason = "system command requires ring adjudication".to_owned();
            self.audit_dispatch("command", &agent_id, &name, 0, false, &reason);
            let response =
                self.denial_envelope(&message, &format!("system command {name} {reason}"));
            self.lock_outboxes()
                .append(&message.session_id, response.clone());
            return Ok(vec![response]);
        }
        let (agent_id, _context) = self.authority_principal(&message.session_id)?;
        {
            let registered = self.lock_registered();
            if !registered.contains(&name) {
                self.audit_dispatch(
                    "command",
                    &agent_id,
                    &name,
                    0,
                    false,
                    "unregistered command",
                );
                let response =
                    self.denial_envelope(&message, &format!("unregistered command: {name}"));
                self.lock_outboxes()
                    .append(&message.session_id, response.clone());
                return Ok(vec![response]);
            }
        }
        let request = CapabilityRequest {
            agent_id: agent_id.clone(),
            name: name.clone(),
            args: command_args(&message.payload),
            domain: String::new(),
            nature: String::new(),
            interactive: true,
        };
        let result = self.authority.invoke(request);
        self.audit_dispatch(
            "command",
            &agent_id,
            &name,
            0,
            result.success,
            &result.error,
        );
        let response = self.response_envelope(&message, &result);
        self.lock_outboxes()
            .append(&message.session_id, response.clone());
        Ok(vec![response])
    }

    /// Register an additional command name for capability dispatch.
    pub fn register_command(&self, name: impl Into<String>) {
        self.lock_registered().insert(name.into());
    }

    /// Replace the wired capability executor; boot adapters are the caller.
    pub fn register_executor<F>(&self, executor: F)
    where
        F: Fn(CapabilityRequest) -> CapabilityResult + Send + Sync + 'static,
    {
        self.authority.register_executor(executor);
    }

    /// Register an already type-erased capability executor from a bootstrapper.
    pub fn register_executor_arc(&self, executor: crate::capability::CapabilityExecutor) {
        self.authority.register_executor_arc(executor);
    }

    /// Registered command names in stable sorted order.
    pub fn registered_commands(&self) -> Vec<String> {
        self.lock_registered().iter().cloned().collect()
    }

    /// Session identifiers currently held by the session registry.
    pub fn sessions(&self) -> Vec<String> {
        self.lock_sessions().list_ids()
    }

    /// Lifecycle state for one session, if registered.
    pub fn session_state(&self, session_id: &str) -> Option<SessionLifecycle> {
        self.lock_sessions()
            .get(session_id)
            .map(|record| record.state())
    }

    /// Retained view cursor for one session/view pair, if attached.
    pub fn view_cursor(&self, session_id: &str, view_id: &str) -> Option<SessionCursor> {
        self.lock_outboxes().cursor(session_id, view_id).cloned()
    }

    /// Number of intents currently buffered without an upstream pipe.
    pub fn pending_intent_count(&self) -> usize {
        self.lock_pending().len()
    }

    /// Buffered intents awaiting an L3 upstream pipe, in arrival order.
    pub fn pending_intents(&self) -> Vec<Message> {
        self.lock_pending().iter().cloned().collect()
    }

    /// Wire or detach the L3 upstream pipe for intent passthrough.
    pub fn set_upstream(&self, upstream: Option<Arc<dyn L3Upstream>>) {
        *self.lock_upstream() = upstream;
    }

    /// Bind trusted host authorization evidence to one session.
    ///
    /// The binding is explicit and one-shot per session. `Ok(false)` reports
    /// that a context was already bound; callers must not silently replace it.
    pub fn bind_authorization_context(
        &self,
        context: HostAuthorizationContext,
    ) -> Result<bool, &'static str> {
        context.validate()?;
        let mut contexts = self
            .authorization_contexts
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if contexts.contains_key(&context.session_id) {
            return Ok(false);
        }
        contexts.insert(context.session_id.clone(), context);
        Ok(true)
    }

    /// Remove a trusted host context during controlled shutdown or test reset.
    pub fn clear_authorization_context(&self, session_id: &str) {
        self.authorization_contexts
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .remove(session_id);
    }

    /// Return a defensive copy of a trusted context, when bound.
    pub fn authorization_context(&self, session_id: &str) -> Option<HostAuthorizationContext> {
        self.authorization_contexts
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .get(session_id)
            .cloned()
    }

    /// Attach a Rust-owned runtime settings endpoint.
    ///
    /// The host must inject both the runtime and an authorization policy. The
    /// router never accepts approval fields from a command payload and the
    /// endpoint remains absent until this explicit wiring call succeeds.
    pub fn register_settings_endpoint(
        &self,
        runtime: Arc<KernelRuntime>,
        authorizer: Arc<dyn SettingsAuthorizer>,
    ) -> bool {
        let mut endpoint = self
            .settings_endpoint
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if endpoint.is_some() {
            return false;
        }
        *endpoint = Some(Arc::new(RuntimeSettingsEndpoint::new(runtime, authorizer)));
        true
    }

    /// Remove the settings endpoint during controlled shutdown or test reset.
    pub fn clear_settings_endpoint(&self) {
        *self
            .settings_endpoint
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = None;
    }

    /// Return the dispatch audit trail for inspection or journal wiring.
    pub fn audit(&self) -> Arc<AuditLog> {
        Arc::clone(&self.audit)
    }

    /// Return audit row count and journal error count.
    pub fn audit_stats(&self) -> (usize, u64) {
        self.audit.stats()
    }

    /// Route a control message to its session and operation handler.
    fn route_control(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let op = message
            .payload
            .get("op")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let agent_id = self.agent_id_for(&message.session_id);
        let result = match op.as_str() {
            "attach" => self.control_attach(message),
            "detach" => self.control_detach(message),
            "resume" => self.control_resume(message),
            "recovery" => self.control_recovery(message),
            "ack" => self.apply_ack(message),
            _ => Err(ProtocolError::InvalidContract(format!(
                "control payload has unknown op: {op}"
            ))),
        };
        self.audit_outcome(&result, "control", &agent_id, &op, 0);
        result
    }

    /// Handle the attach control operation.
    fn control_attach(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let session_id = target_session(message);
        let terminal_id = message
            .payload
            .get("terminal_id")
            .and_then(Value::as_str)
            .unwrap_or(DEFAULT_TERMINAL_ID);
        let process_id = message
            .payload
            .get("process_id")
            .and_then(Value::as_str)
            .unwrap_or(DEFAULT_PROCESS_ID);
        let view_id = message.payload.get("view_id").and_then(Value::as_str);
        let identity = SessionIdentity::new(session_id.clone(), terminal_id, process_id)?;
        let mut sessions = self.lock_sessions();
        if sessions.get(&session_id).is_none() {
            sessions.create(identity)?;
        }
        if let Some(view_id) = view_id {
            if let Some(record) = sessions.get_mut(&session_id) {
                record.attach_view(view_id);
            }
            self.lock_outboxes().attach(&session_id, view_id);
        }
        let identity = sessions
            .get(&session_id)
            .map(|record| record.identity.clone())
            .ok_or_else(|| {
                ProtocolError::InvalidContract(format!("attach: unknown session {session_id}"))
            })?;
        drop(sessions);
        let data = serde_json::to_value(identity).map_err(|error| {
            ProtocolError::Serialization(format!("session identity encoding failed: {error}"))
        })?;
        let event = self.envelope(
            message,
            MessageKind::Event,
            BTreeMap::from([
                (
                    "name".to_owned(),
                    Value::String("session.attached".to_owned()),
                ),
                ("data".to_owned(), data),
            ]),
        );
        self.lock_outboxes()
            .append(&message.session_id, event.clone());
        Ok(vec![event])
    }

    /// Handle the detach control operation.
    fn control_detach(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let session_id = target_session(message);
        let view_id = message
            .payload
            .get("view_id")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                ProtocolError::InvalidContract("control detach requires view_id".to_owned())
            })?;
        if let Some(record) = self.lock_sessions().get_mut(&session_id) {
            record.detach_view(view_id);
        }
        self.lock_outboxes().detach(&session_id, view_id);
        Ok(Vec::new())
    }

    /// Handle the resume control operation.
    fn control_resume(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let session_id = target_session(message);
        let mut sessions = self.lock_sessions();
        let record = sessions.get_mut(&session_id).ok_or_else(|| {
            ProtocolError::InvalidContract(format!("resume: unknown session {session_id}"))
        })?;
        record.transition(SessionLifecycle::Running)?;
        Ok(Vec::new())
    }

    /// Handle the recovery control operation.
    fn control_recovery(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let session_id = target_session(message);
        let after = message
            .payload
            .get("last_acked")
            .and_then(Value::as_i64)
            .unwrap_or(-1);
        let replay = self
            .lock_outboxes()
            .get_or_create(&session_id)
            .unacked_after(after);
        let replay_value = serde_json::to_value(replay).map_err(|error| {
            ProtocolError::Serialization(format!("session replay encoding failed: {error}"))
        })?;
        let event = self.envelope_for_session(
            message,
            &session_id,
            MessageKind::Event,
            BTreeMap::from([
                (
                    "name".to_owned(),
                    Value::String("session.recovered".to_owned()),
                ),
                (
                    "data".to_owned(),
                    Value::Object(serde_json::Map::from_iter([
                        ("session_id".to_owned(), Value::String(session_id.clone())),
                        ("replay".to_owned(), replay_value),
                    ])),
                ),
            ]),
        );
        self.lock_outboxes().append(&session_id, event.clone());
        Ok(vec![event])
    }

    /// Apply an ack to the session's outbox.
    fn apply_ack(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let session_id = target_session(message);
        let ack_seq = message
            .payload
            .get("ack_seq")
            .and_then(Value::as_u64)
            .ok_or_else(|| {
                ProtocolError::InvalidContract(
                    "ack payload requires a non-negative integer ack_seq".to_owned(),
                )
            })?;
        let view_id = message.payload.get("view_id").and_then(Value::as_str);
        let mut outboxes = self.lock_outboxes();
        if let Some(view_id) = view_id {
            outboxes.ack_view(&session_id, view_id, ack_seq);
        } else {
            outboxes.ack(&session_id, ack_seq);
        }
        Ok(Vec::new())
    }

    /// Route an ack message to its owning agent.
    fn route_ack(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let agent_id = self.agent_id_for(&message.session_id);
        let result = self.apply_ack(&message);
        self.audit_outcome(&result, "ack", &agent_id, "ack", 0);
        result
    }

    /// Route an intent message to its owning agent.
    fn route_intent(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let agent_id = self.agent_id_for(&message.session_id);
        let result = self.forward_intent(message);
        self.audit_outcome(&result, "intent", &agent_id, "intent", 0);
        result
    }

    /// Forward an intent to the upstream L3 authority.
    fn forward_intent(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let upstream = self.lock_upstream().clone();
        match upstream {
            Some(pipe) => catch_unwind(AssertUnwindSafe(|| pipe.forward(message)))
                .map_err(|_| {
                    ProtocolError::InvalidContract("L3 upstream callback panicked".to_owned())
                })?
                .map(|_| Vec::new()),
            None => {
                let mut pending = self.lock_pending();
                if pending.len() >= self.config.intent_buffer_cap {
                    return Err(ProtocolError::InvalidContract(
                        "intent buffer overflow (fail-closed)".to_owned(),
                    ));
                }
                pending.push_back(message);
                Ok(Vec::new())
            }
        }
    }

    /// Dispatch the settings commands through the host-injected endpoint.
    ///
    /// Settings argument, authorization, and runtime failures are returned as
    /// result envelopes so clients do not stall on a semantic denial. The
    /// endpoint itself is never auto-created and therefore remains fail-closed
    /// until a host explicitly wires it.
    fn dispatch_settings(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let name = message
            .payload
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let args = command_arg_strings(&message.payload)?;
        let (agent_id, context) = self.authority_principal(&message.session_id)?;
        let endpoint = self
            .settings_endpoint
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone();
        let result = match endpoint {
            None => Err(SettingsEndpointError::Runtime(
                "settings endpoint is not wired".to_owned(),
            )),
            Some(endpoint) => match name.as_str() {
                SETTINGS_GET_COMMAND => match context.as_ref() {
                    Some(context) => endpoint.get_with_context(context, &args),
                    None => endpoint.get(&agent_id, &args),
                },
                SETTINGS_SET_COMMAND => match context.as_ref() {
                    Some(context) => endpoint.set_with_context(context, &args),
                    None => endpoint.set(&agent_id, &args),
                },
                _ => Err(SettingsEndpointError::InvalidArguments(format!(
                    "unsupported settings command: {name}"
                ))),
            },
        };
        match result {
            Ok(reply) => {
                let payload = serde_json::to_value(reply)
                    .map_err(|error| ProtocolError::Serialization(error.to_string()))?
                    .as_object()
                    .cloned()
                    .ok_or_else(|| {
                        ProtocolError::Serialization(
                            "settings reply must serialize to an object".to_owned(),
                        )
                    })?
                    .into_iter()
                    .collect::<BTreeMap<_, _>>();
                let mut payload = payload;
                payload.insert("success".to_owned(), Value::Bool(true));
                self.audit_dispatch("settings", &agent_id, &name, 0, true, "");
                let response = self.envelope(&message, MessageKind::Result, payload);
                self.lock_outboxes()
                    .append(&message.session_id, response.clone());
                Ok(vec![response])
            }
            Err(error) => {
                let reason = error.to_string();
                self.audit_dispatch("settings", &agent_id, &name, 0, false, &reason);
                let response = self.denial_envelope(&message, &reason);
                self.lock_outboxes()
                    .append(&message.session_id, response.clone());
                Ok(vec![response])
            }
        }
    }

    fn lock_sessions(&self) -> MutexGuard<'_, SessionRegistry> {
        self.sessions.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_outboxes(&self) -> MutexGuard<'_, OutboxRegistry> {
        self.outboxes.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_pending(&self) -> MutexGuard<'_, VecDeque<Message>> {
        self.pending_intents
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_registered(&self) -> MutexGuard<'_, BTreeSet<String>> {
        self.registered
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_upstream(&self) -> MutexGuard<'_, Option<Arc<dyn L3Upstream>>> {
        self.upstream.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn authority_principal(
        &self,
        session_id: &str,
    ) -> Result<(String, Option<HostAuthorizationContext>), ProtocolError> {
        let context = self.authorization_context(session_id);
        if self.config.require_host_context && context.is_none() {
            return Err(ProtocolError::InvalidContract(format!(
                "trusted host authorization context is not bound for session {session_id}"
            )));
        }
        if self.config.require_host_context
            && context
                .as_ref()
                .is_some_and(|value| !value.identity_verified && value.ring >= 2)
        {
            return Err(ProtocolError::InvalidContract(
                "verified host identity is required for authorization ring >= 2".to_owned(),
            ));
        }
        let principal = context.as_ref().map_or_else(
            || self.agent_id_for(session_id),
            |value| value.principal.clone(),
        );
        Ok((principal, context))
    }

    /// Resolve the owning agent id for a session.
    fn agent_id_for(&self, session_id: &str) -> String {
        if self.lock_sessions().get(session_id).is_some() {
            session_id.to_owned()
        } else {
            "system".to_owned()
        }
    }

    /// Record a dispatch intent in the audit log.
    fn audit_dispatch(
        &self,
        kind: &str,
        agent_id: &str,
        command: &str,
        ring: u8,
        allowed: bool,
        reason: &str,
    ) {
        let decision = if allowed { "allowed" } else { "denied" };
        self.audit.record_fields(
            format!("dispatch.{kind}"),
            agent_id,
            allowed,
            reason,
            format!("command={command} ring={ring} decision={decision}"),
        );
    }

    /// Record a dispatch outcome in the audit log.
    fn audit_outcome(
        &self,
        result: &Result<Vec<Message>, ProtocolError>,
        kind: &str,
        agent_id: &str,
        command: &str,
        ring: u8,
    ) {
        match result {
            Ok(_) => self.audit_dispatch(kind, agent_id, command, ring, true, ""),
            Err(error) => {
                self.audit_dispatch(kind, agent_id, command, ring, false, &error.to_string())
            }
        }
    }

    /// Build the response envelope for a capability result.
    fn response_envelope(&self, request: &Message, result: &CapabilityResult) -> Message {
        let output = if result.success {
            match result.data.get("echo") {
                Some(JsonValue::String(text)) => text.clone(),
                _ => result.capability.clone(),
            }
        } else {
            result.error.clone()
        };
        let payload = BTreeMap::from([
            ("success".to_owned(), Value::Bool(result.success)),
            ("output".to_owned(), Value::String(output)),
        ]);
        self.envelope(request, MessageKind::Result, payload)
    }

    /// Fail-closed denial envelope (R7): rejections travel as structured
    /// results so clients never wait on a transport-level error.
    fn denial_envelope(&self, request: &Message, error: &str) -> Message {
        let payload = BTreeMap::from([
            ("success".to_owned(), Value::Bool(false)),
            ("error".to_owned(), Value::String(error.to_owned())),
        ]);
        self.envelope(request, MessageKind::Result, payload)
    }

    /// Transport-level acknowledgement for one accepted input, mirroring
    /// `ProtocolHost.handle` in
    /// `systems/python-reference-runtime/l2/protocol/host.py`: every decoded
    /// inbound envelope receives an ack carrying its inbound seq.
    pub fn ack_envelope(&self, request: &Message) -> Message {
        let payload = BTreeMap::from([("ack_seq".to_owned(), Value::from(request.seq))]);
        self.envelope(request, MessageKind::Ack, payload)
    }

    /// Structured denial envelope for a protocol-level routing violation,
    /// bound to the offending envelope's session (used by stdio adapters
    /// that must answer even when [`Self::route`] returns Err).
    pub fn error_envelope_for(&self, request: &Message, error: &str) -> Message {
        self.denial_envelope(request, error)
    }

    /// Build a result envelope for a session.
    fn envelope(
        &self,
        request: &Message,
        kind: MessageKind,
        payload: BTreeMap<String, Value>,
    ) -> Message {
        self.envelope_for_session(request, &request.session_id, kind, payload)
    }

    /// Build a session-targeted result envelope.
    fn envelope_for_session(
        &self,
        request: &Message,
        session_id: &str,
        kind: MessageKind,
        payload: BTreeMap<String, Value>,
    ) -> Message {
        Message::new(
            session_id,
            self.next_response_seq(session_id),
            kind,
            payload,
            request.trace_id.clone().unwrap_or_default(),
            request.ts,
        )
    }

    /// Next outbound sequence for one session (R2): per-session monotonic.
    fn next_response_seq(&self, session_id: &str) -> u64 {
        let mut seqs = self.lock_response_seqs();
        let counter = seqs.entry(session_id.to_owned()).or_insert(0);
        *counter = if *counter >= MAX_SAFE_SEQUENCE {
            1
        } else {
            counter.saturating_add(1)
        };
        *counter
    }

    fn lock_response_seqs(&self) -> MutexGuard<'_, BTreeMap<String, u64>> {
        self.response_seqs
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

fn command_args(payload: &BTreeMap<String, Value>) -> JsonObject {
    let mut args = JsonObject::new();
    if let Some(items) = payload.get("args").and_then(Value::as_array) {
        args.insert(
            "args".to_owned(),
            JsonValue::Array(
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(|text| JsonValue::String(text.to_owned()))
                    .collect(),
            ),
        );
    }
    args
}

fn command_arg_strings(payload: &BTreeMap<String, Value>) -> Result<Vec<String>, ProtocolError> {
    let Some(args) = payload.get("args") else {
        return Ok(Vec::new());
    };
    let Some(args) = args.as_array() else {
        return Err(ProtocolError::InvalidContract(
            "command payload args must be a string array".to_owned(),
        ));
    };
    args.iter()
        .map(|value| {
            value.as_str().map(str::to_owned).ok_or_else(|| {
                ProtocolError::InvalidContract(
                    "command payload args must be a string array".to_owned(),
                )
            })
        })
        .collect()
}

fn system_ring(payload: &BTreeMap<String, Value>) -> u8 {
    payload
        .get("ring")
        .and_then(Value::as_u64)
        .map_or(1, |ring| u8::try_from(ring).unwrap_or(u8::MAX))
        .max(1)
}

fn system_danger(payload: &BTreeMap<String, Value>, ring: u8) -> u8 {
    payload
        .get("danger")
        .and_then(Value::as_u64)
        .map_or(ring, |danger| u8::try_from(danger).unwrap_or(u8::MAX))
        .max(1)
}

fn target_session(message: &Message) -> String {
    message
        .payload
        .get("session_id")
        .and_then(Value::as_str)
        .unwrap_or(&message.session_id)
        .to_owned()
}

fn outbound_only(kind: &str) -> ProtocolError {
    ProtocolError::InvalidContract(format!("outbound-only message kind: {kind}"))
}

/// R4: reject inbound payloads carrying host-derived authorization fields.
/// Approval authority is injected by identity/posture adapters at the
/// GateRequest boundary; a wire declaration must never confer it.
fn reject_host_derived(payload: &BTreeMap<String, Value>) -> Result<(), ProtocolError> {
    for field in HOST_DERIVED_FIELDS {
        if payload.contains_key(field) {
            return Err(ProtocolError::InvalidContract(format!(
                "payload carries host-derived authorization field: {field}"
            )));
        }
    }
    Ok(())
}
