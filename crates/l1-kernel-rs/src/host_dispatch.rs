//! Kind-by-kind host dispatch boundary for the Rust protocol host.
//!
//! The dispatch layer is the wire boundary of the future Rust protocol host.
//! It routes a decoded v1 envelope KIND-BY-KIND while keeping the L1/L2
//! authority rules: L1-side operations (commands and `$`-style system,
//! status, health, process/fs operations) resolve through the capability
//! gate after gatechain ring/danger adjudication; intent and L3A traffic
//! passes through to an opaque L3 upstream pipe; ack and control messages
//! resolve through the session and outbox registries. Event, Result, and
//! StreamChunk envelopes are outbound-only and rejected at the inbound
//! boundary.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use serde_json::Value;

use crate::capability::CapabilityAuthority;
use crate::contract::{CapabilityRequest, CapabilityResult, JsonObject, JsonValue};
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
    sessions: Mutex<SessionRegistry>,
    outboxes: Mutex<OutboxRegistry>,
    registered: Mutex<BTreeSet<String>>,
    pending_intents: Mutex<VecDeque<Message>>,
    response_seq: AtomicU64,
}

impl HostRouter {
    /// Build a router with an explicit configuration.
    pub fn new(config: RouterConfig) -> Self {
        let authority = Arc::new(CapabilityAuthority::new());
        authority.register_executor(|request| CapabilityResult {
            success: true,
            error: String::new(),
            capability: request.name.clone(),
            data: JsonObject::from([(
                "echo".to_owned(),
                JsonValue::String(format!("echo:{}", request.name)),
            )]),
        });
        let registered = BTreeSet::from_iter(SYSTEM_COMMANDS.iter().map(|name| (*name).to_owned()));
        Self {
            config,
            authority,
            sessions: Mutex::new(SessionRegistry::new()),
            outboxes: Mutex::new(OutboxRegistry::new()),
            registered: Mutex::new(registered),
            pending_intents: Mutex::new(VecDeque::new()),
            response_seq: AtomicU64::new(0),
        }
    }

    /// Route one decoded envelope by kind, returning any outbound responses.
    pub fn route(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        match message.kind {
            MessageKind::Command => self.dispatch_command(message),
            MessageKind::Control => self.route_control(&message),
            MessageKind::Ack => self.apply_ack(&message),
            MessageKind::Intent => self.route_intent(message),
            MessageKind::Event => Err(outbound_only("event")),
            MessageKind::Result => Err(outbound_only("result")),
            MessageKind::StreamChunk => Err(outbound_only("stream_chunk")),
        }
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
        {
            let registered = self.lock_registered();
            if !registered.contains(&name) {
                return Err(ProtocolError::InvalidContract(format!(
                    "unregistered command: {name}"
                )));
            }
        }
        let agent_id = self.agent_id_for(&message.session_id);
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
        self.lock_sessions().get(session_id).map(|record| record.state())
    }

    /// Retained view cursor for one session/view pair, if attached.
    pub fn view_cursor(&self, session_id: &str, view_id: &str) -> Option<SessionCursor> {
        self.lock_outboxes().cursor(session_id, view_id).cloned()
    }

    /// Number of intents currently buffered without an upstream pipe.
    pub fn pending_intent_count(&self) -> usize {
        self.lock_pending().len()
    }

    fn route_control(&self, message: &Message) -> Result<Vec<Message>, ProtocolError> {
        let op = message
            .payload
            .get("op")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        match op.as_str() {
            "attach" => self.control_attach(message),
            "detach" => self.control_detach(message),
            "resume" => self.control_resume(message),
            "recovery" => self.control_recovery(message),
            "ack" => self.apply_ack(message),
            _ => Err(ProtocolError::InvalidContract(format!(
                "control payload has unknown op: {op}"
            ))),
        }
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

    fn route_intent(&self, message: Message) -> Result<Vec<Message>, ProtocolError> {
        let mut pending = self.lock_pending();
        if pending.len() >= self.config.intent_buffer_cap {
            return Err(ProtocolError::InvalidContract(
                "intent buffer overflow (fail-closed)".to_owned(),
            ));
        }
        pending.push_back(message);
        Ok(Vec::new())
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

    fn agent_id_for(&self, session_id: &str) -> String {
        if self.lock_sessions().get(session_id).is_some() {
            session_id.to_owned()
        } else {
            "system".to_owned()
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
        Message::new(
            request.session_id.clone(),
            self.next_response_seq(),
            MessageKind::Result,
            payload,
            request.trace_id.clone().unwrap_or_default(),
            request.ts,
        )
    }

    fn next_response_seq(&self) -> u64 {
        self.response_seq.fetch_add(1, Ordering::SeqCst).saturating_add(1)
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