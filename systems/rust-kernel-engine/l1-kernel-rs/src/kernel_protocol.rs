//! Versioned, transport-neutral protocol boundary for the clean-break kernel.
//!
//! This module owns only retained wire semantics: v1 envelopes, TS-neutral
//! records, canonical JSON, and bounded replay cursors. HTTP, WebSocket, L2
//! dispatch, providers, and runtime session state remain adapter-owned.

use std::collections::{BTreeMap, VecDeque};
use std::fmt::{Display, Formatter};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Current envelope protocol version.
pub const PROTOCOL_VERSION: u32 = 1;
/// Current TS-neutral record schema version.
pub const RECORD_SCHEMA_VERSION: u32 = 1;
/// Default bounded replay window per session.
pub const OUTBOX_MAXLEN: usize = 1024;
/// Highest sequence value that can cross the JSON/TS boundary exactly.
pub const MAX_SAFE_SEQUENCE: u64 = 9_007_199_254_740_991;

/// Stable descriptor for the retained protocol boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProtocolDescriptor {
    /// Envelope protocol version.
    /// Wire protocol version this host speaks.
    pub protocol_version: u32,
    /// TS-neutral record schema version.
    /// Version of the typed-record schema family.
    pub record_schema_version: u32,
    /// Bounded replay window per session.
    /// Replay-window bound every session outbox must honor.
    pub outbox_maxlen: usize,
    /// Message kinds accepted by the v1 envelope.
    /// Envelope kinds admitted by this descriptor.
    pub message_kinds: Vec<String>,
}

impl ProtocolDescriptor {
    /// Return the descriptor consumed by a current Rust assembly.
    pub fn current() -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            record_schema_version: RECORD_SCHEMA_VERSION,
            outbox_maxlen: OUTBOX_MAXLEN,
            message_kinds: vec![
                "ack".to_owned(),
                "command".to_owned(),
                "control".to_owned(),
                "event".to_owned(),
                "intent".to_owned(),
                "result".to_owned(),
                "stream_chunk".to_owned(),
            ],
        }
    }

    /// Validate a host-supplied descriptor without accepting partial versions.
    ///
    /// # Errors
    ///
    /// ProtocolVersion / RecordSchemaVersion / OutboxMaxlen when values fall
    /// outside supported bounds; MessageKinds when the set is empty or
    /// contains unknown kinds.
    pub fn validate(&self) -> Result<(), ProtocolDescriptorError> {
        let expected = Self::current();
        if self.protocol_version != expected.protocol_version {
            return Err(ProtocolDescriptorError::ProtocolVersion {
                expected: expected.protocol_version,
                actual: self.protocol_version,
            });
        }
        if self.record_schema_version != expected.record_schema_version {
            return Err(ProtocolDescriptorError::RecordSchemaVersion {
                expected: expected.record_schema_version,
                actual: self.record_schema_version,
            });
        }
        if self.outbox_maxlen != expected.outbox_maxlen {
            return Err(ProtocolDescriptorError::OutboxMaxlen {
                expected: expected.outbox_maxlen,
                actual: self.outbox_maxlen,
            });
        }
        if self.message_kinds != expected.message_kinds {
            return Err(ProtocolDescriptorError::MessageKinds);
        }
        Ok(())
    }
}

/// Version mismatch at the assembly protocol boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtocolDescriptorError {
    /// The envelope version diverges.
    ProtocolVersion { expected: u32, actual: u32 },
    /// The record schema version diverges.
    RecordSchemaVersion { expected: u32, actual: u32 },
    /// The bounded replay window diverges.
    OutboxMaxlen { expected: usize, actual: usize },
    /// The accepted message-kind set or order diverges.
    MessageKinds,
}

/// Message kinds retained at the language-neutral boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MessageKind {
    Ack,
    Command,
    Control,
    Event,
    Intent,
    Result,
    StreamChunk,
}

impl MessageKind {
    /// Parse a wire message-kind label into its typed form.
    fn parse(value: &str) -> Option<Self> {
        match value {
            "ack" => Some(Self::Ack),
            "command" => Some(Self::Command),
            "control" => Some(Self::Control),
            "event" => Some(Self::Event),
            "intent" => Some(Self::Intent),
            "result" => Some(Self::Result),
            "stream_chunk" => Some(Self::StreamChunk),
            _ => None,
        }
    }
}

