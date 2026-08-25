//! Independent declarative boot-plan mechanism tests for the Rust kernel.

use l1_kernel_rs::boot::{BootPlan, BootPlanError, BootStepSpec};

#[test]
fn dependency_order_is_deterministic_and_registration_is_bounded() {
    let mut plan = BootPlan::new();
    plan.register(
        BootStepSpec::new("cell", vec!["services".to_owned()]),
        false,
    )
    .expect("cell");
    plan.register(
        BootStepSpec::new("services", vec!["config".to_owned()]),
        false,
    )
    .expect("services");
    plan.register(BootStepSpec::new("config", Vec::new()), false)
        .expect("config");
    assert_eq!(
        plan.resolve_order().expect("order"),
        ["config", "services", "cell"]
    );
    assert!(matches!(
        plan.register(BootStepSpec::new("cell", Vec::new()), false),
        Err(BootPlanError::DuplicateStep { .. })
    ));
}

#[test]
fn missing_dependencies_and_cycles_fail_closed() {
    let mut missing = BootPlan::new();
    missing
        .register(
            BootStepSpec::new("cell", vec!["services".to_owned()]),
            false,
        )
        .expect("step");
    assert!(matches!(
        missing.resolve_order(),
        Err(BootPlanError::MissingDependency { .. })
    ));

    let mut cycle = BootPlan::new();
    cycle
        .register(BootStepSpec::new("a", vec!["b".to_owned()]), false)
        .expect("a");
    cycle
        .register(BootStepSpec::new("b", vec!["a".to_owned()]), false)
        .expect("b");
    assert!(matches!(
        cycle.resolve_order(),
        Err(BootPlanError::Cycle { .. })
    ));
}

#[test]
fn lock_requires_explicit_replace() {
    let mut plan = BootPlan::new();
    plan.register(BootStepSpec::new("config", Vec::new()), false)
        .expect("step");
    plan.lock();
    assert!(matches!(
        plan.register(BootStepSpec::new("new", Vec::new()), false),
        Err(BootPlanError::Locked)
    ));
    plan.register(BootStepSpec::new("config", vec!["new".to_owned()]), true)
        .expect("explicit replacement");
    assert!(plan.is_locked());
}
