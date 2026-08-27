//! Independent declarative boot-plan mechanism tests for the Rust kernel.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use l1_kernel_rs::boot::{BootAction, BootExecutionError, BootPlan, BootPlanError, BootStepSpec};

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

#[test]
fn locked_plan_executes_handlers_in_dependency_order() {
    let mut plan = BootPlan::new();
    plan.register(BootStepSpec::new("cell", vec!["config".to_owned()]), false)
        .expect("cell");
    plan.register(BootStepSpec::new("config", Vec::new()), false)
        .expect("config");
    plan.lock();
    let calls = Arc::new(Mutex::new(Vec::new()));
    let mut handlers: BTreeMap<String, BootAction> = BTreeMap::new();
    for name in ["config", "cell"] {
        let calls = Arc::clone(&calls);
        let step = name.to_owned();
        handlers.insert(
            name.to_owned(),
            Box::new(move || {
                calls.lock().expect("calls lock").push(step.clone());
                Ok(())
            }),
        );
    }
    let report = plan.execute(handlers).expect("execute");
    assert_eq!(report.step_count, 2);
    assert_eq!(report.attempted, ["config", "cell"]);
    assert_eq!(report.completed, ["config", "cell"]);
    assert_eq!(*calls.lock().expect("calls lock"), ["config", "cell"]);
}

#[test]
fn handler_shape_is_validated_before_any_callback_runs() {
    let mut plan = BootPlan::new();
    plan.register(BootStepSpec::new("config", Vec::new()), false)
        .expect("config");
    plan.lock();
    let calls = Arc::new(Mutex::new(0_u32));
    let calls_for_handler = Arc::clone(&calls);
    let mut handlers: BTreeMap<String, BootAction> = BTreeMap::new();
    handlers.insert(
        "extra".to_owned(),
        Box::new(move || {
            *calls_for_handler.lock().expect("calls lock") += 1;
            Ok(())
        }),
    );
    assert_eq!(
        plan.execute(handlers),
        Err(BootExecutionError::MissingHandler {
            step: "config".to_owned()
        })
    );
    assert_eq!(*calls.lock().expect("calls lock"), 0);
}

#[test]
fn handler_failure_and_panic_return_completed_prefix() {
    let mut plan = BootPlan::new();
    plan.register(BootStepSpec::new("first", Vec::new()), false)
        .expect("first");
    plan.register(BootStepSpec::new("second", vec!["first".to_owned()]), false)
        .expect("second");
    plan.register(BootStepSpec::new("third", vec!["second".to_owned()]), false)
        .expect("third");
    plan.lock();

    let mut failed: BTreeMap<String, BootAction> = BTreeMap::new();
    failed.insert("first".to_owned(), Box::new(|| Ok(())));
    failed.insert(
        "second".to_owned(),
        Box::new(|| Err("dependency unavailable".to_owned())),
    );
    failed.insert("third".to_owned(), Box::new(|| Ok(())));
    assert_eq!(
        plan.execute(failed),
        Err(BootExecutionError::StepFailed {
            step: "second".to_owned(),
            reason: "dependency unavailable".to_owned(),
            completed: vec!["first".to_owned()]
        })
    );

    let mut panicked: BTreeMap<String, BootAction> = BTreeMap::new();
    panicked.insert("first".to_owned(), Box::new(|| Ok(())));
    panicked.insert("second".to_owned(), Box::new(|| panic!("boom")));
    panicked.insert("third".to_owned(), Box::new(|| Ok(())));
    assert_eq!(
        plan.execute(panicked),
        Err(BootExecutionError::StepPanicked {
            step: "second".to_owned(),
            completed: vec!["first".to_owned()]
        })
    );
}
