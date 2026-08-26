//! Declarative boot-plan assembly for the Rust-first kernel.
//!
//! This module owns step metadata, dependency ordering, and an explicit
//! caller-supplied execution seam. The executor never discovers callbacks,
//! starts workers, reads configuration, mutates lifecycle state, or wires
//! upper-layer services on its own.

use std::collections::{BTreeMap, BTreeSet};
use std::panic::{AssertUnwindSafe, catch_unwind};

use serde::{Deserialize, Serialize};

/// One side-effect-free boot step declaration.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BootStepSpec {
    /// Stable step name.
    pub name: String,
    /// Names that must be ordered before this step.
    #[serde(default)]
    pub depends_on: Vec<String>,
}

impl BootStepSpec {
    /// Build a step declaration from a name and dependency list.
    pub fn new(name: impl Into<String>, depends_on: Vec<String>) -> Self {
        Self {
            name: name.into(),
            depends_on,
        }
    }
}

/// Structured errors raised while assembling a boot plan.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum BootPlanError {
    /// Step names must be unique unless replacement is explicit.
    DuplicateStep { name: String },
    /// A locked plan rejects ordinary registrations.
    Locked,
    /// A step or dependency has an empty name.
    InvalidName,
    /// A dependency does not have a registered step.
    MissingDependency { step: String, dependency: String },
    /// The dependency graph contains a cycle.
    Cycle { path: Vec<String> },
}

/// Failure while executing an explicitly supplied boot handler set.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum BootExecutionError {
    /// Execution requires a plan locked against registration changes.
    PlanUnlocked,
    /// The plan could not be resolved into a dependency order.
    InvalidPlan(BootPlanError),
    /// A validated plan step has no caller-supplied handler.
    MissingHandler { step: String },
    /// A caller supplied a handler for a step absent from the plan.
    UnexpectedHandler { step: String },
    /// A handler returned an application error after prior steps completed.
    StepFailed {
        step: String,
        reason: String,
        completed: Vec<String>,
    },
    /// A handler panicked; no panic is allowed to cross the kernel boundary.
    StepPanicked {
        step: String,
        completed: Vec<String>,
    },
}

/// Stable result of one dependency-ordered boot execution.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BootExecutionReport {
    /// Number of registered steps in the executed plan.
    pub step_count: usize,
    /// Steps attempted in dependency order.
    pub attempted: Vec<String>,
    /// Steps whose handlers returned success.
    pub completed: Vec<String>,
}

/// Caller-owned callback type for one boot step.
pub type BootAction = Box<dyn Fn() -> Result<(), String> + Send + Sync + 'static>;

/// Validated declarative boot plan with deterministic registration order.
#[derive(Debug, Default)]
pub struct BootPlan {
    order: Vec<String>,
    steps: BTreeMap<String, BootStepSpec>,
    locked: bool,
}

impl BootPlan {
    /// Create an empty, mutable boot plan.
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a step, optionally replacing a prior declaration.
    pub fn register(
        &mut self,
        step: BootStepSpec,
        allow_replace: bool,
    ) -> Result<(), BootPlanError> {
        validate_step(&step)?;
        if self.locked && !allow_replace {
            return Err(BootPlanError::Locked);
        }
        if self.steps.contains_key(&step.name) && !allow_replace {
            return Err(BootPlanError::DuplicateStep { name: step.name });
        }
        if !self.steps.contains_key(&step.name) {
            self.order.push(step.name.clone());
        }
        self.steps.insert(step.name.clone(), step);
        Ok(())
    }

    /// Prevent further ordinary registrations before execution wiring.
    pub fn lock(&mut self) {
        self.locked = true;
    }

    /// Return whether the plan has been locked.
    pub const fn is_locked(&self) -> bool {
        self.locked
    }

    /// Return declarations in registration order without exposing internal maps.
    pub fn snapshot(&self) -> Vec<BootStepSpec> {
        self.order
            .iter()
            .filter_map(|name| self.steps.get(name).cloned())
            .collect()
    }