/// Structured protocol boundary failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProtocolError {
    /// Input was not valid JSON.
    InvalidJson(String),
    /// A message or record violated its versioned contract.
    InvalidContract(String),
    /// Canonical serialization failed for an unsupported value.
    Serialization(String),
}

impl Display for ProtocolError {
    /// Render a protocol error as a human-readable message.
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidJson(message) => write!(formatter, "invalid json: {message}"),
            Self::InvalidContract(message) => {
                write!(formatter, "invalid protocol contract: {message}")
            }
            Self::Serialization(message) => {
                write!(formatter, "protocol serialization failed: {message}")
            }
        }
    }
}

impl std::error::Error for ProtocolError {}

/// Versioned v1 envelope. The payload is deliberately JSON-shaped only at the
/// wire edge; kernel mechanisms do not consume arbitrary JSON values.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Message {
    /// Envelope version.
    /// Envelope version (currently 1).
    pub v: u32,
    /// Session correlation identifier.
    /// Session the envelope belongs to.
    pub session_id: String,
    /// Monotonic session sequence.
    /// Per-session monotonic sequence.
    pub seq: u64,
    /// Producer timestamp in seconds.
    /// Unix timestamp in seconds (fractional).
    pub ts: f64,
    /// Optional trace correlation.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    /// Optional correlation id for cross-system tracing.
    pub trace_id: Option<String>,
    /// Envelope message kind.
    /// Envelope kind driving dispatch.
    pub kind: MessageKind,
    /// Kind-specific JSON payload.
    /// Kind-specific payload with deterministic key order.
    pub payload: BTreeMap<String, Value>,
}

impl Message {
    /// Construct a v1 message with an explicit timestamp.
    ///
    /// # Errors
    ///
    /// ProtocolError when `maxlen` is zero.
    pub fn new(
        session_id: impl Into<String>,
        seq: u64,
        kind: MessageKind,
        payload: BTreeMap<String, Value>,
        trace_id: impl Into<String>,
        ts: f64,
    ) -> Self {
        Self {
            v: PROTOCOL_VERSION,
            session_id: session_id.into(),
            seq,
            ts,
            trace_id: Some(trace_id.into()),
            kind,
            payload,
        }
    }
}

/// Validate a decoded envelope and return all contract errors.
pub fn validate_message(message: &Message) -> Vec<String> {
    let mut errors = Vec::new();
    if message.v != PROTOCOL_VERSION {
        errors.push(format!("unsupported version: {}", message.v));
    }
    if message.session_id.is_empty() {
        errors.push("session_id must be a non-empty string".to_owned());
    }
    if message.seq > MAX_SAFE_SEQUENCE {
        errors.push("seq must be a non-negative integer (safe range)".to_owned());
    }
    if !message.ts.is_finite() {
        errors.push("ts must be a number".to_owned());
    }
    errors.extend(validate_payload(message.kind, &message.payload));
    errors
}

/// Host-derived authorization fields banned from inbound command/control
/// payloads (R4): approval authority is adapter-injected at the GateRequest
/// boundary and must never be wire-declared.
const HOST_DERIVED_PAYLOAD_FIELDS: [&str; 4] = [
    "approved",
    "pre_approved",
    "full_power",
    "harness_auto_approved",
];

