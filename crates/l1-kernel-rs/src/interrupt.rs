//! Provider-neutral interrupt values and bounded IRQ bookkeeping.

use std::collections::{BTreeMap, VecDeque};
use std::sync::{Mutex, PoisonError};

use serde::{Deserialize, Serialize};

/// Maximum history retained by the Python interrupt table.
pub const INTERRUPT_MAX_HISTORY: usize = 200;
/// Default recent-history query limit.
pub const INTERRUPT_QUERY_LIMIT: usize = 20;

/// Stable interrupt kinds emitted by the kernel boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Ord, PartialOrd, Serialize, Deserialize)]
pub enum InterruptType {
    /// Agent execution crashed.
    #[serde(rename = "AGENT_CRASH")]
    AgentCrash,
    /// A resource limit was reached.
    #[serde(rename = "RESOURCE_EXHAUSTION")]
    ResourceExhaustion,
    /// A deadlock was detected.
    #[serde(rename = "DEADLOCK_DETECTED")]
    DeadlockDetected,
    /// An allocation was terminated by the OOM policy.
    #[serde(rename = "OOM_KILL")]
    OomKill,
    /// A process or agent was cancelled.
    #[serde(rename = "CANCELLED")]
    Cancelled,
}

impl InterruptType {
    /// Parse the Python enum name without accepting unknown kinds.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "AGENT_CRASH" => Some(Self::AgentCrash),
            "RESOURCE_EXHAUSTION" => Some(Self::ResourceExhaustion),
            "DEADLOCK_DETECTED" => Some(Self::DeadlockDetected),
            "OOM_KILL" => Some(Self::OomKill),
            "CANCELLED" => Some(Self::Cancelled),
            _ => None,
        }
    }

    /// Return the stable Python enum name.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::AgentCrash => "AGENT_CRASH",
            Self::ResourceExhaustion => "RESOURCE_EXHAUSTION",
            Self::DeadlockDetected => "DEADLOCK_DETECTED",
            Self::OomKill => "OOM_KILL",
            Self::Cancelled => "CANCELLED",
        }
    }
}

/// Serializable interrupt history row.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Interrupt {
    /// Interrupt kind (`type` on the Python history wire).
    #[serde(rename = "type")]
    pub interrupt_type: InterruptType,
    /// Agent or process identity associated with the interrupt.
    #[serde(rename = "agent")]
    pub agent_id: String,
    /// Human-readable reason.
    pub reason: String,
    /// Structured provider-neutral payload.
    pub data: serde_json::Value,
    /// Per-kind sequence number.
    #[serde(rename = "seq")]
    pub sequence: u64,
}

/// Thread-safe bounded IRQ table.
pub struct InterruptTable {
    max_history: usize,
    query_limit: usize,
    state: Mutex<InterruptState>,
}

#[derive(Debug, Default)]
struct InterruptState {
    counts: BTreeMap<String, u64>,
    history: VecDeque<Interrupt>,
}

impl InterruptTable {
    /// Create a table with the Python defaults.
    pub fn new() -> Self {
        Self::with_limits(INTERRUPT_MAX_HISTORY, INTERRUPT_QUERY_LIMIT)
    }

    /// Create a table with explicit limits for deterministic tests/adapters.
    pub fn with_limits(max_history: usize, query_limit: usize) -> Self {
        Self {
            max_history,
            query_limit,
            state: Mutex::new(InterruptState::default()),
        }
    }

    /// Record an IRQ without executing callbacks or performing I/O.
    pub fn raise(
        &self,
        interrupt_type: InterruptType,
        agent_id: impl Into<String>,
        reason: impl Into<String>,
        data: Option<serde_json::Value>,
    ) -> Interrupt {
        let mut state = self.lock();
        let name = interrupt_type.as_str().to_owned();
        let sequence = state.counts.entry(name).or_insert(0);
        *sequence += 1;
        let interrupt = Interrupt {
            interrupt_type,
            agent_id: agent_id.into(),
            reason: reason.into(),
            data: normalize_data(data),
            sequence: *sequence,
        };
        if self.max_history > 0 {
            state.history.push_back(interrupt.clone());
            while state.history.len() > self.max_history {
                state.history.pop_front();
            }
        }
        interrupt
    }

