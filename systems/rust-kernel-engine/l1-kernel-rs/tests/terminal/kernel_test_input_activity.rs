//! Independent aggregate input-activity probe tests for the Rust kernel.

use std::sync::{Arc, Mutex};

use l1_kernel_rs::input_activity::{
    CompositeInputActivityAdapter, HostInputActivityPort, InputActivityHostAdapter,
    InputActivityHostSample, InputActivityObservation, InputActivityPermission, InputActivityProbe,
    InputActivityProbeConfig,
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
        "../../../../../tests/fixtures/kernel_input_activity_vectors.json"
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

struct FakeHostAdapter {
    start_permission: Mutex<InputActivityPermission>,
    sample: Mutex<Option<Result<InputActivityHostSample, InputActivityPermission>>>,
    stops: Mutex<usize>,
}

impl Default for FakeHostAdapter {
    fn default() -> Self {
        Self {
            start_permission: Mutex::new(InputActivityPermission::Unavailable),
            sample: Mutex::new(None),
            stops: Mutex::new(0),
        }
    }
}

impl InputActivityHostAdapter for FakeHostAdapter {
    fn start(&self) -> InputActivityPermission {
        *self.start_permission.lock().expect("start permission lock")
    }

    fn stop(&self) {
        *self.stops.lock().expect("stop lock") += 1;
    }

    fn sample(&self) -> Result<InputActivityHostSample, InputActivityPermission> {
        self.sample
            .lock()
            .expect("sample lock")
            .clone()
            .unwrap_or(Err(InputActivityPermission::Unavailable))
    }
}

#[test]
fn host_input_port_models_permission_and_aggregate_lifecycle() {
    let adapter = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Ok(InputActivityHostSample {
            now: 12.0,
            observations: vec![InputActivityObservation::new(
                "keyboard",
                InputActivityPermission::Granted,
                true,
                false,
                11.5,
            )],
        }))),
        stops: Mutex::new(0),
    });
    let port = HostInputActivityPort::new(InputActivityProbeConfig::default(), adapter.clone())
        .expect("port");
    assert!(port.start());
    let snapshot = port.snapshot().expect("snapshot");
    assert_eq!(snapshot.source, "host-adapter");
    assert_eq!(snapshot.permission, "granted");
    assert!(snapshot.keyboard_active);
    assert!(!snapshot.pointer_active);
    port.stop();
    let stopped = port.snapshot().expect("stopped snapshot");
    assert_eq!(
        stopped.state,
        l1_kernel_rs::ports::InputActivityState::Unknown
    );
    assert_eq!(stopped.permission, "unavailable");
    assert_eq!(*adapter.stops.lock().expect("stop lock"), 1);
}

#[test]
fn host_input_port_degrades_denial_and_stops_on_invalid_sample() {
    let denied = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Denied),
        ..FakeHostAdapter::default()
    });
    let denied_port =
        HostInputActivityPort::new(InputActivityProbeConfig::default(), denied.clone())
            .expect("denied port");
    assert!(!denied_port.start());
    assert_eq!(
        denied_port.snapshot().expect("denied snapshot").permission,
        "denied"
    );

    let invalid = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Ok(InputActivityHostSample {
            now: 5.0,
            observations: vec![InputActivityObservation::new(
                "pointer",
                InputActivityPermission::Granted,
                false,
                true,
                6.0,
            )],
        }))),
        ..FakeHostAdapter::default()
    });
    let invalid_port =
        HostInputActivityPort::new(InputActivityProbeConfig::default(), invalid.clone())
            .expect("invalid port");
    assert!(invalid_port.start());
    assert!(invalid_port.snapshot().is_err());
    assert_eq!(*invalid.stops.lock().expect("stop lock"), 1);
    assert_eq!(
        invalid_port.snapshot().expect("failed snapshot").permission,
        "unavailable"
    );
}

#[test]
fn host_input_port_stops_when_permission_is_revoked_during_sampling() {
    let adapter = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Err(InputActivityPermission::Denied))),
        ..FakeHostAdapter::default()
    });
    let port = HostInputActivityPort::new(InputActivityProbeConfig::default(), adapter.clone())
        .expect("port");
    assert!(port.start());
    let snapshot = port.snapshot().expect("permission snapshot");
    assert_eq!(
        snapshot.state,
        l1_kernel_rs::ports::InputActivityState::Unknown
    );
    assert_eq!(snapshot.permission, "denied");
    assert_eq!(*adapter.stops.lock().expect("stop lock"), 1);
    assert_eq!(
        port.snapshot().expect("stopped snapshot").permission,
        "denied"
    );
}