/// Validate required payload fields per message kind, collecting errors.
fn validate_payload(kind: MessageKind, payload: &BTreeMap<String, Value>) -> Vec<String> {
    let mut errors = Vec::new();
    if matches!(kind, MessageKind::Command | MessageKind::Control)
        && HOST_DERIVED_PAYLOAD_FIELDS
            .iter()
            .any(|field| payload.contains_key(*field))
    {
        errors.push("payload carries host-derived authorization fields".to_owned());
    }
    match kind {
        MessageKind::Command => {
            if !non_empty_text(payload.get("name")) {
                errors.push("command payload requires a non-empty name".to_owned());
            }
            if let Some(args) = payload.get("args")
                && !args
                    .as_array()
                    .is_some_and(|items| items.iter().all(|item| item.as_str().is_some()))
            {
                errors.push("command payload args must be a string array".to_owned());
            }
        }
        MessageKind::Intent => {
            if !non_empty_text(payload.get("text")) {
                errors.push("intent payload requires non-empty text".to_owned());
            }
        }
        MessageKind::Result => {
            if !payload.get("success").is_some_and(Value::is_boolean) {
                errors.push("result payload requires boolean success".to_owned());
            }
        }
        MessageKind::StreamChunk => {
            if payload.get("data").and_then(Value::as_str).is_none() {
                errors.push("stream_chunk payload requires string data".to_owned());
            }
        }
        MessageKind::Control => {
            let op = payload.get("op").and_then(Value::as_str);
            if !matches!(
                op,
                Some("attach" | "detach" | "resume" | "recovery" | "ack")
            ) {
                errors.push(format!("control payload has unknown op: {op:?}"));
            }
            if let Some(target) = payload.get("session_id")
                && !non_empty_text(Some(target))
            {
                errors.push("control payload session_id must be a non-empty string".to_owned());
            }
            if let Some(last_acked) = payload.get("last_acked") {
                let valid = last_acked
                    .as_i64()
                    .is_some_and(|value| (-1..=MAX_SAFE_SEQUENCE as i64).contains(&value));
                if !valid {
                    errors.push(
                        "control payload last_acked must be an integer >= -1 (safe range)"
                            .to_owned(),
                    );
                }
            }
        }
        MessageKind::Ack => {
            if payload
                .get("ack_seq")
                .and_then(Value::as_u64)
                .is_none_or(|value| value > MAX_SAFE_SEQUENCE)
            {
                errors.push(
                    "ack payload requires a non-negative integer ack_seq (safe range)".to_owned(),
                );
            }
        }
        MessageKind::Event => {}
    }
    errors
}

/// Accept only non-empty string values.
fn non_empty_text(value: Option<&Value>) -> bool {
    value
        .and_then(Value::as_str)
        .is_some_and(|text| !text.is_empty())
}

/// Serialize a validated message with recursively sorted object keys.
///
/// # Errors
///
/// InvalidContract carrying every validation failure of `message`.
pub fn encode_message(message: &Message) -> Result<String, ProtocolError> {
    let errors = validate_message(message);
    if !errors.is_empty() {
        return Err(ProtocolError::InvalidContract(errors.join("; ")));
    }
    let value = serde_json::to_value(message)
        .map_err(|error| ProtocolError::Serialization(error.to_string()))?;
    canonical_json(&value)
}

/// Decode one JSONL envelope and fail closed on malformed input.
///
/// # Errors
///
/// InvalidContract for an empty line, malformed JSON, missing/bad
/// `v`, unknown kind, or any envelope validation failure.
pub fn decode_message(line: &str) -> Result<Message, ProtocolError> {
    if line.trim().is_empty() {
        return Err(ProtocolError::InvalidContract("empty line".to_owned()));
    }
    let raw: Value = serde_json::from_str(line)
        .map_err(|error| ProtocolError::InvalidJson(error.to_string()))?;
    let object = raw.as_object().ok_or_else(|| {
        ProtocolError::InvalidContract("envelope must be a JSON object".to_owned())
    })?;
    for field in ["v", "session_id", "seq", "ts", "kind", "payload"] {
        if !object.contains_key(field) {
            return Err(ProtocolError::InvalidContract(format!(
                "missing field: {field}"
            )));
        }
    }
    let v = object
        .get("v")
        .and_then(Value::as_u64)
        .ok_or_else(|| ProtocolError::InvalidContract("v must be an integer".to_owned()))?;
    let session_id = object
        .get("session_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ProtocolError::InvalidContract("session_id must be a string".to_owned()))?;
    let seq = object.get("seq").and_then(Value::as_u64).ok_or_else(|| {
        ProtocolError::InvalidContract("seq must be a non-negative integer".to_owned())
    })?;
    let ts = object
        .get("ts")
        .and_then(Value::as_f64)
        .ok_or_else(|| ProtocolError::InvalidContract("ts must be a number".to_owned()))?;
    let kind_name = object
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| ProtocolError::InvalidContract("kind must be a string".to_owned()))?;
    let kind = MessageKind::parse(kind_name)
        .ok_or_else(|| ProtocolError::InvalidContract(format!("unknown kind: {kind_name}")))?;
    let payload = object
        .get("payload")
        .and_then(Value::as_object)
        .ok_or_else(|| ProtocolError::InvalidContract("payload must be an object".to_owned()))?
        .iter()
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect();
    let trace_id = match object.get("trace_id") {
        None => None,
        Some(value) => Some(
            value
                .as_str()
                .ok_or_else(|| {
                    ProtocolError::InvalidContract("trace_id must be a string".to_owned())
                })?
                .to_owned(),
        ),
    };
    let message = Message {
        v: u32::try_from(v)
            .map_err(|_| ProtocolError::InvalidContract("v is out of range".to_owned()))?,
        session_id: session_id.to_owned(),
        seq,
        ts,
        trace_id,
        kind,
        payload,
    };
    let errors = validate_message(&message);
    if errors.is_empty() {
        Ok(message)
    } else {
        Err(ProtocolError::InvalidContract(errors.join("; ")))
    }
}