    /// Resolve a deterministic dependency-first execution order.
    pub fn resolve_order(&self) -> Result<Vec<String>, BootPlanError> {
        let mut ordered = Vec::with_capacity(self.order.len());
        let mut visited = BTreeSet::new();
        let mut visiting = Vec::new();
        for name in &self.order {
            visit(name, &self.steps, &mut visited, &mut visiting, &mut ordered)?;
        }
        Ok(ordered)
    }

    /// Return the number of registered steps.
    pub fn len(&self) -> usize {
        self.steps.len()
    }

    /// Return whether no steps are registered.
    pub fn is_empty(&self) -> bool {
        self.steps.is_empty()
    }

    /// Execute every locked step through the exact caller-supplied handlers.
    ///
    /// Handler lookup is validated before the first callback runs. A missing
    /// or unexpected handler therefore cannot produce a partially executed
    /// boot. Callback failures and panics stop execution and return the
    /// completed prefix for caller-owned rollback or recovery policy.
    pub fn execute(
        &self,
        handlers: BTreeMap<String, BootAction>,
    ) -> Result<BootExecutionReport, BootExecutionError> {
        if !self.locked {
            return Err(BootExecutionError::PlanUnlocked);
        }
        let order = self
            .resolve_order()
            .map_err(BootExecutionError::InvalidPlan)?;
        for step in &order {
            if !handlers.contains_key(step) {
                return Err(BootExecutionError::MissingHandler { step: step.clone() });
            }
        }
        for step in handlers.keys() {
            if !self.steps.contains_key(step) {
                return Err(BootExecutionError::UnexpectedHandler { step: step.clone() });
            }
        }

        let mut attempted = Vec::with_capacity(order.len());
        let mut completed = Vec::with_capacity(order.len());
        for step in order {
            attempted.push(step.clone());
            let action = handlers
                .get(&step)
                .expect("handler presence validated before execution");
            let result = catch_unwind(AssertUnwindSafe(action));
            match result {
                Ok(Ok(())) => completed.push(step),
                Ok(Err(reason)) => {
                    return Err(BootExecutionError::StepFailed {
                        step,
                        reason,
                        completed,
                    });
                }
                Err(_) => {
                    return Err(BootExecutionError::StepPanicked { step, completed });
                }
            }
        }
        Ok(BootExecutionReport {
            step_count: attempted.len(),
            attempted,
            completed,
        })
    }
}

fn validate_step(step: &BootStepSpec) -> Result<(), BootPlanError> {
    if step.name.trim().is_empty() || step.depends_on.iter().any(|name| name.trim().is_empty()) {
        return Err(BootPlanError::InvalidName);
    }
    Ok(())
}

fn visit(
    name: &str,
    steps: &BTreeMap<String, BootStepSpec>,
    visited: &mut BTreeSet<String>,
    visiting: &mut Vec<String>,
    ordered: &mut Vec<String>,
) -> Result<(), BootPlanError> {
    if visited.contains(name) {
        return Ok(());
    }
    if let Some(index) = visiting.iter().position(|item| item == name) {
        let mut path = visiting[index..].to_vec();
        path.push(name.to_owned());
        return Err(BootPlanError::Cycle { path });
    }
    let Some(step) = steps.get(name) else {
        let parent = visiting.last().cloned().unwrap_or_default();
        return Err(BootPlanError::MissingDependency {
            step: parent,
            dependency: name.to_owned(),
        });
    };
    visiting.push(name.to_owned());
    for dependency in &step.depends_on {
        if !steps.contains_key(dependency) {
            return Err(BootPlanError::MissingDependency {
                step: name.to_owned(),
                dependency: dependency.clone(),
            });
        }
        visit(dependency, steps, visited, visiting, ordered)?;
    }
    visiting.pop();
    visited.insert(name.to_owned());
    ordered.push(name.to_owned());
    Ok(())
}
