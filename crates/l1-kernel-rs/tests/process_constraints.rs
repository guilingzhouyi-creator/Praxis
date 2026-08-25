//! Independent tests for fail-closed Agent process admission.

use std::collections::BTreeSet;

use l1_kernel_rs::contract::ProcessOptions;
use l1_kernel_rs::process_adapter::ProcessAdapterConfig;
use l1_kernel_rs::process_constraints::{
    AgentProcessMode, AgentProcessPolicy, AgentProcessSpec, AgentResourceRequest,
    ProcessConstraintError, ProcessConstraintEvaluator, ProcessConstraintViolation,
};
use l1_kernel_rs::process_group_runtime::{ProcessGroupRuntime, ProcessGroupRuntimeError};
use l1_kernel_rs::terminal_probe::{TerminalKind, TerminalObservation};

fn terminal() -> TerminalObservation {
    TerminalObservation::new(
        "bash",
        TerminalKind::Bash,
        "/host/bash",
        vec!["-c".to_owned()],
        Some("5".to_owned()),
        true,
        true,
        true,
        "utf-8",
        "test-probe",
    )
}

fn policy() -> AgentProcessPolicy {
    AgentProcessPolicy {
        allowed_rings: BTreeSet::from([3]),
        allowed_terminal_ids: Some(BTreeSet::from(["bash".to_owned()])),
        allowed_terminal_kinds: Some(BTreeSet::from([TerminalKind::Bash])),
        allowed_executables: Some(BTreeSet::from([
            "/host/bash".to_owned(),
            "/host/tool".to_owned(),
        ])),
        allowed_cwd_prefixes: Some(vec!["/workspace".to_owned()]),
        allowed_environment_keys: BTreeSet::from(["PATH".to_owned(), "LANG".to_owned()]),
        denied_environment_keys: BTreeSet::from(["SECRET".to_owned()]),
        allow_environment_replacement: false,
        max_argv_items: 5,
        max_timeout_ms: 1_000,
        max_output_bytes: 1_024,
        max_cpu_time_ms: Some(500),
        max_memory_bytes: Some(1 << 20),
        allow_shell: true,
        require_interactive_terminal: true,
        require_pty: true,
        require_process_group: true,
    }
}

fn shell_spec() -> AgentProcessSpec {
    AgentProcessSpec {
        process_id: "p1".to_owned(),
        agent_id: "agent".to_owned(),
        cell_id: "cell".to_owned(),
        ring: 3,
        mode: AgentProcessMode::Shell,
        argv: terminal().command_argv("printf ready"),
        cwd: Some("/workspace/job".to_owned()),
        environment_keys: vec!["PATH".to_owned()],
        replaces_environment: false,
        process_group_id: Some("group-1".to_owned()),
        timeout_ms: 100,
        resources: AgentResourceRequest {
            max_output_bytes: 512,
            max_cpu_time_ms: Some(100),
            max_memory_bytes: Some(4096),
        },
    }
}

#[test]
fn shell_admission_requires_explicit_terminal_and_limits() {
    let evaluator = ProcessConstraintEvaluator::new(policy()).expect("policy");
    let admission = evaluator
        .admit(&shell_spec(), Some(&terminal()))
        .expect("admitted");
    assert_eq!(admission.process_id, "p1");
    assert_eq!(admission.terminal_id.as_deref(), Some("bash"));
    assert_eq!(admission.argv, terminal().command_argv("printf ready"));
}