/// A validated TS-neutral record with forward-compatible unknown fields removed.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProtocolRecord {
    /// Stable record discriminator.
    /// Typed-record discriminator.
    pub record_type: String,
    /// Record schema version.
    /// Schema version of `data` for this record type.
    pub schema_version: u32,
    /// Known record data fields.
    /// Record payload with canonical key ordering.
    pub data: BTreeMap<String, Value>,
}

const RECORD_TYPES: [&str; 6] = [
    "decision_summary",
    "event_envelope",
    "evidence_ref",
    "session_identity",
    "session_message",
    "tool_failure",
];

/// Decode and validate one TS-neutral record envelope.
///
/// # Errors
///
/// InvalidContract for empty input, malformed JSON, unknown record
/// type, or unsupported schema version.
pub fn decode_record(line: &str) -> Result<ProtocolRecord, ProtocolError> {
    if line.trim().is_empty() {
        return Err(ProtocolError::InvalidContract(
            "record line must be non-empty text".to_owned(),
        ));
    }
    let raw: Value = serde_json::from_str(line)
        .map_err(|error| ProtocolError::InvalidJson(error.to_string()))?;
    let object = raw
        .as_object()
        .ok_or_else(|| ProtocolError::InvalidContract("record must be an object".to_owned()))?;
    let record_type = object
        .get("record_type")
        .and_then(Value::as_str)
        .ok_or_else(|| ProtocolError::InvalidContract("record_type must be a string".to_owned()))?;
    if !RECORD_TYPES.contains(&record_type) {
        return Err(ProtocolError::InvalidContract(format!(
            "unknown record_type: {record_type}"
        )));
    }
    let schema_version = object
        .get("schema_version")
        .and_then(Value::as_u64)
        .ok_or_else(|| {
            ProtocolError::InvalidContract("schema_version must be an integer".to_owned())
        })?;
    if schema_version != u64::from(RECORD_SCHEMA_VERSION) {
        return Err(ProtocolError::InvalidContract(format!(
            "unsupported record schema version: {schema_version}"
        )));
    }
    let data = object
        .get("data")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            ProtocolError::InvalidContract("record data must be an object".to_owned())
        })?;
    let known = known_record_fields(record_type);
    let mut normalized = known
        .iter()
        .filter_map(|field| {
            data.get(*field)
                .map(|value| ((*field).to_owned(), value.clone()))
        })
        .collect::<BTreeMap<_, _>>();
    insert_record_defaults(record_type, &mut normalized);
    let record = ProtocolRecord {
        record_type: record_type.to_owned(),
        schema_version: RECORD_SCHEMA_VERSION,
        data: normalized,
    };
    validate_record(&record)?;
    Ok(record)
}

/// Fill per-type defaults for missing record fields.
fn insert_record_defaults(record_type: &str, data: &mut BTreeMap<String, Value>) {
    let defaults: &[(&str, Value)] = match record_type {
        "session_identity" => &[
            ("user_id", Value::String(String::new())),
            ("role", Value::String(String::new())),
            ("cell_id", Value::String(String::new())),
            ("memory_scope", Value::String(String::new())),
        ],
        "event_envelope" => &[
            ("input_seq", Value::Null),
            ("trace_id", Value::String(String::new())),
        ],
        "session_message" => &[("trace_id", Value::String(String::new()))],
        "tool_failure" => &[("trace_id", Value::String(String::new()))],
        "decision_summary" => &[
            ("evidence_refs", Value::Array(Vec::new())),
            ("trace_id", Value::String(String::new())),
        ],
        "evidence_ref" => &[
            ("digest", Value::String(String::new())),
            ("trace_id", Value::String(String::new())),
            ("metadata", Value::Object(Map::new())),
        ],
        _ => &[],
    };
    for (field, value) in defaults {
        data.entry((*field).to_owned())
            .or_insert_with(|| value.clone());
    }
    if matches!(
        record_type,
        "event_envelope" | "session_message" | "tool_failure" | "decision_summary"
    ) {
        data.entry("ts".to_owned())
            .or_insert_with(|| Value::from(now_seconds()));
    }
}

