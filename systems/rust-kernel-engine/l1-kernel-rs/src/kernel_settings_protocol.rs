//! Host-injected protocol adapter for Rust-owned runtime settings.
//!
//! The adapter keeps settings reads and writes behind an explicit authorization
//! seam. Wire arguments carry only the setting key/value; approval state is
//! supplied by the host adapter and never trusted from JSON. The runtime owns
//! the settings snapshot and persistence while this module owns argument
//! validation and the response-shaped value contract.

use std::collections::BTreeMap;
use std::fmt::{Display, Formatter};
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::host_authorization::HostAuthorizationContext;
use crate::runtime::{KernelRuntime, RuntimeError};
use crate::settings::{SettingsSnapshot, SettingsSource};

/// Protocol command used to read one or all Rust-owned settings.
pub const SETTINGS_GET_COMMAND: &str = "settings_get";
/// Protocol command used to mutate one Rust-owned setting.
pub const SETTINGS_SET_COMMAND: &str = "settings_set";
/// Maximum UTF-8 bytes accepted for one JSON-encoded setting value.
pub const MAX_SETTINGS_VALUE_BYTES: usize = 1 << 20;

/// Operation being authorized at the settings boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SettingsOperation {
    /// Read one or all settings.
    Read,
    /// Mutate one setting.
    Write,
}

/// Host-injected authorization contract for settings operations.
///
/// The host may derive the decision from trusted identity, ring, engineering
/// debug state, or GateChain context. The wire payload is deliberately absent
/// from this trait so a client cannot claim approval.
pub trait SettingsAuthorizer: Send + Sync {
    /// Authorize one operation for one boundary principal and optional key.
    fn authorize(
        &self,
        agent_id: &str,
        operation: SettingsOperation,
        key: Option<&str>,
    ) -> Result<(), String>;

    /// Authorize one operation using trusted host context.
    ///
    /// Existing adapter implementations remain valid because the default
    /// bridge delegates only the validated principal string. Context-aware
    /// hosts may override this method to enforce session, ring, identity, or
    /// engineering-debug policy without trusting wire fields.
    fn authorize_context(
        &self,
        context: &HostAuthorizationContext,
        operation: SettingsOperation,
        key: Option<&str>,
    ) -> Result<(), String> {
        self.authorize(&context.principal, operation, key)
    }
}

/// Small explicit authorizer useful for adapters and isolated tests.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StaticSettingsAuthorizer {
    allow_reads: bool,
    allow_writes: bool,
}

impl StaticSettingsAuthorizer {
    /// Deny both reads and writes.
    pub const fn deny() -> Self {
        Self {
            allow_reads: false,
            allow_writes: false,
        }
    }

    /// Allow reads while keeping writes denied.
    pub const fn read_only() -> Self {
        Self {
            allow_reads: true,
            allow_writes: false,
        }
    }

    /// Allow both reads and writes.
    pub const fn read_write() -> Self {
        Self {
            allow_reads: true,
            allow_writes: true,
        }
    }
}

impl Default for StaticSettingsAuthorizer {
    /// Keep the settings boundary fail-closed unless a host opts in.
    fn default() -> Self {
        Self::deny()
    }
}

impl SettingsAuthorizer for StaticSettingsAuthorizer {
    /// Apply the explicit static read/write decision.
    fn authorize(
        &self,
        _agent_id: &str,
        operation: SettingsOperation,
        _key: Option<&str>,
    ) -> Result<(), String> {
        let allowed = match operation {
            SettingsOperation::Read => self.allow_reads,
            SettingsOperation::Write => self.allow_writes,
        };
        if allowed {
            Ok(())
        } else {
            Err(format!(
                "settings {:?} denied by host authorization",
                operation
            ))
        }
    }
}

/// Structured settings endpoint rejection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SettingsEndpointError {
    /// The command argument count or shape is invalid.
    InvalidArguments(String),
    /// The host authorization seam denied the operation.
    Unauthorized(String),
    /// The JSON value exceeds the bounded protocol value size.
    ValueTooLarge {
        actual_bytes: usize,
        max_bytes: usize,
    },
    /// The runtime settings facade rejected the operation.
    Runtime(String),
}

impl Display for SettingsEndpointError {
    /// Render a stable endpoint error for a result envelope and audit row.
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidArguments(message) => {
                write!(formatter, "invalid settings arguments: {message}")
            }
            Self::Unauthorized(message) => {
                write!(formatter, "settings authorization denied: {message}")
            }
            Self::ValueTooLarge {
                actual_bytes,
                max_bytes,
            } => write!(
                formatter,
                "settings value is too large: {actual_bytes} bytes exceeds {max_bytes}"
            ),
            Self::Runtime(message) => write!(formatter, "settings runtime failed: {message}"),
        }
    }
}

impl std::error::Error for SettingsEndpointError {}

impl From<RuntimeError> for SettingsEndpointError {
    fn from(error: RuntimeError) -> Self {
        Self::Runtime(format!("{error:?}"))
    }
}

/// Result payload emitted by the settings protocol endpoint.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SettingsReply {
    /// Operation that produced this reply.
    pub operation: String,
    /// Key selected by a read or changed by a write, if one was supplied.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub key: Option<String>,
    /// Value selected by a keyed read, if the key exists.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<Value>,
    /// Monotonic Rust settings revision.
    pub revision: u64,
    /// Settings source selected by the runtime.
    pub source: SettingsSource,
    /// Defensive settings values selected by this operation.
    pub values: BTreeMap<String, Value>,
}

