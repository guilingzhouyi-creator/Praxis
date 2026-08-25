//! Independent load-adaptive control-law tests for the Rust kernel.

use l1_kernel_rs::load_adaptive::{
    Action, ControllerConfig, ControllerMetrics, LoadAdaptiveController,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct VectorFile {
    cases: Vec<VectorCase>,
}

#[derive(Debug, Deserialize)]
struct VectorCase {
    config: ControllerConfig,
    steps: Vec<VectorStep>,
}

#[derive(Debug, Deserialize)]
struct VectorStep {
    metrics: ControllerMetrics,
    now: f64,
    expected: ExpectedDecision,
}

#[derive(Debug, Deserialize)]
struct ExpectedDecision {
    action: Action,
    target_workers: u64,
    ewma_depth: f64,
    in_cooldown: bool,
    reason: String,
}

#[test]
fn defaults_and_validation_match_python_boundary() {
    let controller = LoadAdaptiveController::default();
    assert_eq!(controller.config(), ControllerConfig::default());
    assert!(
        LoadAdaptiveController::new(ControllerConfig {
            low_ratio: 0.6,
            high_ratio: 0.2,
            ..ControllerConfig::default()
        })
        .is_err()
    );
    assert!(
        LoadAdaptiveController::new(ControllerConfig {
            ewma_alpha: 0.0,
            ..ControllerConfig::default()
        })
        .is_err()
    );
}

#[test]
fn shared_load_adaptive_vectors_match_python_reference() {
    let vectors: VectorFile = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_load_adaptive_vectors.json"
    ))
    .expect("load-adaptive fixture must be valid JSON");
    for case in vectors.cases {
        let mut controller = LoadAdaptiveController::new(case.config).expect("valid config");
        for step in case.steps {
            let actual = controller.decide(step.metrics, step.now);
            assert_eq!(actual.action, step.expected.action);
            assert_eq!(actual.target_workers, step.expected.target_workers);
            assert!((actual.ewma_depth - step.expected.ewma_depth).abs() < 1e-12);
            assert_eq!(actual.in_cooldown, step.expected.in_cooldown);
            assert_eq!(actual.reason, step.expected.reason);
        }
    }
}

#[test]
fn reset_clears_state_without_changing_config() {
    let mut controller = LoadAdaptiveController::new(ControllerConfig {
        hysteresis_samples: 1,
        cooldown_s: 0.0,
        ..ControllerConfig::default()
    })
    .expect("valid config");
    let metrics = ControllerMetrics {
        queue_ratio: 0.9,
        worker_count: 8,
        worker_max: 32,
        ..ControllerMetrics::default()
    };
    assert_eq!(controller.decide(metrics, 100.0).action, Action::Grow);
    controller.reset();
    assert_eq!(controller.state(100.0).decisions_total, 0);
    assert_eq!(controller.config().hysteresis_samples, 1);
}
