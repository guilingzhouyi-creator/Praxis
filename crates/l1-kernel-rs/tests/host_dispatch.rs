//! Host dispatch integration tests: kind-by-kind routing matrix, ring-gated
//! system commands (boundary audit B4), persistent audit rows, L3 upstream
//! passthrough, session registry effects, and a canonical Result response
//! golden vector.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use l1_kernel_rs::contract::CapabilityResult;
use l1_kernel_rs::host_dispatch::{HostRouter, L3Upstream, RouterConfig, SYSTEM_COMMANDS};
use l1_kernel_rs::protocol::{Message, MessageKind, ProtocolError, decode_message, encode_message};
use l1_kernel_rs::session_lifecycle::SessionLifecycle;
use serde_json::json;

fn command(name: &str, session_id: &str, seq: u64) -> Message {
    Message::new(
        session_id,
        seq,
        MessageKind::Command,
        BTreeMap::from([("name".to_owned(), json!(name))]),
        "",
        100.0,
    )
}

fn system_command(name: &str, ring: u8, approved: bool, session_id: &str, seq: u64) -> Message {
    let mut payload = BTreeMap::from([
        ("name".to_owned(), json!(name)),
        ("ring".to_owned(), json!(ring)),
    ]);
    if approved {
        payload.insert("approved".to_owned(), json!(true));
    }
    Message::new(session_id, seq, MessageKind::Command, payload, "", 100.0)
}

fn intent(session_id: &str, text: &str, seq: u64) -> Message {
    Message::new(
        session_id,
        seq,
        MessageKind::Intent,
        BTreeMap::from([("text".to_owned(), json!(text))]),
        "",
        100.0,
    )
}

fn control(op: &str, session_id: &str, view_id: Option<&str>, seq: u64) -> Message {
    let mut payload = BTreeMap::from([
        ("op".to_owned(), json!(op)),
        ("session_id".to_owned(), json!(session_id)),
    ]);
    if let Some(view) = view_id {
        payload.insert("view_id".to_owned(), json!(view));
    }
    Message::new(session_id, seq, MessageKind::Control, payload, "", 100.0)
}

struct RecordingUpstream {
    forwarded: Mutex<Vec<Message>>,
}

impl RecordingUpstream {
    fn new() -> Self {
        Self {
            forwarded: Mutex::new(Vec::new()),
        }
    }

    fn forwarded(&self) -> Vec<Message> {
        self.forwarded.lock().unwrap().clone()
    }
}

impl L3Upstream for RecordingUpstream {
    fn forward(&self, message: Message) -> Result<(), ProtocolError> {
        self.forwarded.lock().unwrap().push(message);
        Ok(())
    }
}

#[test]
fn command_approved_dispatches_through_capability_gate() {
    let router = HostRouter::new(RouterConfig::default());
    router.register_command("hello");
    let responses = router
        .route(command("hello", "s-1", 7))
        .expect("dispatches");
    assert_eq!(responses.len(), 1);
    assert_eq!(responses[0].kind, MessageKind::Result);
    assert_eq!(responses[0].payload["success"], json!(true));
    assert_eq!(responses[0].payload["output"], json!("echo:hello"));
    assert_eq!(responses[0].session_id, "s-1");
    assert_eq!(responses[0].seq, 1);
}

#[test]
fn command_denied_by_executor_is_wrapped_as_failed_result() {
    let router = HostRouter::new(RouterConfig::default());
    router.register_command("hello");
    router.register_executor(|request| CapabilityResult {
        success: false,
        error: format!("denied:{}", request.name),
        capability: request.name,
        data: Default::default(),
    });
    let responses = router
        .route(command("hello", "s-1", 7))
        .expect("dispatches");
    assert_eq!(responses[0].payload["success"], json!(false));
    assert_eq!(responses[0].payload["output"], json!("denied:hello"));
    let denied = router
        .audit()
        .query(10, None)
        .into_iter()
        .find(|row| row.op == "dispatch.command" && !row.success)
        .expect("denied audit row");
    assert!(denied.error.contains("denied:hello"));
}

#[test]
fn unknown_command_fails_closed_and_is_audited() {
    let router = HostRouter::new(RouterConfig::default());
    let error = router
        .route(command("nonsense", "s-1", 7))
        .expect_err("unregistered command fails closed");
    assert!(error.to_string().contains("unregistered command: nonsense"));
    assert!(
        !router
            .registered_commands()
            .contains(&"nonsense".to_owned())
    );
    for name in SYSTEM_COMMANDS {
        assert!(
            router.registered_commands().contains(&name.to_owned()),
            "default registry includes system command {name}"
        );
    }
    let denied = router
        .audit()
        .query(10, None)
        .into_iter()
        .find(|row| row.op == "dispatch.command" && !row.success)
        .expect("denied audit row");
    assert!(denied.error.contains("unregistered"));
    assert!(denied.detail.contains("command=nonsense"));
}

