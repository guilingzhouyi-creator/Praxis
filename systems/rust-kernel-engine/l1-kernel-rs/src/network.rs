//! Transport-neutral peer bookkeeping for the Rust-first kernel.
//!
//! The candidate owns bounded peer identity, endpoint validation, liveness
//! transitions, and deterministic snapshots. Clocks, sockets, discovery,
//! TLS, EventBus delivery, card synchronization, and message serialization
//! remain adapter responsibilities.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// Default duration before an unseen peer is considered dead.
pub const DEFAULT_PEER_TIMEOUT_MS: u64 = 60_000;
/// Default grace period before a reported dead peer is evicted.
pub const DEFAULT_PEER_EVICT_AFTER_MS: u64 = 300_000;

/// Caller-supplied liveness policy for one peer book.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeerPolicy {
    /// Time without an announce before a peer is considered dead.
    /// Peer reachability timeout.
    pub timeout_ms: u64,
    /// Time without an announce before a reported dead peer is removed.
    /// Silence window before eviction.
    pub evict_after_ms: u64,
}

impl Default for PeerPolicy {
    /// Apply the default peer policy.
    fn default() -> Self {
        Self {
            timeout_ms: DEFAULT_PEER_TIMEOUT_MS,
            evict_after_ms: DEFAULT_PEER_EVICT_AFTER_MS,
        }
    }
}

impl PeerPolicy {
    /// Reject zero or non-increasing liveness windows.
    ///
    /// # Errors
    ///
    /// `Err` when the timeout is non-positive or eviction does not exceed
    /// the timeout.
    pub fn validate(self) -> Result<(), &'static str> {
        if self.timeout_ms == 0 {
            return Err("peer timeout must be positive");
        }
        if self.evict_after_ms <= self.timeout_ms {
            return Err("peer eviction window must exceed timeout");
        }
        Ok(())
    }
}

/// Transport-neutral peer announce input.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeerAnnouncement {
    /// Stable peer node identifier.
    /// Announced peer identity.
    /// Peer identity.
    pub peer_id: String,
    /// Resolved host or address supplied by discovery.
    /// Advertised host/address.
    /// Last-known host.
    pub host: String,
    /// TCP/transport port supplied by discovery.
    /// Advertised port.
    /// Last-known port.
    pub port: u16,
    /// Number of Cells currently advertised by the peer.
    #[serde(default)]
    /// Cell count announced by the peer.
    /// Last-announced cell count.
    pub cell_count: u32,
    /// Adapter or protocol version advertised by the peer.
    #[serde(default)]
    /// Protocol version announcement.
    /// Last-announced version.
    pub version: String,
}

impl PeerAnnouncement {
    /// Build an announcement with empty optional metadata.
    ///
    /// # Errors
    ///
    /// `Err` forwarding PeerPolicy::validate failures (timeout/eviction bounds).
    pub fn new(peer_id: impl Into<String>, host: impl Into<String>, port: u16) -> Self {
        Self {
            peer_id: peer_id.into(),
            host: host.into(),
            port,
            cell_count: 0,
            version: String::new(),
        }
    }

    /// Validate the peer declaration fail-closed.
    fn validate(&self) -> Result<(), &'static str> {
        if self.peer_id.trim().is_empty() {
            return Err("peer id is required");
        }
        if self.host.trim().is_empty() {
            return Err("peer host is required");
        }
        if self.port == 0 {
            return Err("peer port must be positive");
        }
        Ok(())
    }
}

/// Stored peer record with explicit caller-supplied observation time.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeerRecord {
    /// Stable peer node identifier.
    pub peer_id: String,
    /// Last announced host/address.
    pub host: String,
    /// Last announced port.
    pub port: u16,
    /// Last announce time in caller-defined milliseconds.
    /// Caller-clocked last-seen time.
    pub last_seen_ms: u64,
    /// Advertised Cell count.
    pub cell_count: u32,
    /// Advertised protocol version.
    pub version: String,
    /// Whether a loss event was already emitted for this record.
    #[serde(default)]
    /// Whether a loss was reported for this peer.
    pub loss_reported: bool,
}

impl PeerRecord {
    /// Return whether this record is alive at the supplied timestamp.
    pub fn is_alive(&self, now_ms: u64, policy: PeerPolicy) -> bool {
        now_ms.saturating_sub(self.last_seen_ms) < policy.timeout_ms
    }
}

/// Side-effect-free result of announce/prune bookkeeping.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeerObservation {
    /// Peer ID inserted for the first time, if any.
    /// Newly joined peer id, if any.
    pub joined: Option<String>,
    /// True when an announce for the local node was ignored.
    /// Whether our own announcement was ignored.
    pub ignored_self: bool,
    /// Peers crossing the timeout window during this operation.
    /// Peers classified lost this tick.
    pub lost: Vec<String>,
    /// Peers removed after crossing the eviction window.
    /// Peers evicted after the grace window.
    pub evicted: Vec<String>,
}

impl PeerObservation {
    /// Build an empty peer observation.
    fn empty() -> Self {
        Self {
            joined: None,
            ignored_self: false,
            lost: Vec::new(),
            evicted: Vec::new(),
        }
    }
}

/// Deterministic health summary after a prune operation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeerHealth {
    /// `healthy` when one or more peers are alive, otherwise `lonely`.
    /// Aggregate health label.
    pub status: String,
    /// Number of records retained after eviction.
    /// Tracked peer count.
    pub peers_total: usize,
    /// Number of retained records inside the timeout window.
    /// Peers within the alive window.
    pub peers_alive: usize,
    /// Number of retained records outside the timeout window.
    /// Peers beyond the alive window.
    pub peers_dead: usize,
    /// Loss and eviction transitions observed during this health read.
    pub observation: PeerObservation,
}

