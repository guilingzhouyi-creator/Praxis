//! Independent aggregate input-activity probe tests for the Rust kernel.

use l1_kernel_rs::input_activity::{
    InputActivityObservation, InputActivityPermission, InputActivityProbe, InputActivityProbeConfig,
};
use l1_kernel_rs::ports::InputActivitySnapshot;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct InputActivityVectors {
    contract_version: u32,
    config: InputActivityProbeConfig,
    cases: Vec<InputActivityCase>,
}

#[derive(Debug, Deserialize)]
struct InputActivityCase {
    name: String,
    now: f64,
    observations: Vec<InputActivityObservation>,
    expected: InputActivitySnapshot,
}

#[test]
fn shared_input_activity_vectors_match_rust_probe() {
    let vectors: InputActivityVectors = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_input_activity_vectors.json"
    ))
    .expect("valid input activity vectors");
    assert_eq!(vectors.contract_version, 1);
    let probe = InputActivityProbe::new(vectors.config).expect("valid probe config");
    for case in vectors.cases {
        assert_eq!(
            probe
                .aggregate(case.now, case.observations)
                .expect("aggregate"),
            case.expected,
            "{}",
            case.name
        );
    }
}

#[test]
fn invalid_permissions_timestamps_and_source_bounds_fail_closed() {
    let probe = InputActivityProbe::new(InputActivityProbeConfig {
        idle_after_seconds: 5.0,
        max_sources: 1,
    })
    .expect("config");
    let active = InputActivityObservation::new(
        "keyboard",
        InputActivityPermission::Granted,
        true,
        false,
        10.0,
    );
    assert!(probe.aggregate(10.0, [active.clone(), active]).is_err());
    assert!(
        probe
            .aggregate(
                10.0,
                [InputActivityObservation::new(
                    "bad source",
                    InputActivityPermission::Unavailable,
                    false,
                    false,
                    0.0,
                )]
            )
            .is_err()
    );
    assert!(
        probe
            .aggregate(
                10.0,
                [InputActivityObservation::new(
                    "keyboard",
                    InputActivityPermission::Granted,
                    true,
                    false,
                    11.0,
                )]
            )
            .is_err()
    );
    assert!(
        probe
            .aggregate(
                10.0,
                [InputActivityObservation::new(
                    "keyboard",
                    InputActivityPermission::Denied,
                    true,
                    false,
                    9.0,
                )]
            )
            .is_err()
    );
    assert!(probe.aggregate(f64::NAN, std::iter::empty()).is_err());
}

#[test]
fn probe_config_rejects_zero_and_non_finite_bounds() {
    assert!(
        InputActivityProbe::new(InputActivityProbeConfig {
            idle_after_seconds: 0.0,
            max_sources: 1,
        })
        .is_err()
    );
    assert!(
        InputActivityProbe::new(InputActivityProbeConfig {
            idle_after_seconds: f64::INFINITY,
            max_sources: 1,
        })
        .is_err()
    );
    assert!(
        InputActivityProbe::new(InputActivityProbeConfig {
            idle_after_seconds: 1.0,
            max_sources: 0,
        })
        .is_err()
    );
}