fn now_seconds() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}

/// Return the declared field set for one record type.
fn known_record_fields(record_type: &str) -> &'static [&'static str] {
    match record_type {
        "session_identity" => &[
            "session_id",
            "terminal_id",
            "process_id",
            "user_id",
            "role",
            "cell_id",
            "memory_scope",
        ],
        "event_envelope" => &[
            "event_id",
            "session_id",
            "seq",
            "event_type",
            "payload",
            "input_seq",
            "trace_id",
            "ts",
        ],
        "session_message" => &[
            "message_id",
            "session_id",
            "input_seq",
            "role",
            "content",
            "trace_id",
            "ts",
        ],
        "tool_failure" => &[
            "failure_id",
            "session_id",
            "input_seq",
            "tool_name",
            "error_kind",
            "message",
            "retryable",
            "trace_id",
            "ts",
        ],
        "decision_summary" => &[
            "decision_id",
            "session_id",
            "input_seq",
            "summary",
            "outcome",
            "evidence_refs",
            "trace_id",
            "ts",
        ],
        "evidence_ref" => &[
            "evidence_id",
            "session_id",
            "input_seq",
            "kind",
            "locator",
            "digest",
            "trace_id",
            "metadata",
        ],
        _ => &[],
    }
}

/// Return the mandatory field set for one record type.
fn required_record_fields(record_type: &str) -> &'static [&'static str] {
    match record_type {
        "session_identity" => &["session_id", "terminal_id", "process_id"],
        "event_envelope" => &["event_id", "session_id", "seq", "event_type", "payload"],
        "session_message" => &["message_id", "session_id", "input_seq", "role", "content"],
        "tool_failure" => &[
            "failure_id",
            "session_id",
            "input_seq",
            "tool_name",
            "error_kind",
            "message",
            "retryable",
        ],
        "decision_summary" => &[
            "decision_id",
            "session_id",
            "input_seq",
            "summary",
            "outcome",
        ],
        "evidence_ref" => &["evidence_id", "session_id", "input_seq", "kind", "locator"],
        _ => &[],
    }
}

/// Validate schema version, type and required fields fail-closed.
fn validate_record(record: &ProtocolRecord) -> Result<(), ProtocolError> {
    if record.schema_version != RECORD_SCHEMA_VERSION
        || !RECORD_TYPES.contains(&record.record_type.as_str())
    {
        return Err(ProtocolError::InvalidContract(
            "unsupported record schema".to_owned(),
        ));
    }
    for field in required_record_fields(&record.record_type) {
        if !record.data.contains_key(*field) {
            return Err(ProtocolError::InvalidContract(format!(
                "missing record field: {field}"
            )));
        }
    }
    let data = &record.data;
    match record.record_type.as_str() {
        "session_identity" => {
            for field in [
                "session_id",
                "terminal_id",
                "process_id",
                "user_id",
                "role",
                "cell_id",
                "memory_scope",
            ] {
                if let Some(value) = data.get(field) {
                    require_text(value, field, true)?;
                }
            }
            for field in ["session_id", "terminal_id", "process_id"] {
                require_text(
                    data.get(field).expect("required field checked"),
                    field,
                    false,
                )?;
            }
        }
        "event_envelope" => {
            for field in ["event_id", "session_id", "event_type"] {
                require_text(
                    data.get(field).expect("required field checked"),
                    field,
                    false,
                )?;
            }
            require_u64(data.get("seq").expect("required field checked"), "seq", 0)?;
            require_object(
                data.get("payload").expect("required field checked"),
                "payload",
            )?;
            if let Some(value) = data.get("input_seq")
                && !value.is_null()
            {
                require_u64(value, "input_seq", 1)?;
            }
            optional_text(data, "trace_id")?;
            require_number(data.get("ts").expect("event timestamp required"), "ts")?;
        }
        "session_message" => {
            for field in ["message_id", "session_id", "role"] {
                require_text(
                    data.get(field).expect("required field checked"),
                    field,
                    false,
                )?;
            }
            require_text(
                data.get("content").expect("required field checked"),
                "content",
                true,
            )?;
            require_u64(
                data.get("input_seq").expect("required field checked"),
                "input_seq",
                1,
            )?;
            optional_text(data, "trace_id")?;
            require_number(data.get("ts").expect("message timestamp required"), "ts")?;
        }
        "tool_failure" => {
            for field in ["failure_id", "session_id", "tool_name", "error_kind"] {
                require_text(
                    data.get(field).expect("required field checked"),
                    field,
                    false,
                )?;
            }
            require_text(
                data.get("message").expect("required field checked"),
                "message",
                true,
            )?;
            require_u64(
                data.get("input_seq").expect("required field checked"),
                "input_seq",
                1,
            )?;
            if !data.get("retryable").is_some_and(Value::is_boolean) {
                return Err(ProtocolError::InvalidContract(
                    "retryable must be a boolean".to_owned(),
                ));
            }
            optional_text(data, "trace_id")?;
            require_number(data.get("ts").expect("failure timestamp required"), "ts")?;
        }
        "decision_summary" => {
            for field in ["decision_id", "session_id", "outcome"] {
                require_text(
                    data.get(field).expect("required field checked"),
                    field,
                    false,
                )?;
            }
            require_text(
                data.get("summary").expect("required field checked"),
                "summary",
                true,
            )?;
            require_u64(
                data.get("input_seq").expect("required field checked"),
                "input_seq",
                1,
            )?;
            if !data.get("evidence_refs").is_some_and(|value| {
                value
                    .as_array()
                    .is_some_and(|items| items.iter().all(|item| non_empty_text(Some(item))))
            }) {
                return Err(ProtocolError::InvalidContract(
                    "evidence_refs must be a string array".to_owned(),
                ));
            }
            optional_text(data, "trace_id")?;
            require_number(data.get("ts").expect("decision timestamp required"), "ts")?;
        }
        "evidence_ref" => {
            for field in ["evidence_id", "session_id", "kind", "locator"] {
                require_text(
                    data.get(field).expect("required field checked"),
                    field,
                    false,
                )?;
            }
            require_u64(
                data.get("input_seq").expect("required field checked"),
                "input_seq",
                1,
            )?;
            optional_text(data, "digest")?;
            optional_text(data, "trace_id")?;
            require_object(data.get("metadata").expect("metadata required"), "metadata")?;
        }
        _ => unreachable!("record types are checked before validation"),
    }
    Ok(())
}

