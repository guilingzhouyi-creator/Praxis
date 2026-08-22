//! Independent state-layout mechanism tests for the Rust kernel.

use l1_kernel_rs::state_layout::{
    STATE_LAYOUT_VERSION, StateAction, StateEntry, StateLayoutError, StateLayoutManifest,
    StateProbe, StateReason, decide_state_action,
};

#[test]
fn fresh_manifest_is_sorted_and_round_trips() {
    let manifest = StateLayoutManifest::fresh("/var/lib/praxis-rs", 1).expect("layout");
    assert_eq!(manifest.layout_version, STATE_LAYOUT_VERSION);
    assert_eq!(manifest.entries[0], StateEntry::directory("audit"));
    assert_eq!(
        manifest.entries.last().expect("last"),
        &StateEntry::directory("tmp")
    );
    assert!(
        manifest
            .entries
            .contains(&StateEntry::file("runtime/checkpoint.json"))
    );
    let restored =
        StateLayoutManifest::decode(&manifest.encode().expect("encode")).expect("decode");
    assert_eq!(restored, manifest);
}

#[test]
fn malformed_entries_fail_closed() {
    assert!(matches!(
        StateLayoutManifest::new("/tmp/state", 1, vec![]),
        Err(StateLayoutError::EmptyLayout)
    ));
    assert!(matches!(
        StateLayoutManifest::new("/tmp/state", 1, vec![StateEntry::file("../escape")]),
        Err(StateLayoutError::InvalidPath { .. })
    ));
    assert!(matches!(
        StateLayoutManifest::new(
            "/tmp/state",
            1,
            vec![StateEntry::file("audit/events.jsonl")]
        ),
        Err(StateLayoutError::MissingParent { .. })
    ));
}

#[test]
fn state_actions_are_explicit_and_fail_closed() {
    let cases = [
        (
            StateProbe {
                root_exists: false,
                root_empty: false,
                manifest_version: None,
                clean_shutdown: None,
            },
            StateAction::Initialize,
            StateReason::MissingRoot,
        ),
        (
            StateProbe {
                root_exists: true,
                root_empty: true,
                manifest_version: None,
                clean_shutdown: None,
            },
            StateAction::Initialize,
            StateReason::EmptyRoot,
        ),
        (
            StateProbe {
                root_exists: true,
                root_empty: false,
                manifest_version: None,
                clean_shutdown: None,
            },
            StateAction::Reject,
            StateReason::MissingManifest,
        ),
        (
            StateProbe {
                root_exists: true,
                root_empty: false,
                manifest_version: Some(0),
                clean_shutdown: None,
            },
            StateAction::Migrate,
            StateReason::OlderLayout,
        ),
        (
            StateProbe {
                root_exists: true,
                root_empty: false,
                manifest_version: Some(2),
                clean_shutdown: Some(true),
            },
            StateAction::Reject,
            StateReason::FutureLayout,
        ),
        (
            StateProbe {
                root_exists: true,
                root_empty: false,
                manifest_version: Some(1),
                clean_shutdown: Some(false),
            },
            StateAction::Recover,
            StateReason::UncleanShutdown,
        ),
    ];
    for (probe, action, reason) in cases {
        let decision = decide_state_action(&probe, 1).expect("decision");
        assert_eq!(decision.action, action);
        assert_eq!(decision.reason, reason);
    }
}