/// Read-only peer view with an explicit age at the requested timestamp.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeerView {
    /// Stable peer node identifier.
    pub peer_id: String,
    /// Peer host/address.
    pub host: String,
    /// Peer port.
    pub port: u16,
    /// Whether this peer is alive at the requested timestamp.
    pub alive: bool,
    /// Number of milliseconds since the last announce.
    pub age_ms: u64,
    /// Advertised Cell count.
    pub cell_count: u32,
    /// Advertised protocol version.
    pub version: String,
}

/// Rust-native peer table with no clock, socket, or event-bus authority.
pub struct PeerBook {
    self_id: String,
    policy: PeerPolicy,
    peers: BTreeMap<String, PeerRecord>,
}

impl PeerBook {
    /// Create an empty peer book for one local node.
    ///
    /// # Errors
    ///
    /// `Err` when the local node id is empty or the policy is invalid.
    pub fn new(self_id: impl Into<String>, policy: PeerPolicy) -> Result<Self, &'static str> {
        let self_id = self_id.into();
        if self_id.trim().is_empty() {
            return Err("local peer id is required");
        }
        policy.validate()?;
        Ok(Self {
            self_id,
            policy,
            peers: BTreeMap::new(),
        })
    }

    /// Return the policy used by this peer book.
    pub const fn policy(&self) -> PeerPolicy {
        self.policy
    }

    /// Observe one announce and return join/loss/eviction transitions.
    pub fn announce(
        &mut self,
        announcement: PeerAnnouncement,
        now_ms: u64,
    ) -> Result<PeerObservation, &'static str> {
        announcement.validate()?;
        let mut observation = self.prune(now_ms);
        if announcement.peer_id == self.self_id {
            observation.ignored_self = true;
            return Ok(observation);
        }
        let joined = !self.peers.contains_key(&announcement.peer_id);
        let peer_id = announcement.peer_id.clone();
        self.peers.insert(
            peer_id.clone(),
            PeerRecord {
                peer_id: peer_id.clone(),
                host: announcement.host,
                port: announcement.port,
                last_seen_ms: now_ms,
                cell_count: announcement.cell_count,
                version: announcement.version,
                loss_reported: false,
            },
        );
        if joined {
            observation.joined = Some(peer_id);
        }
        Ok(observation)
    }

    /// Prune timed-out records and return loss/eviction transitions.
    pub fn prune(&mut self, now_ms: u64) -> PeerObservation {
        let mut observation = PeerObservation::empty();
        for peer in self.peers.values_mut() {
            if !peer.is_alive(now_ms, self.policy) && !peer.loss_reported {
                peer.loss_reported = true;
                observation.lost.push(peer.peer_id.clone());
            }
        }
        let stale_ids: Vec<String> = self
            .peers
            .values()
            .filter(|peer| {
                peer.loss_reported
                    && now_ms.saturating_sub(peer.last_seen_ms) >= self.policy.evict_after_ms
            })
            .map(|peer| peer.peer_id.clone())
            .collect();
        for peer_id in stale_ids {
            self.peers.remove(&peer_id);
            observation.evicted.push(peer_id);
        }
        observation
    }

    /// Return health after applying timeout and eviction transitions.
    pub fn health(&mut self, now_ms: u64) -> PeerHealth {
        let observation = self.prune(now_ms);
        let peers_alive = self
            .peers
            .values()
            .filter(|peer| peer.is_alive(now_ms, self.policy))
            .count();
        let peers_total = self.peers.len();
        PeerHealth {
            status: if peers_alive > 0 {
                "healthy".to_owned()
            } else {
                "lonely".to_owned()
            },
            peers_total,
            peers_alive,
            peers_dead: peers_total - peers_alive,
            observation,
        }
    }

    /// Return deterministic peer views, newest first and ID tie-broken.
    pub fn list(&self, now_ms: u64) -> Vec<PeerView> {
        let mut peers: Vec<_> = self
            .peers
            .values()
            .map(|peer| PeerView {
                peer_id: peer.peer_id.clone(),
                host: peer.host.clone(),
                port: peer.port,
                alive: peer.is_alive(now_ms, self.policy),
                age_ms: now_ms.saturating_sub(peer.last_seen_ms),
                cell_count: peer.cell_count,
                version: peer.version.clone(),
            })
            .collect();
        peers.sort_by(|left, right| {
            right
                .age_ms
                .cmp(&left.age_ms)
                .then_with(|| left.peer_id.cmp(&right.peer_id))
        });
        peers
    }

    /// Return one alive peer record for an adapter-owned transport send.
    pub fn alive_peer(&self, peer_id: &str, now_ms: u64) -> Option<PeerRecord> {
        self.peers
            .get(peer_id)
            .filter(|peer| peer.is_alive(now_ms, self.policy))
            .cloned()
    }

    /// Return the number of records currently retained.
    pub fn len(&self) -> usize {
        self.peers.len()
    }

    /// Return whether no records are retained.
    pub fn is_empty(&self) -> bool {
        self.peers.is_empty()
    }
}

impl Default for PeerBook {
    /// Create a peer book with the default policy.
    fn default() -> Self {
        Self::new("local", PeerPolicy::default()).expect("default peer policy is valid")
    }
}
