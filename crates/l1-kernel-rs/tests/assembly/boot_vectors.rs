//! Cross-language dependency vectors for the declarative Rust boot plan.

use l1_kernel_rs::boot::{BootPlan, BootPlanError, BootStepSpec};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct BootVectors {
    valid_steps: Vec<BootStepSpec>,
    expected_order: Vec<String>,
    cycle_steps: Vec<BootStepSpec>,
    missing_steps: Vec<BootStepSpec>,
    python_missing_order: Vec<String>,
}

fn register_all(plan: &mut BootPlan, steps: Vec<BootStepSpec>) {
    for step in steps {
        plan.register(step, false).expect("valid registration");
    }
}

#[test]
fn shared_boot_plan_vectors_match_rust_boundary() {
    let vectors: BootVectors = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_boot_plan_vectors.json"
    ))
    .expect("valid boot plan vectors");

    let mut valid = BootPlan::new();
    register_all(&mut valid, vectors.valid_steps);
    assert_eq!(
        valid.resolve_order().expect("valid order"),
        vectors.expected_order
    );

    let mut cycle = BootPlan::new();
    register_all(&mut cycle, vectors.cycle_steps);
    assert!(matches!(
        cycle.resolve_order(),
        Err(BootPlanError::Cycle { .. })
    ));

    let mut missing = BootPlan::new();
    register_all(&mut missing, vectors.missing_steps);
    assert!(matches!(
        missing.resolve_order(),
        Err(BootPlanError::MissingDependency { .. })
    ));
    assert_eq!(vectors.python_missing_order, ["cell"]);
}
