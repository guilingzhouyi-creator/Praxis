//! Golden lifecycle and registry vectors for the host session FSM.

use l1_kernel_rs::protocol::ProtocolError;
use l1_kernel_rs::session::SESSION_MAX_ID_BYTES;
use l1_kernel_rs::session_identity::SessionIdentity;
use l1_kernel_rs::session_lifecycle::{
    SessionBinding, SessionLifecycle, SessionRecord, SessionRegistry,
};

fn identity(session_id: &str) -> SessionIdentity {
    SessionIdentity::new(session_id, "term-1", "proc-1").expect("identity is valid")
}

fn record_in(state: SessionLifecycle) -> SessionRecord {
    let mut record = SessionRecord::new(identity("s-1"), 0);
    match state {
        SessionLifecycle::Created => {}
        SessionLifecycle::Ready => record
            .transition(SessionLifecycle::Ready)
            .expect("created to ready"),
        SessionLifecycle::Running => {
            record
                .transition(SessionLifecycle::Ready)
                .expect("created to ready");
            record
                .transition(SessionLifecycle::Running)
                .expect("ready to running");
        }
        SessionLifecycle::Paused => {
            record
                .transition(SessionLifecycle::Ready)
                .expect("created to ready");
            record
                .transition(SessionLifecycle::Running)
                .expect("ready to running");
            record
                .transition(SessionLifecycle::Paused)
                .expect("running to paused");
        }
        SessionLifecycle::Closing => {
            record
                .transition(SessionLifecycle::Ready)
                .expect("created to ready");
            record
                .transition(SessionLifecycle::Running)
                .expect("ready to running");
            record
                .transition(SessionLifecycle::Closing)
                .expect("running to closing");
        }
        SessionLifecycle::Stopped => {
            record
                .transition(SessionLifecycle::Ready)
                .expect("created to ready");
            record
                .transition(SessionLifecycle::Running)
                .expect("ready to running");
            record
                .transition(SessionLifecycle::Closing)
                .expect("running to closing");
            record
                .transition(SessionLifecycle::Stopped)
                .expect("closing to stopped");
        }
        SessionLifecycle::Failed => unreachable!("failed is reached by transition"),
    }
    record
}

#[test]
fn identity_rejects_empty_required_fields() {
    assert!(matches!(
        SessionIdentity::new("", "t", "p"),
        Err(ProtocolError::InvalidContract(_))
    ));
    assert!(SessionIdentity::new("s", "", "p").is_err());
    assert!(SessionIdentity::new("s", "t", "").is_err());
}

#[test]
fn identity_defaults_optional_fields() {
    let id = identity("s-1");
    assert_eq!(id.session_id, "s-1");
    assert_eq!(id.terminal_id, "term-1");
    assert_eq!(id.process_id, "proc-1");
    assert_eq!(id.user_id, "");
    assert_eq!(id.role, "");
    assert_eq!(id.cell_id, "");
    assert_eq!(id.memory_scope, "");
}

#[test]
fn identity_with_optional_sets_all_fields() {
    let id = identity("s-1").with_optional("user-1", "operator", "cell-1", "mem");
    assert_eq!(id.user_id, "user-1");
    assert_eq!(id.role, "operator");
    assert_eq!(id.cell_id, "cell-1");
    assert_eq!(id.memory_scope, "mem");
}

#[test]
fn identity_rejects_overlong_fields() {
    let overlong = "x".repeat(SESSION_MAX_ID_BYTES + 1);
    assert!(SessionIdentity::new(&overlong, "t", "p").is_err());
    assert!(SessionIdentity::new("s", &overlong, "p").is_err());
    assert!(SessionIdentity::new("s", "t", &overlong).is_err());
}

#[test]
fn lifecycle_full_walk_created_to_stopped() {
    let mut record = SessionRecord::new(identity("s-1"), 1_700_000_000);
    assert_eq!(record.state(), SessionLifecycle::Created);
    for (next, expected) in [
        (SessionLifecycle::Ready, SessionLifecycle::Ready),
        (SessionLifecycle::Running, SessionLifecycle::Running),
        (SessionLifecycle::Paused, SessionLifecycle::Paused),
        (SessionLifecycle::Running, SessionLifecycle::Running),
        (SessionLifecycle::Closing, SessionLifecycle::Closing),
        (SessionLifecycle::Stopped, SessionLifecycle::Stopped),
    ] {
        record.transition(next).expect("valid transition");
        assert_eq!(record.state(), expected);
    }
}

#[test]
fn lifecycle_rejects_invalid_transitions_and_keeps_state() {
    let mut record = SessionRecord::new(identity("s-1"), 0);
    assert!(!record.can_transition(SessionLifecycle::Paused));
    assert!(record.transition(SessionLifecycle::Paused).is_err());
    assert_eq!(record.state(), SessionLifecycle::Created);
    assert!(record.transition(SessionLifecycle::Stopped).is_err());

    record.transition(SessionLifecycle::Ready).expect("valid");
    assert!(!record.can_transition(SessionLifecycle::Created));
    assert!(record.transition(SessionLifecycle::Created).is_err());
    assert!(record.transition(SessionLifecycle::Stopped).is_err());
    assert!(record.transition(SessionLifecycle::Paused).is_err());
    assert_eq!(record.state(), SessionLifecycle::Ready);
}

#[test]
fn lifecycle_failed_is_reachable_from_every_state() {
    for state in [
        SessionLifecycle::Created,
        SessionLifecycle::Ready,
        SessionLifecycle::Running,
        SessionLifecycle::Paused,
        SessionLifecycle::Closing,
        SessionLifecycle::Stopped,
    ] {
        let mut record = record_in(state);
        record
            .transition(SessionLifecycle::Failed)
            .expect("any state may fail");
        assert_eq!(record.state(), SessionLifecycle::Failed);
    }
}

