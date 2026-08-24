//! Independent public coverage for bounded registry snapshot pages.

use std::sync::{Arc, Barrier};
use std::thread;

use l1_kernel_rs::agent_loop::{AgentLoopBook, AgentLoopSpec};
use l1_kernel_rs::session::{SessionBook, SessionSpec};
use l1_kernel_rs::snapshot::{BOOK_SNAPSHOT_MAX_PAGE_SIZE, BookSnapshotPageError};
use l1_kernel_rs::terminal::{TerminalBook, TerminalSpec};

fn session_spec(session_id: &str) -> SessionSpec {
    SessionSpec::new(session_id, "agent-a", "cell-a", "worker", 8)
}

#[test]
fn session_book_pages_in_identity_order_without_changing_full_snapshot_behavior() {
    let book = SessionBook::new(4).expect("session book");
    for session_id in ["session-z", "session-a", "session-m", "session-b"] {
        book.create(session_spec(session_id))
            .expect("session create");
    }

    let first = book.snapshot_page(None, 2).expect("first page");
    assert_eq!(
        first
            .items
            .iter()
            .map(|snapshot| snapshot.spec.session_id.as_str())
            .collect::<Vec<_>>(),
        vec!["session-a", "session-b"]
    );
    assert_eq!(first.next_cursor.as_deref(), Some("session-b"));

    let second = book
        .snapshot_page(first.next_cursor.as_deref(), 2)
        .expect("second page");
    assert_eq!(
        second
            .items
            .iter()
            .map(|snapshot| snapshot.spec.session_id.as_str())
            .collect::<Vec<_>>(),
        vec!["session-m", "session-z"]
    );
    assert_eq!(second.next_cursor, None);
    assert_eq!(
        book.snapshots()
            .iter()
            .map(|snapshot| snapshot.spec.session_id.as_str())
            .collect::<Vec<_>>(),
        vec!["session-a", "session-b", "session-m", "session-z"]
    );
}

#[test]
fn agent_loop_book_uses_an_exclusive_cursor_and_bounded_limit() {
    let book = AgentLoopBook::new();
    for loop_id in ["loop-z", "loop-a", "loop-m"] {
        book.register(AgentLoopSpec::new(
            loop_id,
            "agent-a",
            "cell-a",
            "session-a",
            "terminal-a",
        ))
        .expect("loop register");
    }

    let first = book.snapshot_page(Some("loop-a"), 1).expect("page");
    assert_eq!(first.items[0].spec.loop_id, "loop-m");
    assert_eq!(first.next_cursor.as_deref(), Some("loop-m"));
    let second = book
        .snapshot_page(first.next_cursor.as_deref(), 1)
        .expect("page");
    assert_eq!(second.items[0].spec.loop_id, "loop-z");
    assert_eq!(second.next_cursor, None);
}

#[test]
fn terminal_book_pages_hash_backed_records_in_identity_order() {
    let book = TerminalBook::new();
    for terminal_id in ["terminal-z", "terminal-a", "terminal-m"] {
        book.register(TerminalSpec::new(terminal_id, 1, 1))
            .expect("terminal register");
    }

    let page = book.snapshot_page(None, 2).expect("page");
    assert_eq!(
        page.items
            .iter()
            .map(|snapshot| snapshot.terminal_id.as_str())
            .collect::<Vec<_>>(),
        vec!["terminal-a", "terminal-m"]
    );
    assert_eq!(page.next_cursor.as_deref(), Some("terminal-m"));
}

#[test]
fn restored_loop_and_terminal_books_rebuild_ordered_page_indexes() {
    let loops = AgentLoopBook::new();
    let loop_snapshot = loops
        .register(AgentLoopSpec::new(
            "loop-m",
            "agent-a",
            "cell-a",
            "session-a",
            "terminal-a",
        ))
        .expect("loop register");
    let restored_loops = AgentLoopBook::new();
    restored_loops.restore(loop_snapshot).expect("loop restore");
    assert_eq!(
        restored_loops
            .snapshot_page(None, 1)
            .expect("restored loop page")
            .items[0]
            .spec
            .loop_id,
        "loop-m"
    );

    let terminals = TerminalBook::new();
    let terminal_snapshot = terminals
        .register(TerminalSpec::new("terminal-m", 1, 1))
        .expect("terminal register");
    let restored_terminals = TerminalBook::new();
    restored_terminals
        .restore(terminal_snapshot)
        .expect("terminal restore");
    assert_eq!(
        restored_terminals
            .snapshot_page(None, 1)
            .expect("restored terminal page")
            .items[0]
            .terminal_id,
        "terminal-m"
    );
}

#[test]
fn book_snapshot_pages_reject_unbounded_requests() {
    let sessions = SessionBook::default();
    assert_eq!(
        sessions.snapshot_page(None, 0),
        Err(BookSnapshotPageError::InvalidLimit {
            limit: 0,
            max: BOOK_SNAPSHOT_MAX_PAGE_SIZE,
        })
    );
    assert_eq!(
        AgentLoopBook::new().snapshot_page(None, BOOK_SNAPSHOT_MAX_PAGE_SIZE + 1),
        Err(BookSnapshotPageError::InvalidLimit {
            limit: BOOK_SNAPSHOT_MAX_PAGE_SIZE + 1,
            max: BOOK_SNAPSHOT_MAX_PAGE_SIZE,
        })
    );
}

