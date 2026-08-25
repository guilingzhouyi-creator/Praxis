//! Independent tests for injected terminal capability discovery.

use std::collections::BTreeSet;

use l1_kernel_rs::terminal_probe::{
    TERMINAL_PROBE_CONTRACT_VERSION, TerminalKind, TerminalObservation, TerminalProbe,
    TerminalProbeConfig, TerminalProbeError,
};

fn observation(id: &str, kind: TerminalKind, executable: &str) -> TerminalObservation {
    TerminalObservation::new(
        id,
        kind,
        executable,
        vec!["-c".to_owned()],
        Some("host-version".to_owned()),
        true,
        true,
        true,
        "utf-8",
        "test-adapter",
    )
}

fn config() -> TerminalProbeConfig {
    TerminalProbeConfig::new(
        true,
        true,
        true,
        Some(BTreeSet::from([
            TerminalKind::Bash,
            TerminalKind::PowerShell,
        ])),
        vec!["pwsh7".to_owned(), "bash".to_owned()],
        4,
    )
    .expect("config")
}

#[test]
fn discovery_uses_injected_observations_and_explicit_preference() {
    let probe = TerminalProbe::new(config());
    let discovery = probe
        .discover([
            observation("bash", TerminalKind::Bash, "/host/bash"),
            observation("cmd", TerminalKind::Cmd, "C:\\host\\cmd.exe"),
            observation("pwsh7", TerminalKind::PowerShell, "C:\\host\\pwsh.exe"),
        ])
        .expect("discovery");
    assert_eq!(discovery.contract_version, TERMINAL_PROBE_CONTRACT_VERSION);
    assert_eq!(
        discovery
            .observed
            .iter()
            .map(|value| value.terminal_id.as_str())
            .collect::<Vec<_>>(),
        ["bash", "cmd", "pwsh7"]
    );
    assert_eq!(
        discovery
            .eligible
            .iter()
            .map(|value| value.terminal_id.as_str())
            .collect::<Vec<_>>(),
        ["pwsh7", "bash"]
    );
    assert_eq!(discovery.selected.expect("selected").terminal_id, "pwsh7");
}

#[test]
fn command_argv_is_built_from_host_invocation_without_path_defaults() {
    let terminal = TerminalObservation::new(
        "custom-shell",
        TerminalKind::Other("vendor_shell".to_owned()),
        "/opt/vendor/bin/shell",
        vec!["--execute".to_owned(), "--utf8".to_owned()],
        None,
        true,
        false,
        false,
        "utf-16",
        "vendor-probe",
    );
    assert_eq!(
        terminal.command_argv("echo ready"),
        ["/opt/vendor/bin/shell", "--execute", "--utf8", "echo ready"]
    );
}

#[test]
fn duplicate_and_ineligible_observations_fail_closed() {
    let probe = TerminalProbe::new(config());
    assert!(matches!(
        probe.discover([
            observation("bash", TerminalKind::Bash, "/host/bash"),
            observation("bash", TerminalKind::Bash, "/host/other-bash"),
        ]),
        Err(TerminalProbeError::DuplicateTerminal { .. })
    ));
    let unavailable = TerminalObservation::new(
        "pwsh7",
        TerminalKind::PowerShell,
        "pwsh",
        vec!["-Command".to_owned()],
        None,
        false,
        true,
        true,
        "utf-8",
        "test-adapter",
    );
    assert_eq!(
        probe.discover([unavailable]),
        Err(TerminalProbeError::NoEligibleTerminal)
    );
}
