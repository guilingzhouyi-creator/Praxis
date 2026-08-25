//! Independent allocator and resource-limiter mechanism tests for the Rust kernel.

use l1_kernel_rs::allocator::{Allocator, AllocatorConfig, ResourceLimiter, ResourceProfile};
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::time::Duration;

#[derive(Debug, Deserialize)]
struct ResourceVector {
    config: ResourceConfig,
    profiles: Vec<ProfileVector>,
    operations: Vec<OperationVector>,
}

#[derive(Debug, Deserialize)]
struct ResourceConfig {
    default_profile: ResourceProfile,
    fallback_agent: String,
    resource_keys: Vec<String>,
    default_cost: i64,
}

#[derive(Debug, Deserialize)]
struct ProfileVector {
    agent_id: String,
    fields: BTreeMap<String, u64>,
}

#[derive(Debug, Deserialize)]
struct OperationVector {
    op: String,
    agent_id: Option<String>,
    resource: Option<String>,
    cost: Option<i64>,
    fields: Option<BTreeMap<String, u64>>,
    expected: Value,
}

fn allocator() -> Allocator {
    let defaults = BTreeMap::from([
        ("tokens".to_owned(), 100_u64),
        ("ring1".to_owned(), 20_u64),
        ("ring2".to_owned(), 20_u64),
        ("ring3".to_owned(), 20_u64),
        ("sandbox_kb".to_owned(), 50_u64),
        ("priority".to_owned(), 5_u64),
    ]);
    let config = AllocatorConfig::new(defaults, 10, 80.0, 1, "observe", "disk")
        .with_pressure_ttl(Duration::from_secs(1))
        .with_default_priority(5);
    Allocator::new(config)
}

#[test]
fn allocation_and_free_preserve_usage_shape() {
    let allocator = allocator();
    allocator.set_limit("agent-a", "tokens", 50);
    assert_eq!(
        allocator.alloc("agent-a", "tokens", 10, "", None)["remaining"],
        40
    );
    assert_eq!(allocator.free("agent-a", "tokens", 5)["freed"], 10);
    assert_eq!(allocator.usage("agent-a")["tokens"]["used"], 0);
}

#[test]
fn expired_and_observe_allocations_reclaim_before_oom() {
    let allocator = allocator();
    allocator.set_limit("agent-a", "tokens", 20);
    allocator.alloc(
        "agent-a",
        "tokens",
        10,
        "ephemeral",
        Some(Duration::from_millis(1)),
    );
    std::thread::sleep(Duration::from_millis(5));
    assert_eq!(
        allocator.alloc("agent-a", "tokens", 15, "", None)["success"],
        true
    );
    allocator.set_limit("agent-b", "tokens", 20);
    allocator.alloc("agent-b", "tokens", 20, "observe", None);
    allocator.set_limit("agent-c", "tokens", 20);
    assert_eq!(
        allocator.alloc("agent-c", "tokens", 15, "", None)["success"],
        true
    );
    assert_eq!(allocator.usage("agent-b")["tokens"]["used"], 20);
}

#[test]
fn pressure_swap_and_cleanup_are_bounded() {
    let allocator = allocator();
    allocator.set_limit("agent-a", "ring1", 10);
    allocator.set_limit("agent-a", "ring2", 10);
    allocator.alloc("agent-a", "ring1", 9, "", None);
    assert_eq!(allocator.pressure(None)["under_pressure"], true);
    assert_eq!(
        allocator.swap_out("agent-a", "ring1", "ring2", 1)["moved"],
        1
    );
    assert_eq!(allocator.usage("agent-a")["ring2"]["used"], 9);
    allocator.cleanup_agent("agent-a");
    assert_eq!(allocator.usage("agent-a")["tokens"]["used"], 0);
}

#[test]
fn resource_limiter_enforces_profiles_and_releases() {
    let limiter = ResourceLimiter::new(
        ResourceProfile::new(2, 3, 10, 100, 5),
        "default",
        vec![
            "workers".into(),
            "scouts".into(),
            "memory".into(),
            "tokens".into(),
        ],
        1,
    );
    assert_eq!(limiter.check("agent-a", "workers", None)["success"], true);
    assert_eq!(limiter.check("agent-a", "unknown", None)["success"], false);
    assert_eq!(
        limiter.check("agent-a", "workers", Some(1))["success"],
        true
    );
    assert_eq!(
        limiter.check("agent-a", "workers", Some(1))["success"],
        false
    );
    assert_eq!(limiter.release("agent-a", "workers", None)["current"], 1);
    assert_eq!(limiter.usage("agent-a")["workers"]["current"], 1);
}

#[test]
fn profile_updates_and_cleanup_do_not_leak_usage() {
    let limiter = ResourceLimiter::new(
        ResourceProfile::new(2, 3, 10, 100, 5),
        "default",
        vec![
            "workers".into(),
            "scouts".into(),
            "memory".into(),
            "tokens".into(),
        ],
        1,
    );
    let fields = BTreeMap::from([("max_workers".to_owned(), 4_u64)]);
    limiter.set_profile("agent-a", &fields);
    assert_eq!(limiter.get_profile("agent-a")["max_workers"], 4);
    limiter.check("agent-a", "workers", Some(3));
    limiter.cleanup_agent("agent-a");
    assert_eq!(limiter.usage("agent-a")["workers"]["current"], 0);
}

#[test]
fn shared_resource_vectors_match_python_reference() {
    let vector: ResourceVector = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_resource_vectors.json"
    ))
    .expect("resource fixture must be valid JSON");
    let limiter = ResourceLimiter::new(
        vector.config.default_profile,
        vector.config.fallback_agent,
        vector.config.resource_keys,
        vector.config.default_cost,
    );
    for profile in vector.profiles {
        limiter.set_profile(&profile.agent_id, &profile.fields);
    }
    for operation in vector.operations {
        let agent_id = operation.agent_id.as_deref().unwrap_or_default();
        let resource = operation.resource.as_deref().unwrap_or_default();
        let actual = match operation.op.as_str() {
            "get_profile" => limiter.get_profile(agent_id),
            "set_profile" => limiter.set_profile(agent_id, &operation.fields.unwrap_or_default()),
            "check" => limiter.check(agent_id, resource, operation.cost),
            "release" => limiter.release(agent_id, resource, operation.cost),
            "usage" => limiter.usage(agent_id),
            "all_usage" => limiter.all_usage(),
            "cleanup_agent" => limiter.cleanup_agent(agent_id),
            other => panic!("unknown resource vector operation: {other}"),
        };
        assert_eq!(
            serde_json::to_value(actual).expect("operation json"),
            operation.expected
        );
    }
}
