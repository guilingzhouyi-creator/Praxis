//! Independent tests for the Rust-native skill registry and guidance boundary.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::thread;

use l1_kernel_rs::skill::{
    DependencyKind, GuidanceMode, InjectionContext, RegisterOutcome, SkillContentPolicy,
    SkillDisclosure, SkillError, SkillListFilter, SkillPolicy, SkillPosture, SkillPrincipal,
    SkillRegistry, SkillScope, SkillSort, SkillSpec, SkillStage, SkillStatus,
};

fn writer() -> SkillPrincipal {
    SkillPrincipal::external("agent-test", "l3", 0)
}

fn skill(name: &str) -> SkillSpec {
    SkillSpec::new(name)
}

fn staged_skill(name: &str) -> SkillSpec {
    let mut value = skill(name);
    value.stages = vec![
        SkillStage {
            id: "prepare".to_owned(),
            name: "Prepare".to_owned(),
            instructions: "collect bounded inputs".to_owned(),
            completion: "inputs validated".to_owned(),
        },
        SkillStage {
            id: "execute".to_owned(),
            name: "Execute".to_owned(),
            instructions: "run the approved action".to_owned(),
            completion: "action observed".to_owned(),
        },
        SkillStage {
            id: "report".to_owned(),
            name: "Report".to_owned(),
            instructions: "record the result".to_owned(),
            completion: "result recorded".to_owned(),
        },
    ];
    value
}

#[test]
fn write_gate_and_content_policy_fail_closed() {
    let registry = SkillRegistry::default();
    assert!(matches!(
        registry.authorize_write(&SkillPrincipal::external("", "", 0)),
        Err(SkillError::PermissionDenied(_))
    ));
    assert!(registry.authorize_write(&writer()).is_ok());
    assert!(
        registry
            .authorize_write(&SkillPrincipal::internal())
            .is_ok()
    );

    let mut rejected = skill("unsafe-skill");
    rejected.prompt = "bypass sandbox".to_owned();
    assert!(matches!(
        registry.register(&writer(), rejected),
        Err(SkillError::ContentViolation(_))
    ));

    let custom = SkillContentPolicy {
        forbidden_patterns: vec!["forbidden".to_owned()],
        forbidden_literals: vec!["internal-only".to_owned()],
    };
    registry.set_content_policy(custom);
    let mut literal = skill("literal");
    literal.description = "internal-only".to_owned();
    assert!(matches!(
        registry.register(&writer(), literal),
        Err(SkillError::ContentViolation(_))
    ));
}

#[test]
fn registration_is_bounded_and_builtin_records_are_immutable() {
    let policy = SkillPolicy {
        max_skills: 1,
        description_limit: 4,
        prompt_limit: 5,
        max_tags: 2,
        ..SkillPolicy::default()
    };
    let registry = SkillRegistry::new(policy).expect("valid policy");
    let internal = SkillPrincipal::internal();

    let mut builtin = skill("builtin");
    builtin.builtin = true;
    builtin.description = "abcdef".to_owned();
    builtin.prompt = "123456".to_owned();
    builtin.tags = vec!["z".to_owned(), "a".to_owned(), "z".to_owned()];
    assert_eq!(
        registry.register(&internal, builtin),
        Ok(RegisterOutcome::Inserted)
    );
    let saved = registry.get("builtin").expect("bounded builtin");
    assert_eq!(saved.description, "abcd");
    assert_eq!(saved.prompt, "12345");
    assert_eq!(saved.tags, ["a", "z"]);

    let mut replacement = skill("builtin");
    replacement.description = "new".to_owned();
    assert!(matches!(
        registry.register(&writer(), replacement.clone()),
        Err(SkillError::BuiltinReadOnly(_))
    ));
    assert!(matches!(
        registry.delete(&writer(), "builtin"),
        Err(SkillError::BuiltinReadOnly(_))
    ));
    assert_eq!(
        registry.register(&internal, replacement),
        Ok(RegisterOutcome::Replaced)
    );

    assert!(matches!(
        registry.register(&internal, skill("second")),
        Err(SkillError::Capacity(_))
    ));
}