/// Require a string value, optionally allowing empty text.
fn require_text(value: &Value, name: &str, allow_empty: bool) -> Result<(), ProtocolError> {
    if !value
        .as_str()
        .is_some_and(|text| allow_empty || !text.is_empty())
    {
        let qualifier = if allow_empty {
            "string"
        } else {
            "non-empty string"
        };
        return Err(ProtocolError::InvalidContract(format!(
            "{name} must be a {qualifier}"
        )));
    }
    Ok(())
}

/// Validate an optional string field when present.
fn optional_text(data: &BTreeMap<String, Value>, name: &str) -> Result<(), ProtocolError> {
    if let Some(value) = data.get(name) {
        require_text(value, name, true)?;
    }
    Ok(())
}

/// Require an integer value at or above a minimum.
fn require_u64(value: &Value, name: &str, minimum: u64) -> Result<(), ProtocolError> {
    if value.as_u64().is_none_or(|number| number < minimum) {
        return Err(ProtocolError::InvalidContract(format!(
            "{name} must be an integer >= {minimum}"
        )));
    }
    Ok(())
}

/// Require a finite numeric value.
fn require_number(value: &Value, name: &str) -> Result<(), ProtocolError> {
    if value.as_f64().is_none_or(|number| !number.is_finite()) {
        return Err(ProtocolError::InvalidContract(format!(
            "{name} must be a number"
        )));
    }
    Ok(())
}

/// Require an object value.
fn require_object(value: &Value, name: &str) -> Result<(), ProtocolError> {
    if !value.is_object() {
        return Err(ProtocolError::InvalidContract(format!(
            "{name} must be an object"
        )));
    }
    Ok(())
}

/// Serialize a validated TS-neutral record with unknown fields removed.
///
/// # Errors
///
/// InvalidContract when the record fails its schema validation.
pub fn encode_record(record: &ProtocolRecord) -> Result<String, ProtocolError> {
    let normalized = normalize_record(record)?;
    let value = serde_json::to_value(normalized)
        .map_err(|error| ProtocolError::Serialization(error.to_string()))?;
    canonical_json(&value)
}