#[test]
fn constraint_failures_are_structured_and_accumulated() {
    let evaluator = ProcessConstraintEvaluator::new(policy()).expect("policy");
    let mut spec = shell_spec();
    spec.ring = 2;
    spec.cwd = Some("/tmp".to_owned());
    spec.environment_keys = vec!["SECRET".to_owned(), "HOME".to_owned()];
    spec.replaces_environment = true;
    spec.timeout_ms = 2_000;
    spec.resources.max_output_bytes = 2_000;
    spec.process_group_id = None;
    let error = evaluator.admit(&spec, None).expect_err("rejected");
    let ProcessConstraintError::Violations(violations) = error else {
        panic!("expected structured violations")
    };
    assert!(violations.contains(&ProcessConstraintViolation::RingNotAllowed { ring: 2 }));
    assert!(violations.contains(&ProcessConstraintViolation::TerminalRequired));
    assert!(
        violations.contains(&ProcessConstraintViolation::WorkingDirectoryNotAllowed {
            cwd: "/tmp".to_owned()
        })
    );
    assert!(
        violations.contains(&ProcessConstraintViolation::EnvironmentKeyDenied {
            key: "SECRET".to_owned()
        })
    );
    assert!(
        violations.contains(&ProcessConstraintViolation::EnvironmentKeyNotAllowed {
            key: "HOME".to_owned()
        })
    );
    assert!(violations.contains(&ProcessConstraintViolation::EnvironmentReplacementNotAllowed));
    assert!(
        violations.contains(&ProcessConstraintViolation::TimeoutExceeded {
            actual: 2_000,
            limit: 1_000
        })
    );
    assert!(
        violations.contains(&ProcessConstraintViolation::OutputLimitExceeded {
            actual: 2_000,
            limit: 1_024
        })
    );
    assert!(violations.contains(&ProcessConstraintViolation::ProcessGroupRequired));
}

#[test]
fn direct_admission_does_not_obtain_shell_authority() {
    let evaluator = ProcessConstraintEvaluator::new(policy()).expect("policy");
    let mut spec = shell_spec();
    spec.mode = AgentProcessMode::Direct;
    spec.argv = vec!["/host/tool".to_owned(), "--safe".to_owned()];
    spec.process_group_id = Some("group-1".to_owned());
    let admission = evaluator.admit(&spec, None).expect("direct admitted");
    assert_eq!(admission.terminal_id, None);
    assert_eq!(admission.argv, spec.argv);
}

#[test]
fn shell_without_command_is_rejected() {
    let evaluator = ProcessConstraintEvaluator::new(policy()).expect("policy");
    let mut spec = shell_spec();
    spec.argv = vec!["/host/bash".to_owned(), "-c".to_owned()];
    let error = evaluator
        .admit(&spec, Some(&terminal()))
        .expect_err("missing command");
    assert!(matches!(
        error,
        ProcessConstraintError::Violations(violations)
            if violations.contains(&ProcessConstraintViolation::TerminalCommandMissing)
    ));
}

#[test]
fn working_directory_parent_escape_is_rejected_lexically() {
    let evaluator = ProcessConstraintEvaluator::new(policy()).expect("policy");
    let mut spec = shell_spec();
    spec.cwd = Some("/workspace/../outside".to_owned());
    let error = evaluator
        .admit(&spec, Some(&terminal()))
        .expect_err("parent escape");
    assert!(matches!(
        error,
        ProcessConstraintError::Violations(violations)
            if violations.contains(&ProcessConstraintViolation::WorkingDirectoryNotAllowed {
                cwd: "/workspace/../outside".to_owned()
            })
    ));
}

#[test]
fn constrained_runtime_rejects_adapter_overrides_before_spawn() {
    let runtime = ProcessGroupRuntime::new(
        ProcessAdapterConfig::new(256).expect("config"),
        1,
        1,
        1,
        std::time::Duration::from_millis(100),
    )
    .expect("runtime");
    let group = runtime.create_group("constraints", None).expect("group");
    let options = ProcessOptions {
        cwd: Some("/workspace/job".to_owned()),
        executable: Some("/host/other".to_owned()),
        ..ProcessOptions::default()
    };
    let error = runtime
        .spawn_constrained(
            group,
            &shell_spec(),
            policy(),
            Some(&terminal()),
            Some(&options),
        )
        .expect_err("adapter override");
    assert!(matches!(
        error,
        ProcessGroupRuntimeError::Constraints(ProcessConstraintError::Violations(violations))
            if violations.iter().any(|value| matches!(
                value,
                ProcessConstraintViolation::AdapterExecutableMismatch { .. }
            ))
    ));
    assert_eq!(runtime.processes().active_count(), 0);
    assert!(
        runtime
            .snapshot(group)
            .expect("snapshot")
            .members
            .is_empty()
    );
}
