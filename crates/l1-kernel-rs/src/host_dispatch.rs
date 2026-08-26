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
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use serde_json::Value;

use crate::audit::AuditLog;
use crate::capability::CapabilityAuthority;
use crate::contract::{CapabilityRequest, CapabilityResult, JsonObject, JsonValue};
use crate::gatechain::{GateChain, GatePolicy, GateRequest};
use crate::outbox_registry::OutboxRegistry;
use crate::protocol::{Message, MessageKind, ProtocolError, SessionCursor};
use crate::session_identity::SessionIdentity;
use crate::session_lifecycle::{SessionLifecycle, SessionRegistry};

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
}

impl RouterConfig {
    /// Build a configuration with a positive pending-intent buffer capacity.
    pub fn new(intent_buffer_cap: usize) -> Result<Self, &'static str> {
        if intent_buffer_cap == 0 {
            return Err("intent buffer capacity must be positive");
        }
        Ok(Self { intent_buffer_cap })
    }

    /// Return the configured pending-intent buffer capacity.
    pub const fn intent_buffer_cap(self) -> usize {
        self.intent_buffer_cap
    }
}

impl Default for RouterConfig {
    fn default() -> Self {
        Self {
            intent_buffer_cap: DEFAULT_INTENT_BUFFER_CAP,
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
            response_seqs: Mutex::new(BTreeMap::new()),
        }
    }

    /// Route one decoded envelope by kind, returning any outbound responses.
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
                if SYSTEM_COMMANDS.contains(&name) {
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
        let ring = system_ring(&message.payload);
        let danger = system_danger(&message.payload, ring);
        let agent_id = self.agent_id_for(&message.session_id);
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
            let agent_id = self.agent_id_for(&message.session_id);
            let reason = "system command requires ring adjudication".to_owned();
            self.audit_dispatch("command", &agent_id, &name, 0, false, &reason);
            let response =
                self.denial_envelope(&message, &format!("system command {name} {reason}"));
            self.lock_outboxes()
                .append(&message.session_id, response.clone());
            return Ok(vec![response]);
        }
        let agent_id = self.agent_id_for(&message.session_id);
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

    /// Return the dispatch audit trail for inspection or journal wiring.
    pub fn audit(&self) -> Arc<AuditLog> {
        Arc::clone(&self.audit)
    }

    /// Return audit row count and journal error count.
    pub fn audit_stats(&self) -> (usize, u64) {
        self.audit.stats()
    }

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
        Ok(Vec::new())
    }

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

    fn control_resume(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let session_id = target_session(message);
        let mut sessions = self.lock_sessions();
        let record = sessions.get_mut(&session_id).ok_or_else(|| {
            ProtocolError::InvalidContract(format!("resume: unknown session {session_id}"))
        })?;
        record.transition(SessionLifecycle::Running)?;
        Ok(Vec::new())
    }

    fn control_recovery(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let session_id = target_session(message);
        let after = message
            .payload
            .get("last_acked")
            .and_then(Value::as_i64)
            .unwrap_or(-1);
        let mut outboxes = self.lock_outboxes();
        Ok(outboxes.get_or_create(&session_id).unacked_after(after))
    }

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

    fn route_ack(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let agent_id = self.agent_id_for(&message.session_id);
        let result = self.apply_ack(&message);
        self.audit_outcome(&result, "ack", &agent_id, "ack", 0);
        result
    }

    fn route_intent(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let agent_id = self.agent_id_for(&message.session_id);
        let result = self.forward_intent(message);
        self.audit_outcome(&result, "intent", &agent_id, "intent", 0);
        result
    }

    fn forward_intent(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let upstream = self.lock_upstream().clone();
        match upstream {
            Some(pipe) => pipe.forward(message).map(|_| Vec::new()),
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

    fn agent_id_for(&self, session_id: &str) -> String {
        if self.lock_sessions().get(session_id).is_some() {
            session_id.to_owned()
        } else {
            "system".to_owned()
        }
    }

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
    /// `ProtocolHost.handle` in `src/l2/protocol/host.py`: every decoded
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

    fn envelope(
        &self,
        request: &Message,
        kind: MessageKind,
        payload: BTreeMap<String, Value>,
    ) -> Message {
        Message::new(
            request.session_id.clone(),
            self.next_response_seq(&request.session_id),
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
        *counter = counter.saturating_add(1);
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