/// Normalize a record to canonical form, validating fail-closed.
fn normalize_record(record: &ProtocolRecord) -> Result<ProtocolRecord, ProtocolError> {
    if record.schema_version != RECORD_SCHEMA_VERSION
        || !RECORD_TYPES.contains(&record.record_type.as_str())
    {
        return Err(ProtocolError::InvalidContract(
            "unsupported record schema".to_owned(),
        ));
    }
    let known = known_record_fields(&record.record_type);
    let mut data = known
        .iter()
        .filter_map(|field| {
            record
                .data
                .get(*field)
                .map(|value| ((*field).to_owned(), value.clone()))
        })
        .collect::<BTreeMap<_, _>>();
    insert_record_defaults(&record.record_type, &mut data);
    let normalized = ProtocolRecord {
        record_type: record.record_type.clone(),
        schema_version: record.schema_version,
        data,
    };
    validate_record(&normalized)?;
    Ok(normalized)
}

/// Canonicalize JSON recursively by sorting every object key.
///
/// # Errors
///
/// Serialization when `value` cannot be canonically ordered (e.g.
/// non-string object keys or non-finite floats).
pub fn canonical_json(value: &Value) -> Result<String, ProtocolError> {
    let canonical = canonical_value(value)?;
    serde_json::to_string(&canonical)
        .map_err(|error| ProtocolError::Serialization(error.to_string()))
}

/// Reduce a value to its canonical wire representation.
fn canonical_value(value: &Value) -> Result<Value, ProtocolError> {
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(value.clone()),
        Value::Number(number) => {
            if let Some(float) = number.as_f64() {
                if !float.is_finite() {
                    return Err(ProtocolError::Serialization(
                        "non-finite number cannot be encoded as JSON".to_owned(),
                    ));
                }
                if float.fract() == 0.0 && float >= (i64::MIN as f64) && float <= (u64::MAX as f64)
                {
                    if float >= 0.0 {
                        return Ok(Value::Number(serde_json::Number::from(float as u64)));
                    } else {
                        return Ok(Value::Number(serde_json::Number::from(float as i64)));
                    }
                }
            }
            Ok(value.clone())
        }
        Value::Array(items) => items
            .iter()
            .map(canonical_value)
            .collect::<Result<Vec<_>, _>>()
            .map(Value::Array),
        Value::Object(object) => {
            let mut sorted = Map::new();
            let entries = object
                .iter()
                .map(|(key, child)| Ok((key.clone(), canonical_value(child)?)))
                .collect::<Result<BTreeMap<_, _>, ProtocolError>>()?;
            for (key, child) in entries {
                sorted.insert(key, child);
            }
            Ok(Value::Object(sorted))
        }
    }
}

/// Bounded per-session replay window.
#[derive(Debug, Clone, PartialEq)]
pub struct Outbox {
    maxlen: usize,
    items: VecDeque<Message>,
    last_acked: i64,
}

impl Default for Outbox {
    /// Create an outbox at the default capacity.
    fn default() -> Self {
        Self::new(OUTBOX_MAXLEN).expect("default outbox capacity is valid")
    }
}

impl Outbox {
    /// Create a replay window with a positive capacity.
    ///
    /// # Errors
    ///
    /// ProtocolError::InvalidContract when `maxlen` is zero.
    pub fn new(maxlen: usize) -> Result<Self, ProtocolError> {
        if maxlen == 0 {
            return Err(ProtocolError::InvalidContract(
                "maxlen must be a positive integer".to_owned(),
            ));
        }
        Ok(Self {
            maxlen,
            items: VecDeque::with_capacity(maxlen),
            last_acked: -1,
        })
    }

    /// Append a message and evict the oldest item beyond the cap.
    pub fn append(&mut self, message: Message) {
        self.items.push_back(message);
        while self.items.len() > self.maxlen {
            self.items.pop_front();
        }
    }

    /// Advance the acknowledgement cursor without dropping buffered messages
    /// (non-destructive, mirroring
    /// `systems/python-reference-runtime/l2/protocol/envelope.py`: one view's
    /// ack must never erase another view's replay window).
    pub fn ack(&mut self, seq: u64) {
        self.last_acked = self.last_acked.max(i64::try_from(seq).unwrap_or(i64::MAX));
    }

    /// Return the number of messages currently retained for replay.
    pub fn len(&self) -> usize {
        self.items.len()
    }

    /// Return whether no messages are currently retained for replay.
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// Return messages with sequence strictly greater than `after_seq`
    /// (per-view replay window, mirroring
    /// `systems/python-reference-runtime/l2/protocol/envelope.py`
    /// `Outbox.unacked(after_seq)`).
    pub fn unacked_after(&self, after_seq: i64) -> Vec<Message> {
        self.items
            .iter()
            .filter(|message| i64::try_from(message.seq).unwrap_or(i64::MAX) > after_seq)
            .cloned()
            .collect()
    }

