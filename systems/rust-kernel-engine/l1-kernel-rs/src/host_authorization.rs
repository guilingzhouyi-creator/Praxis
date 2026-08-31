//! Trusted host authorization context for the Rust protocol boundary.
//!
//! The context is adapter-owned evidence, not wire data. A host must validate
//! and bind it before a strict [`HostBootstrap`](crate::host_bootstrap::HostBootstrap)
//! can expose command or settings routing. The kernel keeps this value small,
//! explicit, and bounded so a session string can never smuggle authority.

use serde::{Deserialize, Serialize};

/// Maximum UTF-8 bytes retained for one host identity field.
pub const MAX_HOST_ID_BYTES: usize = 128;
/// Maximum supported authorization ring.
pub const MAX_AUTHORIZATION_RING: u8 = 8;

/// Stable host identity and posture evidence supplied outside the wire.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HostAuthorizationContext {
    /// Trusted principal used for capability and settings audit correlation.
    pub principal: String,
    /// Session to which this context is bound.
    pub session_id: String,
    /// Authorization ring selected by the host policy.
    pub ring: u8,
    /// Whether the host completed identity verification.
    pub identity_verified: bool,
    /// Whether engineering-debug mode is enabled by the host.
    pub engineering_debug: bool,
}

impl HostAuthorizationContext {
    /// Construct and validate a host context.
    ///
    /// # Errors
    ///
    /// Returns a stable message when an identity is empty, over-sized, or
    /// contains a NUL byte, or when the ring is outside the supported range.
    pub fn new(
        principal: impl Into<String>,
        session_id: impl Into<String>,
        ring: u8,
        identity_verified: bool,
        engineering_debug: bool,
    ) -> Result<Self, &'static str> {
        let context = Self {
            principal: principal.into(),
            session_id: session_id.into(),
            ring,
            identity_verified,
            engineering_debug,
        };
        context.validate()?;
        Ok(context)
    }

    /// Validate the context before it crosses into a host router.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.principal.trim().is_empty() || self.session_id.trim().is_empty() {
            return Err("host principal and session id must be non-empty");
        }
        for value in [&self.principal, &self.session_id] {
            if value.len() > MAX_HOST_ID_BYTES {
                return Err("host identity field exceeds the configured bound");
            }
            if value.contains('\0') {
                return Err("host identity field must not contain NUL");
            }
        }
        if self.ring == 0 || self.ring > MAX_AUTHORIZATION_RING {
            return Err("host authorization ring is outside the supported range");
        }
        Ok(())
    }
}