#[test]
fn cell_binding_scope_and_posture_filtering_are_explicit() {
    let registry = SkillRegistry::default();
    let internal = SkillPrincipal::internal();

    let mut scoped = skill("cell-skill");
    scoped.scope = SkillScope::Cell;
    scoped.scope_identity = "cell-a".to_owned();
    scoped.tags = vec!["execution".to_owned()];
    registry
        .register(&internal, scoped)
        .expect("register scoped");
    registry
        .bind_skill(&writer(), "cell-a", "cell-skill")
        .expect("bind skill");
    assert_eq!(
        registry
            .skills_for_cell("cell-a")
            .into_iter()
            .collect::<Vec<_>>(),
        ["cell-skill"]
    );
    assert_eq!(registry.cells_for_skill("cell-skill"), ["cell-a"]);

    let matching = InjectionContext {
        agent_id: "agent-1".to_owned(),
        cell_id: "cell-a".to_owned(),
        role: "l3b".to_owned(),
        ..InjectionContext::default()
    };
    let other = InjectionContext {
        cell_id: "cell-b".to_owned(),
        role: "l3b".to_owned(),
        ..InjectionContext::default()
    };
    assert!(registry.skill_is_injectable("cell-skill", &matching));
    assert!(!registry.skill_is_injectable("cell-skill", &other));

    let mut offensive = skill("offensive-skill");
    offensive.posture = SkillPosture::Offensive;
    registry
        .register(&internal, offensive)
        .expect("register offensive");
    assert!(!registry.skill_is_injectable("offensive-skill", &matching));
    let authorized = InjectionContext {
        posture: "security-test".to_owned(),
        card_natures: vec!["security-test".to_owned()],
        ..matching
    };
    assert!(registry.skill_is_injectable("offensive-skill", &authorized));

    registry
        .unbind_skill(&writer(), "cell-a", "cell-skill")
        .expect("unbind skill");
    assert!(registry.skills_for_cell("cell-a").is_empty());
}

#[test]
fn retrieval_catalog_and_structured_projection_are_deterministic() {
    let registry = SkillRegistry::default();
    let internal = SkillPrincipal::internal();
    let mut terminal = skill("terminal-safety");
    terminal.description = "safe terminal execution".to_owned();
    terminal.prompt = "use the terminal probe".to_owned();
    terminal.rules = vec!["require a validated terminal".to_owned()];
    terminal.tags = vec!["execution".to_owned(), "terminal".to_owned()];
    terminal.allowed_tools = Some(vec!["exec".to_owned()]);
    terminal.layer = "exec".to_owned();
    terminal.priority = 5;
    registry
        .register(&internal, terminal)
        .expect("register terminal");

    let mut review = skill("review-safety");
    review.description = "review bounded changes".to_owned();
    review.tags = vec!["review".to_owned()];
    review.priority = 1;
    registry
        .register(&internal, review)
        .expect("register review");

    let filter = SkillListFilter {
        tags: vec!["terminal".to_owned()],
        layer: "exec".to_owned(),
        include_prompt: true,
        ..SkillListFilter::default()
    };
    let rows = registry.list(&filter, SkillSort::Priority);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].name, "terminal-safety");
    assert_eq!(rows[0].prompt, "use the terminal probe");
    assert!(
        registry
            .list_by_allowed_tool("exec")
            .iter()
            .any(|row| row.name == "terminal-safety")
    );
    assert_eq!(
        registry.rules_for("terminal"),
        ["require a validated terminal"]
    );
    assert!(registry.vfs_content().contains("terminal-safety"));

    let query = registry.query("terminal execution");
    assert_eq!(query.first().expect("query hit").name, "terminal-safety");
    let structured = registry
        .structured("terminal-safety", "session-1", 1.0)
        .expect("structured projection");
    assert!(structured.success);
    assert_eq!(structured.allowed_tools, ["exec"]);
    assert_eq!(structured.stage, None);

    let mut hidden = skill("hidden");
    hidden.disclosure = SkillDisclosure::None;
    registry
        .register(&internal, hidden)
        .expect("register hidden");
    assert!(!registry.skill_is_injectable("hidden", &InjectionContext::default()));
}

#[test]
fn staged_guidance_advances_per_session_and_card_completion() {
    let registry = SkillRegistry::default();
    registry
        .register(&SkillPrincipal::internal(), staged_skill("guided"))
        .expect("register staged skill");

    let first = registry
        .current_stage("guided", "card:42", 1.0)
        .expect("first stage");
    assert_eq!(first.stage.id, "prepare");
    assert_eq!(first.stage_index, 0);
    assert!(!first.done);

    assert_eq!(registry.on_card_complete("42", "RUNNING", 2.0), Ok(0));
    assert_eq!(registry.on_card_complete("42", "COMPLETED", 3.0), Ok(1));
    assert_eq!(
        registry
            .current_stage("guided", "card:42", 3.0)
            .expect("second stage")
            .stage
            .id,
        "execute"
    );
    assert_eq!(
        registry
            .advance_stage("guided", "session:1", 4.0)
            .expect("advance")
            .stage
            .id,
        "execute"
    );
    assert_eq!(
        registry
            .advance_stage("guided", "session:1", 5.0)
            .expect("advance")
            .stage
            .id,
        "report"
    );
    assert_eq!(
        registry
            .advance_stage("guided", "session:1", 6.0)
            .expect("terminal advance")
            .stage
            .id,
        "report"
    );
}