#[test]
fn maximum_page_keeps_the_smallest_identities_and_continues_after_the_cursor() {
    let book = SessionBook::new(8).expect("session book");
    for index in 0..=BOOK_SNAPSHOT_MAX_PAGE_SIZE {
        book.create(session_spec(&format!("session-{index:03}")))
            .expect("session create");
    }

    let first = book
        .snapshot_page(None, BOOK_SNAPSHOT_MAX_PAGE_SIZE)
        .expect("maximum page");
    assert_eq!(first.items.len(), BOOK_SNAPSHOT_MAX_PAGE_SIZE);
    assert_eq!(first.items[0].spec.session_id, "session-000");
    assert_eq!(
        first.items[BOOK_SNAPSHOT_MAX_PAGE_SIZE - 1].spec.session_id,
        "session-511"
    );
    assert_eq!(first.next_cursor.as_deref(), Some("session-511"));

    let final_page = book
        .snapshot_page(first.next_cursor.as_deref(), BOOK_SNAPSHOT_MAX_PAGE_SIZE)
        .expect("final page");
    assert_eq!(final_page.items.len(), 1);
    assert_eq!(final_page.items[0].spec.session_id, "session-512");
    assert_eq!(final_page.next_cursor, None);
}

#[test]
fn session_book_snapshot_pages_allow_concurrent_readers_without_order_drift() {
    let book = Arc::new(SessionBook::new(8).expect("session book"));
    for index in 0..128 {
        book.create(session_spec(&format!("session-{index:03}")))
            .expect("session create");
    }
    let barrier = Arc::new(Barrier::new(4));
    let readers = (0..4)
        .map(|_| {
            let book = Arc::clone(&book);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                for _ in 0..32 {
                    let page = book.snapshot_page(None, 16).expect("snapshot page");
                    assert_eq!(page.items.len(), 16);
                    assert_eq!(page.items[0].spec.session_id, "session-000");
                    assert_eq!(page.items[15].spec.session_id, "session-015");
                    assert_eq!(page.next_cursor.as_deref(), Some("session-015"));
                }
            })
        })
        .collect::<Vec<_>>();
    for reader in readers {
        reader.join().expect("snapshot reader joins");
    }
}

#[test]
fn session_book_snapshot_pages_keep_the_leading_page_stable_during_appended_writes() {
    let book = Arc::new(SessionBook::new(1).expect("session book"));
    for index in 0..64 {
        book.create(session_spec(&format!("session-{index:03}")))
            .expect("session create");
    }
    let barrier = Arc::new(Barrier::new(3));
    let writer_book = Arc::clone(&book);
    let writer_barrier = Arc::clone(&barrier);
    let writer = thread::spawn(move || {
        writer_barrier.wait();
        for index in 0..128 {
            writer_book
                .create(session_spec(&format!("session-zwrite-{index:03}")))
                .expect("session write");
        }
    });
    let readers = (0..2)
        .map(|_| {
            let book = Arc::clone(&book);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                for _ in 0..64 {
                    let page = book.snapshot_page(None, 16).expect("snapshot page");
                    assert_eq!(page.items.len(), 16);
                    assert_eq!(page.items[0].spec.session_id, "session-000");
                    assert_eq!(page.items[15].spec.session_id, "session-015");
                    assert_eq!(page.next_cursor.as_deref(), Some("session-015"));
                }
            })
        })
        .collect::<Vec<_>>();
    writer.join().expect("snapshot writer joins");
    for reader in readers {
        reader.join().expect("snapshot reader joins");
    }
}

#[test]
fn session_page_ordered_index_tracks_closed_removal_and_checkpoint_restore() {
    let book = SessionBook::new(1).expect("session book");
    for session_id in ["session-a", "session-b", "session-c"] {
        book.create(session_spec(session_id))
            .expect("session create");
    }
    let removed = book.get("session-b").expect("session b");
    removed.activate().expect("session activate");
    removed.close(true).expect("session close");
    let checkpoint = removed.checkpoint();
    book.remove_closed("session-b").expect("closed removal");

    let after_removal = book.snapshot_page(None, 3).expect("page after removal");
    assert_eq!(
        after_removal
            .items
            .iter()
            .map(|snapshot| snapshot.spec.session_id.as_str())
            .collect::<Vec<_>>(),
        vec!["session-a", "session-c"]
    );

    book.restore(checkpoint).expect("session restore");
    let after_restore = book.snapshot_page(None, 3).expect("page after restore");
    assert_eq!(
        after_restore
            .items
            .iter()
            .map(|snapshot| snapshot.spec.session_id.as_str())
            .collect::<Vec<_>>(),
        vec!["session-a", "session-b", "session-c"]
    );
}
