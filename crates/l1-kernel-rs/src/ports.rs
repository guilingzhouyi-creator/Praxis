//! Language-neutral port values and declarative adapter registration.
//!
//! This candidate owns only the value contract and deterministic registry
//! metadata. Port implementations, OS I/O, callbacks, and upper-layer
//! services remain behind a future Rust adapter boundary.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::contract::JsonObject;

/// Stable mechanism port categories exposed by the kernel boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PortKind {
    /// One-shot or bounded process execution.
    Process,
    /// Text/state storage adapter.
    Storage,
    /// Mutual exclusion adapter.
    Lock,
    /// Scheduler submission and polling seam.
    Scheduler,
    /// Bounded message channel.
    Channel,
    /// Event publication/subscription seam.
    EventBus,
    /// Worker execution adapter.
    Worker,
    /// Transport lifecycle and byte delivery seam.
    Transport,
    /// Side-channel metric sink.
    Observability,
    /// Append-only evidence sink.
    Evidence,
    /// Dependency graph planner.
    DependencyGraph,
    /// Trace scope provider.
    Trace,
    /// Privacy-preserving input activity provider.
    InputActivity,
}

/// Declarative metadata for one adapter registered at the Rust boundary.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PortDescriptor {
    /// Stable lookup name.
    pub name: String,
    /// Mechanism category.
    pub kind: PortKind,
    /// Contract version implemented by this adapter.
    pub contract_version: u32,
    /// Optional primitive metadata for host diagnostics.
    #[serde(default)]
    pub metadata: JsonObject,
}

impl PortDescriptor {
    /// Construct a descriptor with empty metadata.
    pub fn new(name: impl Into<String>, kind: PortKind, contract_version: u32) -> Self {
        Self {
            name: name.into(),
            kind,
            contract_version,
            metadata: JsonObject::new(),
        }
    }

    /// Add or replace one primitive metadata value.
    pub fn with_metadata(
        mut self,
        key: impl Into<String>,
        value: crate::contract::JsonValue,
    ) -> Self {
        self.metadata.insert(key.into(), value);
        self
    }
}

/// Errors raised by the declarative port registry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PortRegistryError {
    /// Port names must be non-empty and unique.
    InvalidName,
    /// An existing descriptor cannot be replaced implicitly.
    Duplicate { name: String },
    /// A locked registry rejects ordinary writes.
    Locked,
    /// A lookup did not find a descriptor.
    NotFound { name: String },
    /// A descriptor has no supported contract version.
    InvalidVersion,
}

/// Deterministic metadata registry for future adapter wiring.
#[derive(Debug, Default)]
pub struct PortRegistry {
    order: Vec<String>,
    descriptors: BTreeMap<String, PortDescriptor>,
    locked: bool,
}

impl PortRegistry {
    /// Create an empty mutable registry.
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a descriptor, optionally replacing an existing declaration.
    pub fn register(
        &mut self,
        descriptor: PortDescriptor,
        allow_replace: bool,
    ) -> Result<(), PortRegistryError> {
        validate_descriptor(&descriptor)?;
        if self.locked && !allow_replace {
            return Err(PortRegistryError::Locked);
        }
        if self.descriptors.contains_key(&descriptor.name) && !allow_replace {
            return Err(PortRegistryError::Duplicate {
                name: descriptor.name,
            });
        }
        if !self.descriptors.contains_key(&descriptor.name) {
            self.order.push(descriptor.name.clone());
        }
        self.descriptors.insert(descriptor.name.clone(), descriptor);
        Ok(())
    }

    /// Lock ordinary registration before runtime adapter wiring.
    pub fn lock(&mut self) {
        self.locked = true;
    }

    /// Return whether ordinary registration is locked.
    pub const fn is_locked(&self) -> bool {
        self.locked
    }

    /// Return one descriptor by stable name.
    pub fn get(&self, name: &str) -> Result<PortDescriptor, PortRegistryError> {
        self.descriptors
            .get(name)
            .cloned()
            .ok_or_else(|| PortRegistryError::NotFound {
                name: name.to_owned(),
            })
    }

    /// Return descriptors in registration order.
    pub fn snapshot(&self) -> Vec<PortDescriptor> {
        self.order
            .iter()
            .filter_map(|name| self.descriptors.get(name).cloned())
            .collect()
    }

    /// Return whether a name is registered.
    pub fn contains(&self, name: &str) -> bool {
        self.descriptors.contains_key(name)
    }

    /// Return the number of registered descriptors.
    pub fn len(&self) -> usize {
        self.descriptors.len()
    }

    /// Return whether no descriptors are registered.
    pub fn is_empty(&self) -> bool {
        self.descriptors.is_empty()
    }
}

/// Plain result crossing a port boundary without exception leakage.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PortResult {
    /// Whether the adapter accepted or completed the operation.
    pub success: bool,
    /// Stable error text for a failed operation.
    pub error: String,
    /// Additional JSON-compatible result data.
    pub data: JsonObject,
}

impl PortResult {
    /// Build a successful result.
    pub fn ok() -> Self {
        Self {
            success: true,
            error: String::new(),
            data: JsonObject::new(),
        }
    }

    /// Build a successful result carrying one value.
    pub fn ok_with(key: impl Into<String>, value: crate::contract::JsonValue) -> Self {
        let mut result = Self::ok();
        result.data.insert(key.into(), value);
        result
    }

    /// Build a failed result.
    pub fn fail(error: impl Into<String>) -> Self {
        Self {
            success: false,
            error: error.into(),
            data: JsonObject::new(),
        }
    }
}

/// Adapter-neutral endpoint value.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Endpoint {
    /// Opaque address string interpreted by the transport adapter.
    pub address: String,
    /// Transport hint, such as `tcp` or `udp`.
    #[serde(default = "default_transport_hint")]
    pub hint: String,
}