#[test]
fn system_ring3_without_approval_is_denied_and_audited() {
    let router = HostRouter::new(RouterConfig::default());
    let error = router
        .route(system_command("status", 3, false, "s-1", 1))
        .expect_err("ring 3 without approval is denied");
    assert!(error.to_string().contains("blocked by gatechain (BLOCK)"));
    let denied = router
        .audit()
        .query(20, None)
        .into_iter()
        .find(|row| row.op == "dispatch.system" && !row.success)
        .expect("denied system audit row");
    assert!(denied.detail.contains("command=status"));
    assert!(denied.detail.contains("ring=3"));
    assert!(denied.detail.contains("decision=denied"));
    assert!(denied.error.contains("BLOCK"));
}

#[test]
fn system_ring3_with_approval_passes_and_ring1_is_safe() {
    let router = HostRouter::new(RouterConfig::default());
    let approved = router
        .route(system_command("status", 3, true, "s-1", 1))
        .expect("ring 3 with approval passes");
    assert_eq!(approved[0].payload["success"], json!(true));
    let safe = router
        .route(system_command("health", 1, false, "s-1", 2))
        .expect("ring 1 is safe by default");
    assert_eq!(safe[0].payload["success"], json!(true));
    let allowed = router
        .audit()
        .query(20, None)
        .into_iter()
        .find(|row| row.op == "dispatch.system" && row.success)
        .expect("allowed system audit row");
    assert!(allowed.detail.contains("ring=3"));
    assert!(allowed.detail.contains("decision=allowed"));
}

#[test]
fn control_attach_creates_session_record_and_view_cursor() {
    let router = HostRouter::new(RouterConfig::default());
    router
        .route(control("attach", "s-1", Some("view-a"), 1))
        .expect("attach");
    assert!(router.sessions().contains(&"s-1".to_owned()));
    assert_eq!(router.session_state("s-1"), Some(SessionLifecycle::Created));
    let cursor = router.view_cursor("s-1", "view-a").expect("view attached");
    assert_eq!(cursor.view_id, "view-a");
    assert_eq!(cursor.session_id, "s-1");
    assert!(cursor.attached);
    assert_eq!(cursor.last_acked, -1);
}

#[test]
fn ack_advances_view_cursor_monotonically() {
    let router = HostRouter::new(RouterConfig::default());
    router
        .route(control("attach", "s-1", Some("view-a"), 1))
        .expect("attach");
    let ack = Message::new(
        "s-1",
        2,
        MessageKind::Ack,
        BTreeMap::from([
            ("ack_seq".to_owned(), json!(5)),
            ("view_id".to_owned(), json!("view-a")),
        ]),
        "",
        100.0,
    );
    router.route(ack).expect("ack advances the view");
    assert_eq!(router.view_cursor("s-1", "view-a").unwrap().last_acked, 5);
    let control_ack = Message::new(
        "s-1",
        3,
        MessageKind::Control,
        BTreeMap::from([
            ("op".to_owned(), json!("ack")),
            ("session_id".to_owned(), json!("s-1")),
            ("view_id".to_owned(), json!("view-a")),
            ("ack_seq".to_owned(), json!(3)),
        ]),
        "",
        100.0,
    );
    router
        .route(control_ack)
        .expect("regressive ack is a no-op");
    assert_eq!(
        router.view_cursor("s-1", "view-a").unwrap().last_acked,
        5,
        "view ack cursor never moves backward"
    );
}

#[test]
fn control_detach_retains_the_view_cursor() {
    let router = HostRouter::new(RouterConfig::default());
    router
        .route(control("attach", "s-1", Some("view-a"), 1))
        .expect("attach");
    router
        .route(control("detach", "s-1", Some("view-a"), 2))
        .expect("detach");
    let cursor = router
        .view_cursor("s-1", "view-a")
        .expect("cursor retained");
    assert!(!cursor.attached);
    assert_eq!(cursor.last_acked, -1);
}

#[test]
fn control_recovery_replays_the_session_outbox() {
    let router = HostRouter::new(RouterConfig::default());
    router.register_command("hello");
    router.route(command("hello", "s-1", 7)).expect("dispatch");
    let recovery = Message::new(
        "s-1",
        8,
        MessageKind::Control,
        BTreeMap::from([
            ("op".to_owned(), json!("recovery")),
            ("session_id".to_owned(), json!("s-1")),
            ("last_acked".to_owned(), json!(-1)),
        ]),
        "",
        100.0,
    );
    let replayed = router.route(recovery).expect("recovery replays the outbox");
    assert_eq!(replayed.len(), 1);
    assert_eq!(replayed[0].kind, MessageKind::Result);
    assert_eq!(replayed[0].payload["success"], json!(true));
}

#[test]
fn control_resume_on_unknown_session_fails_closed() {
    let router = HostRouter::new(RouterConfig::default());
    let error = router
        .route(control("resume", "ghost", None, 1))
        .expect_err("unknown session cannot resume");
    assert!(error.to_string().contains("unknown session ghost"));
}