#[test]
fn host_input_port_rejects_granted_permission_sample_errors() {
    let adapter = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Err(InputActivityPermission::Granted))),
        ..FakeHostAdapter::default()
    });
    let port = HostInputActivityPort::new(InputActivityProbeConfig::default(), adapter.clone())
        .expect("port");
    assert!(port.start());
    assert_eq!(
        port.snapshot().expect_err("invalid sample error"),
        l1_kernel_rs::input_activity::InputActivityProbeError::InvalidObservation {
            source: "host-adapter".to_owned(),
            reason: "sample failure cannot report granted permission".to_owned(),
        }
    );
    assert_eq!(
        port.snapshot().expect("stopped snapshot").permission,
        "unavailable"
    );
    assert_eq!(*adapter.stops.lock().expect("stop count"), 1);
}

#[test]
fn composite_host_adapter_merges_granted_keyboard_and_pointer_sources() {
    let keyboard = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Ok(InputActivityHostSample {
            now: 12.0,
            observations: vec![InputActivityObservation::new(
                "keyboard",
                InputActivityPermission::Granted,
                true,
                false,
                11.5,
            )],
        }))),
        ..FakeHostAdapter::default()
    });
    let pointer = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Ok(InputActivityHostSample {
            now: 11.0,
            observations: vec![InputActivityObservation::new(
                "pointer",
                InputActivityPermission::Granted,
                false,
                true,
                10.5,
            )],
        }))),
        ..FakeHostAdapter::default()
    });
    let composite =
        Arc::new(CompositeInputActivityAdapter::new(vec![keyboard, pointer]).expect("composite"));
    assert_eq!(composite.source_count(), 2);
    let port =
        HostInputActivityPort::new(InputActivityProbeConfig::default(), composite).expect("port");
    assert!(port.start());
    let snapshot = port.snapshot().expect("snapshot");
    assert_eq!(
        snapshot.state,
        l1_kernel_rs::ports::InputActivityState::Active
    );
    assert_eq!(snapshot.permission, "granted");
    assert!(snapshot.keyboard_active);
    assert!(snapshot.pointer_active);
    assert_eq!(snapshot.last_activity_at, 11.5);
}

#[test]
fn composite_host_adapter_keeps_granted_sources_when_one_source_is_denied() {
    let keyboard = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Ok(InputActivityHostSample {
            now: 12.0,
            observations: vec![InputActivityObservation::new(
                "keyboard",
                InputActivityPermission::Granted,
                true,
                false,
                11.5,
            )],
        }))),
        ..FakeHostAdapter::default()
    });
    let pointer = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Denied),
        ..FakeHostAdapter::default()
    });
    let pointer_for_assert = Arc::clone(&pointer);
    let composite =
        Arc::new(CompositeInputActivityAdapter::new(vec![keyboard, pointer]).expect("composite"));
    let port =
        HostInputActivityPort::new(InputActivityProbeConfig::default(), composite).expect("port");
    assert!(port.start());
    let snapshot = port.snapshot().expect("keyboard snapshot");
    assert_eq!(snapshot.permission, "granted");
    assert!(snapshot.keyboard_active);
    assert!(!snapshot.pointer_active);
    assert_eq!(*pointer_for_assert.stops.lock().expect("stop count"), 0);
}

#[test]
fn composite_host_adapter_drops_a_revoked_source_without_losing_others() {
    let keyboard = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Ok(InputActivityHostSample {
            now: 12.0,
            observations: vec![InputActivityObservation::new(
                "keyboard",
                InputActivityPermission::Granted,
                true,
                false,
                11.5,
            )],
        }))),
        ..FakeHostAdapter::default()
    });
    let pointer = Arc::new(FakeHostAdapter {
        start_permission: Mutex::new(InputActivityPermission::Granted),
        sample: Mutex::new(Some(Err(InputActivityPermission::Denied))),
        ..FakeHostAdapter::default()
    });
    let pointer_for_assert = Arc::clone(&pointer);
    let composite =
        Arc::new(CompositeInputActivityAdapter::new(vec![keyboard, pointer]).expect("composite"));
    let port =
        HostInputActivityPort::new(InputActivityProbeConfig::default(), composite).expect("port");
    assert!(port.start());
    let snapshot = port.snapshot().expect("keyboard snapshot");
    assert_eq!(snapshot.permission, "granted");
    assert!(snapshot.keyboard_active);
    assert!(!snapshot.pointer_active);
    assert_eq!(*pointer_for_assert.stops.lock().expect("stop count"), 1);
}

#[test]
fn composite_host_adapter_rejects_empty_source_sets() {
    assert!(CompositeInputActivityAdapter::new(Vec::new()).is_err());
}