    /// Default replay window (R1): retained messages strictly above the
    /// acknowledged cursor. Retained messages at or below the cursor are
    /// never destroyed — recover them via `unacked_after(-1)`.
    pub fn unacked(&self) -> Vec<Message> {
        self.unacked_after(self.last_acked)
    }

    /// Return the highest acknowledged sequence, or -1 before acknowledgement.
    pub const fn last_acked(&self) -> i64 {
        self.last_acked
    }
}

/// Cursor for one frontend view attached to a session.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionCursor {
    /// Frontend view identifier.
    pub view_id: String,
    /// Bound session identifier, empty before attach.
    pub session_id: String,
    /// Highest acknowledged sequence.
    pub last_acked: i64,
    /// Whether the view is currently attached.
    pub attached: bool,
}

impl SessionCursor {
    /// Create a detached view cursor.
    pub fn new(view_id: impl Into<String>) -> Self {
        Self {
            view_id: view_id.into(),
            session_id: String::new(),
            last_acked: -1,
            attached: false,
        }
    }

    /// Bind the view to a session.
    pub fn attach(&mut self, session_id: impl Into<String>) {
        self.session_id = session_id.into();
        self.attached = true;
    }

    /// Detach the view while retaining its cursor.
    pub fn detach(&mut self) {
        self.attached = false;
    }
}

/// Multi-view session multiplexer mirroring
/// `systems/typescript-shell-engine/src/engine/session-manager.ts` `SessionMultiplexer`:
/// one shared event stream, per-view ack cursors, non-destructive replay
/// windows, and a shared watermark equal to the lagging view's cursor.
pub struct SessionMultiplexer {
    events: Vec<Message>,
    views: std::collections::BTreeMap<String, SessionCursor>,
}

impl Default for SessionMultiplexer {
    /// Create an empty session multiplexer.
    fn default() -> Self {
        Self::new()
    }
}

impl SessionMultiplexer {
    /// Create an empty multiplexer with no views.
    pub fn new() -> Self {
        Self {
            events: Vec::new(),
            views: std::collections::BTreeMap::new(),
        }
    }

    /// Record one outbound event in the shared stream.
    pub fn emit(&mut self, message: Message) {
        self.events.push(message);
    }

    /// Attach a view (no-op if already attached).
    pub fn attach(&mut self, view_id: impl Into<String>, session_id: impl Into<String>) {
        let view_id = view_id.into();
        self.views.entry(view_id.clone()).or_insert_with(|| {
            let mut cursor = SessionCursor::new(view_id);
            cursor.attach(session_id);
            cursor
        });
    }

    /// Detach a view, retaining its cursor for later re-attach.
    pub fn detach(&mut self, view_id: &str) {
        if let Some(view) = self.views.get_mut(view_id) {
            view.detach();
        }
    }

    /// Advance one view's ack cursor (non-destructive: other views keep
    /// their replay windows over the shared stream).
    pub fn ack(&mut self, view_id: &str, ack_seq: u64) {
        if let Some(view) = self.views.get_mut(view_id) {
            view.last_acked = view
                .last_acked
                .max(i64::try_from(ack_seq).unwrap_or(i64::MAX));
        }
    }

    /// Replay the shared stream after `after_seq` (recovery semantics).
    pub fn replay_after(&self, after_seq: i64) -> Vec<Message> {
        self.events
            .iter()
            .filter(|message| i64::try_from(message.seq).unwrap_or(i64::MAX) > after_seq)
            .cloned()
            .collect()
    }

    /// Shared watermark = the lagging attached view's last_acked (lowest of
    /// all views); -1 when no view is attached (mirrors
    /// `SessionMultiplexer.watermark`; detached views are excluded because
    /// the TS multiplexer deletes them from the view map on detach).
    pub fn watermark(&self) -> i64 {
        let mut lowest = i64::MAX;
        for view in self.views.values() {
            if view.attached {
                lowest = lowest.min(view.last_acked);
            }
        }
        if lowest == i64::MAX { -1 } else { lowest }
    }

    /// Attached view identifiers in insertion-stable order.
    pub fn view_ids(&self) -> Vec<String> {
        self.views.keys().cloned().collect()
    }
}