/// Explicit bridge from one Rust runtime to protocol settings commands.
pub struct RuntimeSettingsEndpoint {
    runtime: Arc<KernelRuntime>,
    authorizer: Arc<dyn SettingsAuthorizer>,
}

impl RuntimeSettingsEndpoint {
    /// Build an endpoint with host-owned runtime and authorization inputs.
    pub fn new(runtime: Arc<KernelRuntime>, authorizer: Arc<dyn SettingsAuthorizer>) -> Self {
        Self {
            runtime,
            authorizer,
        }
    }

    /// Return the runtime shared by this endpoint.
    pub fn runtime(&self) -> Arc<KernelRuntime> {
        Arc::clone(&self.runtime)
    }

    /// Dispatch a `settings_get` command argument vector.
    pub fn get(
        &self,
        agent_id: &str,
        args: &[String],
    ) -> Result<SettingsReply, SettingsEndpointError> {
        self.get_authorized(agent_id, None, args)
    }

    /// Dispatch a read with a trusted host context.
    pub fn get_with_context(
        &self,
        context: &HostAuthorizationContext,
        args: &[String],
    ) -> Result<SettingsReply, SettingsEndpointError> {
        self.get_authorized(&context.principal, Some(context), args)
    }

    fn get_authorized(
        &self,
        agent_id: &str,
        context: Option<&HostAuthorizationContext>,
        args: &[String],
    ) -> Result<SettingsReply, SettingsEndpointError> {
        if args.len() > 1 {
            return Err(SettingsEndpointError::InvalidArguments(
                "settings_get accepts zero or one key".to_owned(),
            ));
        }
        let key = args.first().filter(|value| !value.is_empty()).cloned();
        if let Some(key) = key.as_deref() {
            self.authorize(agent_id, context, SettingsOperation::Read, Some(key))?;
        } else {
            self.authorize(agent_id, context, SettingsOperation::Read, None)?;
        }
        let snapshot = self.runtime.settings_snapshot()?;
        let value = key
            .as_deref()
            .and_then(|setting_key| snapshot.values.get(setting_key).cloned());
        let values = match key.as_deref() {
            Some(setting_key) => snapshot
                .values
                .get(setting_key)
                .cloned()
                .map(|value| BTreeMap::from([(setting_key.to_owned(), value)]))
                .unwrap_or_default(),
            None => snapshot.values.clone(),
        };
        Ok(reply(SETTINGS_GET_COMMAND, key, value, snapshot, values))
    }

    /// Dispatch a `settings_set` command argument vector.
    pub fn set(
        &self,
        agent_id: &str,
        args: &[String],
    ) -> Result<SettingsReply, SettingsEndpointError> {
        self.set_authorized(agent_id, None, args)
    }

    /// Dispatch a write with a trusted host context.
    pub fn set_with_context(
        &self,
        context: &HostAuthorizationContext,
        args: &[String],
    ) -> Result<SettingsReply, SettingsEndpointError> {
        self.set_authorized(&context.principal, Some(context), args)
    }

    fn set_authorized(
        &self,
        agent_id: &str,
        context: Option<&HostAuthorizationContext>,
        args: &[String],
    ) -> Result<SettingsReply, SettingsEndpointError> {
        if args.len() != 2 {
            return Err(SettingsEndpointError::InvalidArguments(
                "settings_set requires <key> <json-value>".to_owned(),
            ));
        }
        let key = args[0].as_str();
        if key.trim().is_empty() {
            return Err(SettingsEndpointError::InvalidArguments(
                "settings_set key must be non-empty".to_owned(),
            ));
        }
        self.authorize(agent_id, context, SettingsOperation::Write, Some(key))?;
        if args[1].len() > MAX_SETTINGS_VALUE_BYTES {
            return Err(SettingsEndpointError::ValueTooLarge {
                actual_bytes: args[1].len(),
                max_bytes: MAX_SETTINGS_VALUE_BYTES,
            });
        }
        let value = serde_json::from_str::<Value>(&args[1]).map_err(|error| {
            SettingsEndpointError::InvalidArguments(format!("json value is invalid: {error}"))
        })?;
        let snapshot = self
            .runtime
            .set_runtime_setting(key.to_owned(), value.clone())?;
        let values = BTreeMap::from([(key.to_owned(), value.clone())]);
        Ok(reply(
            SETTINGS_SET_COMMAND,
            Some(key.to_owned()),
            Some(value),
            snapshot,
            values,
        ))
    }

    fn authorize(
        &self,
        agent_id: &str,
        context: Option<&HostAuthorizationContext>,
        operation: SettingsOperation,
        key: Option<&str>,
    ) -> Result<(), SettingsEndpointError> {
        let result = match context {
            Some(context) => self.authorizer.authorize_context(context, operation, key),
            None => self.authorizer.authorize(agent_id, operation, key),
        };
        result.map_err(SettingsEndpointError::Unauthorized)
    }
}

fn reply(
    operation: &str,
    key: Option<String>,
    value: Option<Value>,
    snapshot: SettingsSnapshot,
    values: BTreeMap<String, Value>,
) -> SettingsReply {
    SettingsReply {
        operation: operation.to_owned(),
        key,
        value,
        revision: snapshot.revision,
        source: snapshot.source,
        values,
    }
}
