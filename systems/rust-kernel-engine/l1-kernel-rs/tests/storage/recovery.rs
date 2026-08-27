//! Independent tests for the Rust recovery decision boundary.

use l1_kernel_rs::execution_store::ExecutionStoreDocument;
use l1_kernel_rs::lifecycle::LifecycleState;
use l1_kernel_rs::recovery::{RecoveryAction, RecoveryTrigger};

fn document(clean_shutdown: bool, generation: u64) -> ExecutionStoreDocument {
    ExecutionStoreDocument {
        store_version: 1,
        generation,
        clean_shutdown,
        sessions: Vec::new(),
        terminals: Vec::new(),
        loops: Vec::new(),
    }
}

#[test]
fn fresh_decision_requires_halted_lifecycle() {
    assert_eq!(
        RecoveryTrigger::decide(LifecycleState::Halted, None).action,
        RecoveryAction::Fresh
    );
    assert_eq!(
        RecoveryTrigger::decide(LifecycleState::Active, None).action,
        RecoveryAction::Reject
    );
}

#[test]
fn clean_document_is_resumable_only_when_halted() {
    let document = document(true, 4);
    let decision = RecoveryTrigger::decide(LifecycleState::Halted, Some(&document));
    assert_eq!(decision.action, RecoveryAction::ResumeClean);
    assert_eq!(decision.generation, 4);
    assert_eq!(
        RecoveryTrigger::decide(LifecycleState::Crashed, Some(&document)).action,
        RecoveryAction::Reject
    );
}

#[test]
fn unclean_document_requires_crashed_lifecycle() {
    let document = document(false, 5);
    let decision = RecoveryTrigger::decide(LifecycleState::Crashed, Some(&document));
    assert_eq!(decision.action, RecoveryAction::RecoverUnclean);
    assert!(decision.reason.contains("explicit recovery"));
    assert_eq!(
        RecoveryTrigger::decide(LifecycleState::Halted, Some(&document)).action,
        RecoveryAction::Reject
    );
}

#[test]
fn empty_document_is_fresh_only_at_generation_zero() {
    let empty = document(true, 0);
    assert_eq!(
        RecoveryTrigger::decide(LifecycleState::Halted, Some(&empty)).action,
        RecoveryAction::Fresh
    );
    let nonempty = document(true, 1);
    assert_eq!(
        RecoveryTrigger::decide(LifecycleState::Halted, Some(&nonempty)).action,
        RecoveryAction::ResumeClean
    );
}
