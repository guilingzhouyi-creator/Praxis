//! Rust-native execution bridge for one logical AgentLoop input.
//!
//! The bridge joins an already-running AgentLoop to the bounded kernel
//! worker pool. Input admission happens inside the accepted runtime task, so a
//! queue-capacity or pre-execution cancellation failure cannot leave a session
//! message behind. The caller still supplies the action that represents
//! provider/tool work; this module only admits its optional event back into
//! the Rust session truth root.

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Arc;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{Value, to_value};

use crate::agent_loop::{
    AgentLoopError, AgentLoopEvent, AgentLoopHandle, AgentLoopReceipt, AgentLoopSpec,
    AgentLoopState,
};
use crate::runtime::{KernelRuntime, RuntimeError, RuntimeTask, RuntimeTaskState};
use crate::session::{Session, SessionInput};
use crate::worker::{TaskFn, TaskHandleError};

/// Version of the Rust-native AgentLoop execution bridge contract.
pub const AGENT_LOOP_EXECUTION_CONTRACT_VERSION: u32 = 1;

/// Caller-owned action for one admitted input.
pub type AgentLoopAction = Box<
    dyn FnOnce(AgentLoopExecutionContext) -> Result<Option<AgentLoopEvent>, String>
        + Send
        + 'static,
>;

/// One caller-owned input/action pair for grouped execution admission.
pub struct AgentLoopExecutionRequest {
    /// Input admitted before the caller-owned action runs.
    pub input: SessionInput,
    /// Caller-owned provider/tool action for this input.
    pub action: AgentLoopAction,
}

impl AgentLoopExecutionRequest {
    /// Build one grouped execution request.
    pub fn new(input: SessionInput, action: AgentLoopAction) -> Self {
        Self { input, action }
    }
}

/// Immutable context passed to the caller-owned execution action.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentLoopExecutionContext {
    /// Receipt assigned after the input reaches the session truth root.
    pub receipt: AgentLoopReceipt,
    /// Stable identity of the loop executing the action.
    pub spec: AgentLoopSpec,
}

/// Result of one complete input/action/event execution.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentLoopExecutionReport {
    /// Execution bridge contract version.
    pub contract_version: u32,
    /// Receipt for the admitted user input.
    pub input: AgentLoopReceipt,
    /// Receipt for the optional assistant/tool/system event.
    pub event: Option<AgentLoopReceipt>,
}

/// Stage at which one execution task failed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentLoopExecutionStage {
    /// Input admission into the session truth root.
    Admission,
    /// Caller-owned provider/tool action.
    Action,
    /// Optional event admission into the session truth root.
    EventAdmission,
}

/// Structured failure retained in a failed runtime task result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentLoopExecutionFailure {
    /// Stage that rejected or failed.
    pub stage: AgentLoopExecutionStage,
    /// Input receipt, when admission completed before the failure.
    pub input: Option<AgentLoopReceipt>,
    /// Stable action or bridge failure text.
    pub reason: String,
    /// Kernel admission error, when the session rejected a message.
    pub agent_loop_error: Option<AgentLoopError>,
}

/// Failure while submitting or resolving an execution task.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AgentLoopExecutionError {
    /// The loop identity or admission precondition was rejected.
    AgentLoop(AgentLoopError),
    /// The runtime could not reserve or enqueue a task.
    Runtime(RuntimeError),
}

/// Failure returned while waiting for an execution task.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AgentLoopExecutionWaitError {
    /// The action or worker produced a structured execution failure.
    Execution(AgentLoopExecutionFailure),
    /// The worker result was cancelled, timed out, or could not be decoded.
    Task(TaskHandleError),
    /// A successful task returned a value outside the bridge contract.
    InvalidReport(String),
}

/// Handle for one queued AgentLoop execution.
#[derive(Clone)]
pub struct AgentLoopExecutionTask {
    task: RuntimeTask,
}

impl AgentLoopExecutionTask {
    /// Return the generation-safe runtime handle.
    pub const fn handle(&self) -> crate::substrate::ProcessHandle {
        self.task.handle()
    }