#[test]
fn lifecycle_failed_is_terminal() {
    let mut record = record_in(SessionLifecycle::Running);
    record
        .transition(SessionLifecycle::Failed)
        .expect("running to failed");
    assert_eq!(record.state(), SessionLifecycle::Failed);
    for target in [
        SessionLifecycle::Created,
        SessionLifecycle::Ready,
        SessionLifecycle::Running,
        SessionLifecycle::Paused,
        SessionLifecycle::Closing,
        SessionLifecycle::Stopped,
        SessionLifecycle::Failed,
    ] {
        assert!(!record.can_transition(target));
        assert!(record.transition(target).is_err());
        assert_eq!(record.state(), SessionLifecycle::Failed);
    }
}

#[test]
fn record_holds_created_at_and_binding() {
    let mut record = SessionRecord::new(identity("s-1"), 1_700_000_000);
    assert_eq!(record.created_at, 1_700_000_000);
    assert!(record.binding.is_none());
    let binding = SessionBinding::new("term-x", "proc-y").expect("binding is valid");
    record.bind(binding.clone());
    assert_eq!(record.binding, Some(binding));
    record.unbind();
    assert!(record.binding.is_none());
}

#[test]
fn session_binding_rejects_empty_fields() {
    assert!(SessionBinding::new("", "p").is_err());
    assert!(SessionBinding::new("t", "").is_err());
}

#[test]
fn views_attach_detach_are_session_scoped() {
    let mut record = SessionRecord::new(identity("s-1"), 0);
    record.attach_view("view-a");
    record.attach_view("view-b");
    assert_eq!(record.view_count(), 2);
    assert_eq!(record.list_views().len(), 2);
    let attached = record.view("view-a").expect("view-a registered");
    assert_eq!(attached.view_id, "view-a");
    assert_eq!(attached.session_id, "s-1");
    assert_eq!(attached.last_acked, -1);
    assert!(attached.attached);

    assert!(record.detach_view("view-a"));
    assert!(!record.detach_view("missing"));
    let detached = record.view("view-a").expect("cursor retained on detach");
    assert!(!detached.attached);
}

#[test]
fn view_ack_is_monotonic_across_reattach() {
    let mut record = SessionRecord::new(identity("s-1"), 0);
    record.attach_view("view-a");
    record.ack_view("view-a", 5);
    record.ack_view("view-a", 3);
    assert_eq!(record.view("view-a").unwrap().last_acked, 5);
    record.detach_view("view-a");
    record.attach_view("view-a");
    let cursor = record.view("view-a").expect("re-attached");
    assert!(cursor.attached);
    assert_eq!(cursor.last_acked, 5);
}

#[test]
fn views_are_isolated_between_sessions() {
    let mut registry = SessionRegistry::new();
    registry.create(identity("s-1")).unwrap();
    registry.create(identity("s-2")).unwrap();
    {
        let first = registry.get_mut("s-1").expect("s-1 present");
        first.attach_view("view-a");
        first.ack_view("view-a", 7);
        first.detach_view("view-a");
    }
    {
        let second = registry.get_mut("s-2").expect("s-2 present");
        second.attach_view("view-a");
        assert!(second.view("view-a").unwrap().attached);
        assert_eq!(second.view("view-a").unwrap().last_acked, -1);
        assert_eq!(second.view_count(), 1);
    }
    let first = registry.get("s-1").expect("s-1 still present");
    assert_eq!(first.view_count(), 1);
    assert!(!first.view("view-a").unwrap().attached);
}

#[test]
fn registry_create_get_remove_list() {
    let mut registry = SessionRegistry::new();
    assert!(registry.is_empty());
    registry.create(identity("s-1")).unwrap();
    registry.create(identity("s-2")).unwrap();
    assert_eq!(registry.len(), 2);
    assert_eq!(registry.list_ids(), ["s-1", "s-2"]);
    assert!(registry.get("s-1").is_some());
    assert!(registry.get("missing").is_none());

    assert!(registry.remove("s-1"));
    assert!(!registry.remove("s-1"));
    assert_eq!(registry.list_ids(), ["s-2"]);
    assert!(registry.get("s-1").is_none());
}

#[test]
fn registry_rejects_invalid_identity_and_duplicates() {
    let mut registry = SessionRegistry::new();
    let invalid = SessionIdentity {
        session_id: String::new(),
        terminal_id: "t".to_owned(),
        process_id: "p".to_owned(),
        user_id: String::new(),
        role: String::new(),
        cell_id: String::new(),
        memory_scope: String::new(),
    };
    assert!(registry.create(invalid).is_err());
    assert!(registry.is_empty());

    registry.create(identity("s-1")).unwrap();
    assert!(matches!(
        registry.create(identity("s-1")),
        Err(ProtocolError::InvalidContract(_))
    ));
    assert_eq!(registry.len(), 1);
}

#[test]
fn registry_create_at_is_deterministic_and_mutable() {
    let mut registry = SessionRegistry::new();
    registry.create_at(identity("s-1"), 1_700_000_000).unwrap();
    assert_eq!(registry.get("s-1").unwrap().created_at, 1_700_000_000);
    assert_eq!(
        registry.get("s-1").unwrap().state(),
        SessionLifecycle::Created
    );
    registry
        .get_mut("s-1")
        .expect("s-1 present")
        .transition(SessionLifecycle::Ready)
        .expect("created to ready");
    assert_eq!(
        registry.get("s-1").unwrap().state(),
        SessionLifecycle::Ready
    );
}
