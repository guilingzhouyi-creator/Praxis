//! Explicit terminal-to-AgentLoop composition for the Rust L1 boundary.
//!
//! The terminal mailbox remains an opaque byte transport and the AgentLoop
//! remains the authoritative session admission path. This bridge only checks
//! the already-established loop/session/terminal correlation, delegates byte
//! decoding to the caller, and submits decoded inputs through the existing
//! execution bridge. It does not inspect host terminals, create PTYs, choose
//! encodings, execute providers, or grant production runtime authority.

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::agent_loop::{AgentLoopError, AgentLoopSpec, AgentLoopState};
use crate::agent_loop_execution::{
    AgentLoopAction, AgentLoopExecutionBridge, AgentLoopExecutionError, AgentLoopExecutionRequest,
    AgentLoopExecutionTask,
};
use crate::runtime::KernelRuntime;
use crate::session::{Session, SessionInput};
use crate::terminal::{
    TERMINAL_MAX_FRAME_BYTES, TerminalError, TerminalFrame, TerminalSnapshot, TerminalState,
    TerminalStream,
};

/// Version of the terminal-to-AgentLoop composition contract.
pub const AGENT_LOOP_TERMINAL_CONTRACT_VERSION: u32 = 1;
/// Maximum number of terminal frames admitted by one grouped bridge call.
pub const AGENT_LOOP_TERMINAL_MAX_BATCH: usize = 256;

/// Stable correlation evidence returned by the bridge preflight.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentLoopTerminalBinding {
    /// Composition contract version.
    pub contract_version: u32,
    /// Immutable logical AgentLoop identity.
    pub spec: AgentLoopSpec,
    /// Session identity validated against the loop and terminal.
    pub session_id: String,
    /// Terminal lifecycle observed during preflight.
    pub terminal_state: TerminalState,
}

/// Fail-closed errors at the terminal-to-AgentLoop composition seam.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AgentLoopTerminalError {
    /// The logical AgentLoop rejected the identity or lifecycle operation.
    AgentLoop(AgentLoopError),
    /// The terminal book rejected lookup or mailbox access.
    Terminal(TerminalError),
    /// The runtime could not reserve or enqueue execution work.
    Execution(AgentLoopExecutionError),
    /// The loop/session/terminal correlation is inconsistent.
    InvalidBinding(String),
    /// A terminal frame is not a valid input frame for this bridge.
    InvalidFrame(String),
    /// The injected decoder rejected the frame or panicked.
    Decoder(String),
    /// A grouped submission exceeded the explicit fixed-work bound.
    BatchTooLarge { size: usize, limit: usize },
    /// The number of caller-owned actions does not match the frame count.
    ActionCountMismatch { frames: usize, actions: usize },
}

impl From<AgentLoopError> for AgentLoopTerminalError {
    fn from(error: AgentLoopError) -> Self {
        Self::AgentLoop(error)
    }
}

impl From<TerminalError> for AgentLoopTerminalError {
    fn from(error: TerminalError) -> Self {
        Self::Terminal(error)
    }
}

impl From<AgentLoopExecutionError> for AgentLoopTerminalError {
    fn from(error: AgentLoopExecutionError) -> Self {
        Self::Execution(error)
    }
}

/// Caller-owned decoder from opaque terminal bytes to a session input.
pub type TerminalInputDecoder =
    dyn Fn(&TerminalFrame) -> Result<SessionInput, String> + Send + Sync + 'static;

/// Explicit composition bridge for a running terminal-backed AgentLoop.
pub struct AgentLoopTerminalBridge<'runtime> {
    runtime: &'runtime KernelRuntime,
    decoder: Arc<TerminalInputDecoder>,
    max_batch: usize,
}

