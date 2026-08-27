//! Cross-language liveness vectors for the Rust peer bookkeeping candidate.

use l1_kernel_rs::network::{PeerAnnouncement, PeerBook};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct PeerVectors {
    self_id: String,
    operations: Vec<Operation>,
    expected_peer_ids: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct Operation {
    kind: String,
    at_ms: u64,
    peer_id: Option<String>,
    host: Option<String>,
    port: Option<u16>,
    cells: Option<u32>,
    version: Option<String>,
    status: Option<String>,
    peers_total: Option<usize>,
    peers_alive: Option<usize>,
    peers_dead: Option<usize>,
    lost: Option<Vec<String>>,
    evicted: Option<Vec<String>>,
}

#[test]
fn shared_peer_vectors_match_rust_candidate() {
    let vectors: PeerVectors = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_peer_vectors.json"
    ))
    .expect("valid peer vectors");
    let mut book = PeerBook::new(vectors.self_id, Default::default()).expect("valid peer book");

    for operation in vectors.operations {
        match operation.kind.as_str() {
            "announce" => {
                let mut announcement = PeerAnnouncement::new(
                    operation.peer_id.expect("peer id"),
                    operation.host.expect("peer host"),
                    operation.port.expect("peer port"),
                );
                announcement.cell_count = operation.cells.unwrap_or_default();
                announcement.version = operation.version.unwrap_or_default();
                book.announce(announcement, operation.at_ms)
                    .expect("announce succeeds");
            }
            "health" => {
                let health = book.health(operation.at_ms);
                assert_eq!(health.status, operation.status.expect("status"));
                assert_eq!(health.peers_total, operation.peers_total.expect("total"));
                assert_eq!(health.peers_alive, operation.peers_alive.expect("alive"));
                assert_eq!(health.peers_dead, operation.peers_dead.expect("dead"));
                assert_eq!(health.observation.lost, operation.lost.expect("lost"));
                assert_eq!(
                    health.observation.evicted,
                    operation.evicted.expect("evicted")
                );
            }
            other => panic!("unknown peer operation: {other}"),
        }
    }

    let mut peer_ids: Vec<String> = book
        .list(400_100)
        .into_iter()
        .map(|peer| peer.peer_id)
        .collect();
    peer_ids.sort();
    assert_eq!(peer_ids, vectors.expected_peer_ids);
}
