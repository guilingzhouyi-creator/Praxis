//! Independent peer-book mechanism tests for the Rust kernel.

use l1_kernel_rs::network::{PeerAnnouncement, PeerBook, PeerPolicy};

fn announcement(peer_id: &str) -> PeerAnnouncement {
    PeerAnnouncement::new(peer_id, "127.0.0.1", 9000)
}

#[test]
fn self_announces_are_ignored_and_endpoints_are_validated() {
    let mut book = PeerBook::new("self", PeerPolicy::default()).expect("valid book");
    let observation = book.announce(announcement("self"), 100).expect("announce");
    assert!(observation.ignored_self);
    assert!(book.is_empty());
    assert!(
        book.announce(PeerAnnouncement::new("peer", "", 9000), 100)
            .is_err()
    );
    assert!(
        book.announce(PeerAnnouncement::new("peer", "127.0.0.1", 0), 100)
            .is_err()
    );
}

#[test]
fn lifecycle_reports_loss_once_then_evicts() {
    let mut book = PeerBook::default();
    book.announce(announcement("peer-a"), 100_000)
        .expect("announce a");
    book.announce(announcement("peer-b"), 150_000)
        .expect("announce b");
    assert_eq!(book.health(150_000).peers_alive, 2);
    let dead = book.health(160_100);
    assert_eq!(dead.observation.lost, ["peer-a"]);
    assert_eq!(dead.peers_dead, 1);
    book.announce(announcement("peer-b"), 350_000)
        .expect("refresh b");
    let evicted = book.health(400_100);
    assert_eq!(evicted.observation.evicted, ["peer-a"]);
    assert_eq!(evicted.peers_total, 1);
    assert_eq!(evicted.peers_alive, 1);
}

#[test]
fn list_is_newest_first_and_policy_is_explicit() {
    let policy = PeerPolicy {
        timeout_ms: 10,
        evict_after_ms: 20,
    };
    let mut book = PeerBook::new("self", policy).expect("valid policy");
    book.announce(announcement("b"), 100).expect("announce b");
    book.announce(announcement("a"), 100).expect("announce a");
    assert_eq!(book.list(105)[0].peer_id, "a");
    assert!(
        PeerPolicy {
            timeout_ms: 20,
            evict_after_ms: 20,
        }
        .validate()
        .is_err()
    );
}