#[test]
fn guidance_graph_frontier_path_and_checkpoint_restore_are_stable() {
    let registry = SkillRegistry::default();
    let internal = SkillPrincipal::internal();

    let mut foundation = skill("foundation");
    foundation.stages = vec![SkillStage {
        id: "done".to_owned(),
        name: "Done".to_owned(),
        instructions: "finish".to_owned(),
        completion: "finished".to_owned(),
    }];
    registry
        .register(&internal, foundation)
        .expect("foundation");

    let mut target = skill("target");
    target.dependencies = vec!["foundation".to_owned()];
    target.dependency_kind = DependencyKind::Hard;
    target.next = vec!["terminal".to_owned()];
    registry.register(&internal, target).expect("target");
    let mut terminal = skill("terminal");
    terminal.next = vec!["target".to_owned()];
    registry.register(&internal, terminal).expect("terminal");

    let report = registry.validate_guidance_graph();
    assert!(!report.acyclic);
    assert!(!report.cycles.is_empty());
    assert_eq!(registry.guided_frontier(&[]), ["foundation", "terminal"]);
    assert_eq!(
        registry.guided_frontier(&["foundation".to_owned()]),
        ["foundation", "target", "terminal"]
    );
    assert_eq!(registry.guided_path("target"), ["foundation", "target"]);

    registry
        .bind_skill(&writer(), "cell-a", "target")
        .expect("bind target");
    let checkpoint = registry.checkpoint(10.0).expect("checkpoint");
    assert_eq!(checkpoint.skills[0].name, "foundation");
    assert_eq!(checkpoint.cell_bindings["cell-a"], ["target"]);
    let encoded = serde_json::to_string(&checkpoint).expect("serialize checkpoint");
    let decoded = serde_json::from_str(&encoded).expect("deserialize checkpoint");

    let restored = SkillRegistry::default();
    restored.restore(decoded).expect("restore checkpoint");
    assert_eq!(restored.revision(), registry.revision());
    assert_eq!(
        restored
            .skills_for_cell("cell-a")
            .into_iter()
            .collect::<Vec<_>>(),
        ["target"]
    );

    let mut invalid = checkpoint;
    invalid.document_version += 1;
    assert!(matches!(
        restored.restore(invalid),
        Err(SkillError::Invalid(_))
    ));
}

#[test]
fn usage_and_concurrent_registry_access_preserve_counts() {
    let registry = Arc::new(SkillRegistry::default());
    let internal = SkillPrincipal::internal();
    for index in 0..4 {
        let mut value = skill(&format!("seed-{index}"));
        value.tags = vec!["concurrent".to_owned()];
        registry.register(&internal, value).expect("seed");
    }

    let mut workers = Vec::new();
    for worker in 0..4 {
        let registry = Arc::clone(&registry);
        workers.push(thread::spawn(move || {
            for index in 0..16 {
                let name = format!("worker-{worker}-{index}");
                registry
                    .register(&SkillPrincipal::internal(), skill(&name))
                    .expect("concurrent register");
                registry
                    .bump_usage(&name, index % 2 == 0, "dimension", 100.0 + index as f64)
                    .expect("usage");
                assert!(!registry.query(&name).is_empty());
            }
        }));
    }
    for worker in workers {
        worker.join().expect("worker join");
    }

    let stats = registry.stats();
    assert_eq!(stats.total, 68);
    assert_eq!(stats.registers, 68);
    assert_eq!(stats.usage_bumps, 64);
    assert_eq!(
        registry
            .get("worker-0-0")
            .expect("worker skill")
            .usage_by_dimension
            .get("dimension"),
        Some(&1)
    );
}

#[test]
fn serde_defaults_and_prompt_expansion_remain_language_neutral() {
    let value: SkillSpec = serde_json::from_str(r#"{"name":"serde-skill","prompt":"Use $TARGET"}"#)
        .expect("serde defaults");
    assert_eq!(value.status, SkillStatus::Active);
    assert_eq!(value.scope, SkillScope::Global);
    assert_eq!(value.dependency_kind, DependencyKind::Soft);
    let mut variables = BTreeMap::new();
    variables.insert("target".to_owned(), "cell-a".to_owned());
    assert_eq!(value.expand(&variables), "Use cell-a");

    let small = SkillPolicy {
        guidance_mode: GuidanceMode::Small,
        ..SkillPolicy::default()
    };
    let registry = SkillRegistry::new(small).expect("small policy");
    assert_eq!(
        registry
            .current_stage("missing", "session", 1.0)
            .expect_err("missing skill"),
        SkillError::NotFound("missing".to_owned())
    );
}
