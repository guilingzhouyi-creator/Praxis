//! Bounded Rust JSONL protocol gate for the clean-break kernel.
//!
//! The gate validates and canonicalizes retained v1 envelopes before a future
//! transport or runtime adapter consumes them. It does not dispatch commands,
//! execute intents, own sessions, or route AgentLoop work.

use std::fmt::{Display, Formatter};

use crate::protocol::{ProtocolError, decode_message, encode_message};

/// Default maximum UTF-8 frame size accepted by the protocol gate.
pub const DEFAULT_MAX_FRAME_BYTES: usize = 1024 * 1024;

/// Configuration for the bounded JSONL protocol gate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProtocolHostConfig {
    max_frame_bytes: usize,
}

impl Default for ProtocolHostConfig {
    fn default() -> Self {
        Self {
            max_frame_bytes: DEFAULT_MAX_FRAME_BYTES,
        }
    }
}

impl ProtocolHostConfig {
    /// Build a gate configuration with a positive frame limit.
    ///
    /// # Errors
    ///
    /// `&'static str` diagnostic when the frame cap is zero.
    pub fn new(max_frame_bytes: usize) -> Result<Self, &'static str> {
        if max_frame_bytes == 0 {
            return Err("protocol frame limit must be positive");
        }
        Ok(Self { max_frame_bytes })
    }

    /// Return the configured UTF-8 frame limit.
    pub const fn max_frame_bytes(self) -> usize {
        self.max_frame_bytes
    }
}

/// Protocol-gate failures that can be reported without panics or I/O errors.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProtocolHostError {
    /// The input frame exceeds the configured bound.
    FrameTooLarge {
        actual_bytes: usize,
        max_bytes: usize,
    },
    /// The retained protocol decoder rejected the frame.
    Protocol(ProtocolError),
}

impl Display for ProtocolHostError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FrameTooLarge {
                actual_bytes,
                max_bytes,
            } => write!(
                formatter,
                "protocol frame is too large: {actual_bytes} bytes exceeds {max_bytes}"
            ),
            Self::Protocol(error) => Display::fmt(error, formatter),
        }
    }
}

impl std::error::Error for ProtocolHostError {}

impl From<ProtocolError> for ProtocolHostError {
    fn from(error: ProtocolError) -> Self {
        Self::Protocol(error)
    }
}

/// Stateless JSONL gate that preserves the retained protocol boundary.
#[derive(Debug, Clone, Copy)]
pub struct ProtocolHost {
    config: ProtocolHostConfig,
}

impl Default for ProtocolHost {
    fn default() -> Self {
        Self::new(ProtocolHostConfig::default())
    }
}

impl ProtocolHost {
    /// Create a protocol gate with explicit bounds.
    pub const fn new(config: ProtocolHostConfig) -> Self {
        Self { config }
    }

    /// Return the immutable gate configuration.
    pub const fn config(&self) -> ProtocolHostConfig {
        self.config
    }

    /// Decode, validate, and canonicalize one JSONL envelope.
    ///
    /// # Errors
    ///
    /// ProtocolError for oversized frames and any envelope validation failure (R7).
    pub fn canonicalize_line(&self, line: &str) -> Result<String, ProtocolHostError> {
        let actual_bytes = line.len();
        if actual_bytes > self.config.max_frame_bytes {
            return Err(ProtocolHostError::FrameTooLarge {
                actual_bytes,
                max_bytes: self.config.max_frame_bytes,
            });
        }
        let message = decode_message(line)?;
        Ok(encode_message(&message)?)
    }
}