#[test]
fn event_result_stream_chunk_inbound_rejected() {
    let router = HostRouter::new(RouterConfig::default());
    let cases = [
        (
            MessageKind::Event,
            BTreeMap::from([("event_type".to_owned(), json!("tick"))]),
        ),
        (
            MessageKind::Result,
            BTreeMap::from([
                ("success".to_owned(), json!(true)),
                ("output".to_owned(), json!("ok")),
            ]),
        ),
        (
            MessageKind::StreamChunk,
            BTreeMap::from([("data".to_owned(), json!("partial"))]),
        ),
    ];
    for (kind, payload) in cases {
        let message = Message::new("s-1", 1, kind, payload, "", 100.0);
        let error = router
            .route(message)
            .expect_err("outbound-only kind is rejected");
        assert!(error.to_string().contains("outbound-only"), "{kind:?}");
    }
}

#[test]
fn intent_forwarded_to_upstream_and_recorded() {
    let router = HostRouter::new(RouterConfig::default());
    let upstream = Arc::new(RecordingUpstream::new());
    router.set_upstream(Some(upstream.clone()));
    let message = intent("s-1", "hello l3", 1);
    router.route(message.clone()).expect("intent forwards");
    let forwarded = upstream.forwarded();
    assert_eq!(forwarded.len(), 1);
    assert_eq!(forwarded[0], message);
    assert_eq!(router.pending_intent_count(), 0);
}

#[test]
fn intent_without_upstream_buffers_and_overflow_fails_closed() {
    let router = HostRouter::new(RouterConfig::new(2).expect("bounded buffer"));
    router.route(intent("s-1", "first", 1)).expect("buffered");
    router.route(intent("s-1", "second", 2)).expect("buffered");
    assert_eq!(router.pending_intent_count(), 2);
    assert_eq!(router.pending_intents().len(), 2);
    let error = router
        .route(intent("s-1", "third", 3))
        .expect_err("overflow fails closed");
    assert!(error.to_string().contains("intent buffer overflow"));
    assert_eq!(router.pending_intent_count(), 2);
}

#[test]
fn command_agent_id_comes_from_session_or_system() {
    let router = HostRouter::new(RouterConfig::default());
    router.register_command("hello");
    router
        .route(control("attach", "s-1", Some("view-a"), 1))
        .expect("attach");
    router.route(command("hello", "s-1", 2)).expect("dispatch");
    let row = router
        .audit()
        .query(20, None)
        .into_iter()
        .find(|row| row.op == "dispatch.command" && row.success)
        .expect("allowed command row");
    assert_eq!(row.agent_id, "s-1");

    let fresh = HostRouter::new(RouterConfig::default());
    fresh.register_command("hello");
    fresh.route(command("hello", "s-9", 1)).expect("dispatch");
    let row = fresh
        .audit()
        .query(20, None)
        .into_iter()
        .find(|row| row.op == "dispatch.command" && row.success)
        .expect("allowed command row");
    assert_eq!(row.agent_id, "system");
}

#[test]
fn audit_allowed_and_denied_dispatches_appear_with_correct_fields() {
    let router = HostRouter::new(RouterConfig::default());
    router.register_command("hello");
    router
        .route(command("hello", "s-1", 1))
        .expect("allowed command");
    router
        .route(system_command("status", 3, false, "s-1", 2))
        .expect_err("denied system command");
    router
        .route(command("nonsense", "s-1", 3))
        .expect_err("unregistered command");
    let rows = router.audit().query(20, None);
    let allowed = rows
        .iter()
        .find(|row| row.op == "dispatch.command" && row.success)
        .expect("allowed command row");
    assert!(allowed.detail.contains("command=hello"));
    assert!(allowed.detail.contains("decision=allowed"));
    assert!(allowed.success);
    let denied_system = rows
        .iter()
        .find(|row| row.op == "dispatch.system" && !row.success)
        .expect("denied system row");
    assert!(denied_system.detail.contains("command=status"));
    assert!(denied_system.detail.contains("ring=3"));
    assert!(denied_system.detail.contains("decision=denied"));
    let denied_unregistered = rows
        .iter()
        .find(|row| row.op == "dispatch.command" && !row.success)
        .expect("denied unregistered row");
    assert!(denied_unregistered.error.contains("unregistered"));
    assert!(denied_unregistered.detail.contains("decision=denied"));
    let (count, journal_errors) = router.audit_stats();
    assert!(count >= 3);
    assert_eq!(journal_errors, 0);
}

#[test]
fn result_response_golden_vector_matches_canonical_json() {
    let router = HostRouter::new(RouterConfig::default());
    router.register_command("hello");
    let responses = router.route(command("hello", "s-1", 7)).expect("dispatch");
    assert_eq!(responses.len(), 1);
    let line = encode_message(&responses[0]).expect("response encodes");
    assert_eq!(
        line,
        r#"{"kind":"result","payload":{"output":"echo:hello","success":true},"seq":1,"session_id":"s-1","trace_id":"","ts":100.0,"v":1}"#
    );
    assert_eq!(decode_message(&line).expect("decodes"), responses[0]);
}