impl Endpoint {
    /// Build an endpoint with an explicit transport hint.
    pub fn new(address: impl Into<String>, hint: impl Into<String>) -> Self {
        Self {
            address: address.into(),
            hint: hint.into(),
        }
    }

    /// Validate the value without opening a socket.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.address.trim().is_empty() {
            return Err("endpoint address is required");
        }
        if self.hint.trim().is_empty() {
            return Err("endpoint hint is required");
        }
        Ok(())
    }
}

/// Message value buffered by a transport or channel adapter.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Message {
    /// Message type.
    #[serde(rename = "type")]
    pub message_type: String,
    /// Sending principal or endpoint label.
    #[serde(default)]
    pub source: String,
    /// Target principal or endpoint label.
    #[serde(default)]
    pub target: String,
    /// JSON-compatible payload.
    pub payload: crate::contract::JsonValue,
    /// Producer-supplied timestamp.
    #[serde(default)]
    pub timestamp: f64,
    /// Locale tag retained at the boundary.
    #[serde(default = "default_locale")]
    pub locale: String,
    /// Additional primitive headers.
    #[serde(default)]
    pub headers: JsonObject,
}

impl Message {
    /// Validate type and timestamp without interpreting payload policy.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.message_type.trim().is_empty() {
            return Err("message type is required");
        }
        if !self.timestamp.is_finite() {
            return Err("message timestamp must be finite");
        }
        Ok(())
    }
}

/// Privacy-preserving aggregate input activity state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum InputActivityState {
    /// Recent keyboard or pointer activity was observed.
    Active,
    /// No activity was observed within the adapter window.
    Idle,
    /// The provider is unavailable or has not started.
    Unknown,
}

/// Aggregate input activity snapshot with no raw key/pointer content.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputActivitySnapshot {
    /// Aggregate state.
    pub state: InputActivityState,
    /// Whether keyboard activity was observed.
    pub keyboard_active: bool,
    /// Whether pointer activity was observed.
    pub pointer_active: bool,
    /// Caller-supplied time of the last activity.
    pub last_activity_at: f64,
    /// Caller-supplied idle duration.
    pub idle_seconds: f64,
    /// Provider label.
    pub source: String,
    /// Permission status label.
    pub permission: String,
}

impl InputActivitySnapshot {
    /// Validate numeric fields without collecting input contents.
    pub fn validate(&self) -> Result<(), &'static str> {
        if !self.last_activity_at.is_finite() || !self.idle_seconds.is_finite() {
            return Err("activity timestamps must be finite");
        }
        if self.idle_seconds < 0.0 {
            return Err("idle seconds must be non-negative");
        }
        Ok(())
    }
}

fn validate_descriptor(descriptor: &PortDescriptor) -> Result<(), PortRegistryError> {
    if descriptor.name.trim().is_empty() {
        return Err(PortRegistryError::InvalidName);
    }
    if descriptor.name.chars().any(char::is_whitespace) {
        return Err(PortRegistryError::InvalidName);
    }
    if descriptor.contract_version == 0 {
        return Err(PortRegistryError::InvalidVersion);
    }
    Ok(())
}

fn default_transport_hint() -> String {
    "tcp".to_owned()
}

fn default_locale() -> String {
    "en".to_owned()
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{
        Endpoint, InputActivitySnapshot, InputActivityState, Message, PortDescriptor, PortKind,
        PortRegistry, PortRegistryError, PortResult,
    };

    #[test]
    fn registry_is_deterministic_and_locked() {
        let mut registry = PortRegistry::new();
        registry
            .register(PortDescriptor::new("process", PortKind::Process, 1), false)
            .expect("process");
        registry
            .register(PortDescriptor::new("storage", PortKind::Storage, 1), false)
            .expect("storage");
        assert!(matches!(
            registry.register(PortDescriptor::new("process", PortKind::Process, 1), false),
            Err(PortRegistryError::Duplicate { .. })
        ));
        registry.lock();
        assert!(matches!(
            registry.register(PortDescriptor::new("lock", PortKind::Lock, 1), false),
            Err(PortRegistryError::Locked)
        ));
        registry
            .register(
                PortDescriptor::new("process", PortKind::Process, 2)
                    .with_metadata("native", crate::contract::JsonValue::Bool(true)),
                true,
            )
            .expect("explicit replacement");
        assert_eq!(registry.snapshot()[0].contract_version, 2);
    }

    #[test]
    fn values_validate_without_side_effects() {
        assert!(Endpoint::new("127.0.0.1:9000", "tcp").validate().is_ok());
        assert!(Endpoint::new("", "tcp").validate().is_err());
        let message = Message {
            message_type: "message".to_owned(),
            source: "a".to_owned(),
            target: "b".to_owned(),
            payload: crate::contract::JsonValue::Object(Default::default()),
            timestamp: 1.0,
            locale: "en".to_owned(),
            headers: Default::default(),
        };
        assert!(message.validate().is_ok());
        assert!(
            InputActivitySnapshot {
                state: InputActivityState::Idle,
                keyboard_active: false,
                pointer_active: false,
                last_activity_at: 1.0,
                idle_seconds: 2.0,
                source: "noop".to_owned(),
                permission: "unavailable".to_owned(),
            }
            .validate()
            .is_ok()
        );
        assert_eq!(
            PortResult::ok_with("ready", crate::contract::JsonValue::Bool(true)).data["ready"],
            crate::contract::JsonValue::Bool(true)
        );
        assert_eq!(
            serde_json::to_value(PortResult::fail("no adapter")).expect("json"),
            json!({"success": false, "error": "no adapter", "data": {}})
        );
    }
}