    /// Return per-kind occurrence counts in stable key order.
    pub fn counts(&self) -> BTreeMap<String, u64> {
        self.lock().counts.clone()
    }

    /// Return the newest history rows up to the configured query limit.
    pub fn recent(&self, limit: Option<usize>) -> Vec<Interrupt> {
        let state = self.lock();
        let requested = limit.unwrap_or(self.query_limit);
        if requested == 0 {
            return state.history.iter().cloned().collect();
        }
        let start = state.history.len().saturating_sub(requested);
        state.history.iter().skip(start).cloned().collect()
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, InterruptState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for InterruptTable {
    fn default() -> Self {
        Self::new()
    }
}

fn normalize_data(data: Option<serde_json::Value>) -> serde_json::Value {
    match data {
        Some(value) if !value.is_null() => value,
        _ => serde_json::json!({}),
    }
}

#[cfg(test)]
mod tests {
    use serde::Deserialize;

    use super::{InterruptTable, InterruptType};

    #[derive(Debug, Deserialize)]
    struct InterruptVector {
        events: Vec<EventVector>,
        expected_counts: serde_json::Value,
        recent_limit: usize,
        expected_recent: serde_json::Value,
    }

    #[derive(Debug, Deserialize)]
    struct EventVector {
        #[serde(rename = "type")]
        interrupt_type: String,
        #[serde(default)]
        agent_id: String,
        #[serde(default)]
        reason: String,
        data: Option<serde_json::Value>,
    }

    #[test]
    fn type_names_are_closed_and_wire_stable() {
        for name in [
            "AGENT_CRASH",
            "RESOURCE_EXHAUSTION",
            "DEADLOCK_DETECTED",
            "OOM_KILL",
            "CANCELLED",
        ] {
            let kind = InterruptType::parse(name).expect("known interrupt type");
            assert_eq!(kind.as_str(), name);
        }
        assert!(InterruptType::parse("UNKNOWN").is_none());
    }

    #[test]
    fn bounded_history_and_per_type_sequence_match_python_shape() {
        let table = InterruptTable::with_limits(2, 20);
        table.raise(InterruptType::Cancelled, "agent-a", "first", None);
        table.raise(InterruptType::Cancelled, "agent-a", "second", None);
        let third = table.raise(
            InterruptType::ResourceExhaustion,
            "agent-b",
            "pressure",
            Some(serde_json::Value::Null),
        );
        assert_eq!(third.sequence, 1);
        assert_eq!(table.counts()["CANCELLED"], 2);
        assert_eq!(table.recent(Some(20)).len(), 2);
        assert_eq!(table.recent(Some(0)).len(), 2);
        assert_eq!(table.recent(None)[0].sequence, 2);
    }

    #[test]
    fn shared_interrupt_vectors_match_python_reference() {
        let vectors: Vec<InterruptVector> = serde_json::from_str(include_str!(
            "../../../tests/fixtures/kernel_interrupt_vectors.json"
        ))
        .expect("interrupt fixture must be valid JSON");
        for vector in vectors {
            let table = InterruptTable::new();
            for event in vector.events {
                let interrupt_type = InterruptType::parse(&event.interrupt_type)
                    .expect("fixture interrupt type must be known");
                table.raise(interrupt_type, event.agent_id, event.reason, event.data);
            }
            assert_eq!(
                serde_json::to_value(table.counts()).expect("counts serialize"),
                vector.expected_counts
            );
            assert_eq!(
                serde_json::to_value(table.recent(Some(vector.recent_limit)))
                    .expect("history serializes"),
                vector.expected_recent
            );
        }
    }
}