impl<'runtime> AgentLoopTerminalBridge<'runtime> {
    /// Construct a bridge with the default bounded batch size.
    pub fn new<F>(runtime: &'runtime KernelRuntime, decoder: F) -> Self
    where
        F: Fn(&TerminalFrame) -> Result<SessionInput, String> + Send + Sync + 'static,
    {
        Self {
            runtime,
            decoder: Arc::new(decoder),
            max_batch: AGENT_LOOP_TERMINAL_MAX_BATCH,
        }
    }

    /// Construct a bridge with an explicit positive batch bound.
    ///
    /// # Errors
    ///
    /// Returns `InvalidBinding` when `max_batch` is zero or exceeds the
    /// contract ceiling.
    pub fn with_max_batch<F>(
        runtime: &'runtime KernelRuntime,
        decoder: F,
        max_batch: usize,
    ) -> Result<Self, AgentLoopTerminalError>
    where
        F: Fn(&TerminalFrame) -> Result<SessionInput, String> + Send + Sync + 'static,
    {
        if max_batch == 0 || max_batch > AGENT_LOOP_TERMINAL_MAX_BATCH {
            return Err(AgentLoopTerminalError::InvalidBinding(
                "terminal bridge batch bound is outside the supported range".to_owned(),
            ));
        }
        Ok(Self {
            runtime,
            decoder: Arc::new(decoder),
            max_batch,
        })
    }

    /// Return the fixed batch bound used by this bridge.
    pub const fn max_batch(&self) -> usize {
        self.max_batch
    }

    /// Validate one loop/session/terminal correlation without requiring
    /// either side to be running.
    pub fn binding(
        &self,
        loop_id: &str,
        session: &Session,
        terminal_id: &str,
    ) -> Result<AgentLoopTerminalBinding, AgentLoopTerminalError> {
        let handle = self.runtime.agent_loops().handle(loop_id)?;
        let spec = handle.spec();
        if spec.terminal_id != terminal_id {
            return Err(AgentLoopTerminalError::InvalidBinding(format!(
                "loop {} is bound to terminal {}, not {}",
                spec.loop_id, spec.terminal_id, terminal_id
            )));
        }
        if session.id() != spec.session_id {
            return Err(AgentLoopTerminalError::InvalidBinding(
                "session id does not match the AgentLoop".to_owned(),
            ));
        }
        let session_spec = session.spec();
        if session_spec.agent_id != spec.agent_id || session_spec.cell_id != spec.cell_id {
            return Err(AgentLoopTerminalError::InvalidBinding(
                "session agent/cell identity does not match the AgentLoop".to_owned(),
            ));
        }
        let terminal = self.runtime.terminals().snapshot(terminal_id)?;
        if terminal.session_id.as_deref() != Some(spec.session_id.as_str()) {
            return Err(AgentLoopTerminalError::InvalidBinding(
                "terminal session binding does not match the AgentLoop".to_owned(),
            ));
        }
        if matches!(
            terminal.state,
            TerminalState::Stopped | TerminalState::Closed
        ) {
            return Err(AgentLoopTerminalError::InvalidBinding(format!(
                "terminal {} is unavailable in {} state",
                terminal_id,
                terminal.state.as_str()
            )));
        }
        Ok(AgentLoopTerminalBinding {
            contract_version: AGENT_LOOP_TERMINAL_CONTRACT_VERSION,
            spec,
            session_id: session.id().to_owned(),
            terminal_state: terminal.state,
        })
    }

    /// Submit one caller-owned terminal input frame to the AgentLoop.
    ///
    /// The caller normally obtains `frame` from `TerminalBook::take_input`.
    /// Dequeue ownership intentionally stays outside this bridge, so a
    /// transport adapter can choose its own retry or dead-letter policy.
    pub fn submit_frame(
        &self,
        loop_id: &str,
        session: Arc<Session>,
        terminal_id: &str,
        frame: TerminalFrame,
        action: AgentLoopAction,
    ) -> Result<AgentLoopExecutionTask, AgentLoopTerminalError> {
        self.ensure_running(loop_id, &session, terminal_id)?;
        validate_input_frame(&frame)?;
        let input = self.decode(&frame)?;
        AgentLoopExecutionBridge::new(self.runtime)
            .submit_input(loop_id, session, input, action)
            .map_err(Into::into)
    }

    /// Submit a bounded group of terminal input frames and actions.
    ///
    /// All frames are decoded before runtime admission. A decoder failure or
    /// action-count mismatch therefore queues no execution work and admits no
    /// session messages.
    pub fn submit_batch(
        &self,
        loop_id: &str,
        session: Arc<Session>,
        terminal_id: &str,
        frames: Vec<TerminalFrame>,
        actions: Vec<AgentLoopAction>,
    ) -> Result<Vec<AgentLoopExecutionTask>, AgentLoopTerminalError> {
        if frames.len() > self.max_batch {
            return Err(AgentLoopTerminalError::BatchTooLarge {
                size: frames.len(),
                limit: self.max_batch,
            });
        }
        if frames.len() != actions.len() {
            return Err(AgentLoopTerminalError::ActionCountMismatch {
                frames: frames.len(),
                actions: actions.len(),
            });
        }
        if frames.is_empty() {
            return Ok(Vec::new());
        }
        self.ensure_running(loop_id, &session, terminal_id)?;
        let inputs = frames
            .iter()
            .map(|frame| {
                validate_input_frame(frame)?;
                self.decode(frame)
            })
            .collect::<Result<Vec<_>, AgentLoopTerminalError>>()?;
        let requests = inputs
            .into_iter()
            .zip(actions)
            .map(|(input, action)| AgentLoopExecutionRequest::new(input, action))
            .collect();
        AgentLoopExecutionBridge::new(self.runtime)
            .submit_input_batch(loop_id, session, requests)
            .map_err(Into::into)
    }

    /// Publish one opaque AgentLoop output frame to the bound terminal.
    pub fn publish_output(
        &self,
        loop_id: &str,
        session: &Session,
        terminal_id: &str,
        stream: TerminalStream,
        data: Vec<u8>,
    ) -> Result<TerminalSnapshot, AgentLoopTerminalError> {
        self.ensure_running(loop_id, session, terminal_id)?;
        validate_output(stream, &data)?;
        Ok(self
            .runtime
            .terminals()
            .publish_output(terminal_id, stream, data)?)
    }

    /// Publish a bounded group of opaque output frames to the bound terminal.
    pub fn publish_output_batch(
        &self,
        loop_id: &str,
        session: &Session,
        terminal_id: &str,
        frames: Vec<(TerminalStream, Vec<u8>)>,
    ) -> Result<Vec<Result<(), TerminalError>>, AgentLoopTerminalError> {
        if frames.len() > self.max_batch {
            return Err(AgentLoopTerminalError::BatchTooLarge {
                size: frames.len(),
                limit: self.max_batch,
            });
        }
        self.ensure_running(loop_id, session, terminal_id)?;
        for (stream, data) in &frames {
            validate_output(*stream, data)?;
        }
        Ok(self
            .runtime
            .terminals()
            .publish_output_batch(terminal_id, frames)?)
    }

    /// Decode one input frame through the panic-contained host callback.
    fn decode(&self, frame: &TerminalFrame) -> Result<SessionInput, AgentLoopTerminalError> {
        catch_unwind(AssertUnwindSafe(|| (self.decoder)(frame)))
            .map_err(|_| {
                AgentLoopTerminalError::Decoder("terminal input decoder panicked".to_owned())
            })?
            .map_err(AgentLoopTerminalError::Decoder)
    }

    /// Validate the correlation and running states required by an I/O action.
    fn ensure_running(
        &self,
        loop_id: &str,
        session: &Session,
        terminal_id: &str,
    ) -> Result<AgentLoopTerminalBinding, AgentLoopTerminalError> {
        let binding = self.binding(loop_id, session, terminal_id)?;
        let loop_state = self.runtime.agent_loops().snapshot(loop_id)?.state;
        if loop_state != AgentLoopState::Running {
            return Err(AgentLoopTerminalError::AgentLoop(
                AgentLoopError::NotRunning(loop_state),
            ));
        }
        if binding.terminal_state != TerminalState::Running {
            return Err(AgentLoopTerminalError::Terminal(
                TerminalError::InvalidState {
                    terminal_id: terminal_id.to_owned(),
                    state: binding.terminal_state,
                    operation: "agent_loop_terminal_io".to_owned(),
                },
            ));
        }
        Ok(binding)
    }
}

/// Validate one caller-owned frame before session admission.
fn validate_input_frame(frame: &TerminalFrame) -> Result<(), AgentLoopTerminalError> {
    if frame.stream != TerminalStream::Input {
        return Err(AgentLoopTerminalError::InvalidFrame(
            "AgentLoop input bridge accepts input-stream frames only".to_owned(),
        ));
    }
    if frame.sequence == 0 {
        return Err(AgentLoopTerminalError::InvalidFrame(
            "terminal frame sequence must be positive".to_owned(),
        ));
    }
    if frame.data.len() > TERMINAL_MAX_FRAME_BYTES {
        return Err(AgentLoopTerminalError::InvalidFrame(format!(
            "terminal frame exceeds {} bytes",
            TERMINAL_MAX_FRAME_BYTES
        )));
    }
    Ok(())
}

/// Validate one caller-owned output frame before mailbox admission.
fn validate_output(stream: TerminalStream, data: &[u8]) -> Result<(), AgentLoopTerminalError> {
    if stream == TerminalStream::Input {
        return Err(AgentLoopTerminalError::InvalidFrame(
            "AgentLoop output bridge rejects input-stream frames".to_owned(),
        ));
    }
    if data.len() > TERMINAL_MAX_FRAME_BYTES {
        return Err(AgentLoopTerminalError::InvalidFrame(format!(
            "terminal output frame exceeds {} bytes",
            TERMINAL_MAX_FRAME_BYTES
        )));
    }
    Ok(())
}