    /// Wait for and decode the complete bridge report.
    pub fn result(
        &self,
        timeout: Option<Duration>,
    ) -> Result<AgentLoopExecutionReport, AgentLoopExecutionWaitError> {
        match self.task.result(timeout) {
            Ok(value) => parse_report(value),
            Err(TaskHandleError::Failed(reason)) => match serde_json::from_str(&reason) {
                Ok(failure) => Err(AgentLoopExecutionWaitError::Execution(failure)),
                Err(_) => Err(AgentLoopExecutionWaitError::Task(TaskHandleError::Failed(
                    reason,
                ))),
            },
            Err(error) => Err(AgentLoopExecutionWaitError::Task(error)),
        }
    }

    /// Request cancellation before the worker starts the action.
    pub fn cancel(&self, reason: impl Into<String>) -> bool {
        self.task.cancel(reason)
    }

    /// Return whether the runtime task has completed.
    pub fn done(&self) -> bool {
        self.task.done()
    }

    /// Return the runtime-owned task state.
    pub fn state(&self) -> Option<RuntimeTaskState> {
        self.task.state()
    }
}

/// Explicit bridge from one KernelRuntime to caller-owned AgentLoop actions.
pub struct AgentLoopExecutionBridge<'runtime> {
    runtime: &'runtime KernelRuntime,
}

impl<'runtime> AgentLoopExecutionBridge<'runtime> {
    /// Bind the bridge to one runtime without changing runtime authority.
    pub const fn new(runtime: &'runtime KernelRuntime) -> Self {
        Self { runtime }
    }

    /// Submit one input/action execution with no worker deadline.
    pub fn submit_input(
        &self,
        loop_id: &str,
        session: Arc<Session>,
        input: SessionInput,
        action: AgentLoopAction,
    ) -> Result<AgentLoopExecutionTask, AgentLoopExecutionError> {
        self.submit_inner(loop_id, session, input, action, None)
    }

    /// Submit one input/action execution with an explicit worker deadline.
    pub fn submit_input_with_timeout(
        &self,
        loop_id: &str,
        session: Arc<Session>,
        input: SessionInput,
        action: AgentLoopAction,
        timeout: Duration,
    ) -> Result<AgentLoopExecutionTask, AgentLoopExecutionError> {
        self.submit_inner(loop_id, session, input, action, Some(timeout))
    }

    /// Submit a non-empty group of input/action executions through one runtime
    /// admission boundary.
    ///
    /// The runtime reserves every task before any worker can execute. If the
    /// process or worker capacity is exhausted, the complete group is rolled
    /// back and no input is admitted. Once accepted, each item retains the
    /// single-input bridge semantics and may complete independently.
    pub fn submit_input_batch(
        &self,
        loop_id: &str,
        session: Arc<Session>,
        requests: Vec<AgentLoopExecutionRequest>,
    ) -> Result<Vec<AgentLoopExecutionTask>, AgentLoopExecutionError> {
        if requests.is_empty() {
            return Ok(Vec::new());
        }
        let handle = self
            .runtime
            .agent_loops()
            .handle(loop_id)
            .map_err(AgentLoopExecutionError::AgentLoop)?;
        let spec = handle.spec();
        if session.id() != spec.session_id {
            return Err(AgentLoopExecutionError::AgentLoop(
                AgentLoopError::SessionMismatch,
            ));
        }
        let state = handle.snapshot().state;
        if state != AgentLoopState::Running {
            return Err(AgentLoopExecutionError::AgentLoop(
                AgentLoopError::NotRunning(state),
            ));
        }
        let actions = requests
            .into_iter()
            .map(|request| {
                let session = Arc::clone(&session);
                let handle = handle.clone();
                Box::new(move || execute_input(handle, session, request.input, request.action))
                    as TaskFn
            })
            .collect();
        self.runtime
            .submit_batch_strict(actions)
            .map(|tasks| {
                tasks
                    .into_iter()
                    .map(|task| AgentLoopExecutionTask { task })
                    .collect()
            })
            .map_err(AgentLoopExecutionError::Runtime)
    }

    /// Reap a terminal execution task through the owning runtime.
    pub fn reap(&self, task: &AgentLoopExecutionTask) -> Result<(), RuntimeError> {
        self.runtime.reap(task.handle())
    }

    fn submit_inner(
        &self,
        loop_id: &str,
        session: Arc<Session>,
        input: SessionInput,
        action: AgentLoopAction,
        timeout: Option<Duration>,
    ) -> Result<AgentLoopExecutionTask, AgentLoopExecutionError> {
        let handle = self
            .runtime
            .agent_loops()
            .handle(loop_id)
            .map_err(AgentLoopExecutionError::AgentLoop)?;
        let spec = handle.spec();
        if session.id() != spec.session_id {
            return Err(AgentLoopExecutionError::AgentLoop(
                AgentLoopError::SessionMismatch,
            ));
        }
        let state = handle.snapshot().state;
        if state != AgentLoopState::Running {
            return Err(AgentLoopExecutionError::AgentLoop(
                AgentLoopError::NotRunning(state),
            ));
        }

        let task: TaskFn = Box::new(move || execute_input(handle, session, input, action));
        let task = match timeout {
            Some(timeout) => self.runtime.submit_with_timeout(task, timeout),
            None => self.runtime.submit(task),
        }
        .map_err(AgentLoopExecutionError::Runtime)?;
        Ok(AgentLoopExecutionTask { task })
    }
}

fn execute_input(
    handle: AgentLoopHandle,
    session: Arc<Session>,
    input: SessionInput,
    action: AgentLoopAction,
) -> Result<Value, String> {
    let SessionInput {
        message_id,
        content,
        created_at_ns,
    } = input;
    let receipt = handle
        .admit_input(&session, message_id, content, created_at_ns)
        .map_err(|error| encode_failure(admission_failure(error)))?;
    let context = AgentLoopExecutionContext {
        receipt: receipt.clone(),
        spec: handle.spec(),
    };
    let event = match catch_unwind(AssertUnwindSafe(|| action(context))) {
        Ok(Ok(event)) => event,
        Ok(Err(reason)) => {
            return Err(encode_failure(AgentLoopExecutionFailure {
                stage: AgentLoopExecutionStage::Action,
                input: Some(receipt),
                reason,
                agent_loop_error: None,
            }));
        }
        Err(_) => {
            return Err(encode_failure(AgentLoopExecutionFailure {
                stage: AgentLoopExecutionStage::Action,
                input: Some(receipt),
                reason: "execution action panicked".to_owned(),
                agent_loop_error: None,
            }));
        }
    };
    let event_receipt = match event {
        Some(event) => Some(
            handle
                .admit_event(&session, event)
                .map_err(|error| encode_failure(event_failure(error, receipt.clone())))?,
        ),
        None => None,
    };
    to_value(AgentLoopExecutionReport {
        contract_version: AGENT_LOOP_EXECUTION_CONTRACT_VERSION,
        input: receipt,
        event: event_receipt,
    })
    .map_err(|error| format!("execution report serialization failed: {error}"))
}

fn admission_failure(error: AgentLoopError) -> AgentLoopExecutionFailure {
    AgentLoopExecutionFailure {
        stage: AgentLoopExecutionStage::Admission,
        input: None,
        reason: "input admission rejected".to_owned(),
        agent_loop_error: Some(error),
    }
}

fn event_failure(error: AgentLoopError, input: AgentLoopReceipt) -> AgentLoopExecutionFailure {
    AgentLoopExecutionFailure {
        stage: AgentLoopExecutionStage::EventAdmission,
        input: Some(input),
        reason: "event admission rejected".to_owned(),
        agent_loop_error: Some(error),
    }
}

fn encode_failure(failure: AgentLoopExecutionFailure) -> String {
    serde_json::to_string(&failure).unwrap_or_else(|_| "agent loop execution failed".to_owned())
}

fn parse_report(value: Value) -> Result<AgentLoopExecutionReport, AgentLoopExecutionWaitError> {
    let report: AgentLoopExecutionReport = serde_json::from_value(value)
        .map_err(|error| AgentLoopExecutionWaitError::InvalidReport(error.to_string()))?;
    if report.contract_version != AGENT_LOOP_EXECUTION_CONTRACT_VERSION {
        return Err(AgentLoopExecutionWaitError::InvalidReport(
            "unsupported AgentLoop execution contract version".to_owned(),
        ));
    }
    Ok(report)
}
