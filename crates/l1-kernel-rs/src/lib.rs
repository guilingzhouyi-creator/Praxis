//! Contract-only Rust boundary for the Praxis L1 kernel migration.
//!
//! Every module is a mechanism-only candidate: policy stays with the
//! injected adapters, side effects stay host-owned, and nothing here is
//! wired into boot, ports, or a production execution authority. Shared
//! JSON vectors under `tests/fixtures/` pin each module's semantics
//! against the Python reference implementation.
//!
//! Module map:
//!   - Crate contract & shared values: contract, errors, identity_uid, territory, paths, platform, discovery, registry, registry_base, schema, rule_descriptor, tool_chain, identity_binding, device, notify, swapper, health, load_adaptive, ports
//!   - Concurrency mechanisms: sync, channel, event, bus, ipc, interrupt, cancellation, worker, state_queue, substrate, scheduler, runtime
//!   - Process ownership: process, process_adapter, managed_process, process_bridge, process_constraints, process_group, process_group_runtime
//!   - Resource accounting: allocator
//!   - Policy adjudication (fail-closed gates): capability, gatechain, constitution, reputation, audit
//!   - Session truth & protocol host: session, session_identity, session_lifecycle, session_store, execution_store, terminal, terminal_probe, agent_loop, outbox_registry, protocol, protocol_host, host_dispatch, input_activity, snapshot
//!   - Networking peers: network
//!   - Lifecycle, state & persistence: boot, lifecycle, versioning, migration, assembly, state_layout, state_store, config_store, persist, vfs
//!   - Benchmark evidence: benchmark, benchmark_runner

#![forbid(unsafe_code)]

// ── Crate contract & shared values ──

/// Language-neutral value contracts mirrored from the Python L1 ports.
pub mod contract;

/// Provider-neutral structured errors and explicit trace propagation values.
pub mod errors;

/// Entropy-injected identity UID issuer candidate for the L1 kernel.
pub mod identity_uid;

/// Provider-neutral territory containment for the L1 boundary.
pub mod territory;

/// Provider-neutral deployment path derivation for the L1 boundary.
pub mod paths;

/// Provider-neutral platform values and command construction for the L1 boundary.
pub mod platform;

/// Provider-neutral declarative configuration discovery values.
pub mod discovery;

/// Provider-neutral system-registry value aggregation candidate.
pub mod registry;

/// Thread-safe metadata registry candidate for the L1 kernel.
pub mod registry_base;

/// Thread-safe string-event schema registry candidate for the L1 kernel.
pub mod schema;

/// Language-neutral Constitution rule descriptor candidate.
pub mod rule_descriptor;

/// Provider-neutral tool-call fingerprint chaining candidate.
pub mod tool_chain;

/// Rust-native identity-binding metadata registry for the L1 kernel.
pub mod identity_binding;

/// Deterministic device bookkeeping candidate for the L1 kernel.
pub mod device;

/// Rust-native bounded notification buffer candidate.
pub mod notify;

/// Provider-neutral memory-ring swap planning candidate for the L1 kernel.
pub mod swapper;

/// Provider-neutral health-result aggregation candidate for the L1 kernel.
pub mod health;

/// Provider-neutral load-adaptive worker-pool control law candidate.
pub mod load_adaptive;

/// Language-neutral port values and declarative adapter registration.
pub mod ports;

// ── Concurrency mechanisms ──

/// Rust synchronization mechanisms staged behind the Python L1 contract.
pub mod sync;

/// Rust fixed-capacity channel candidate behind the ChannelPort contract.
pub mod channel;

/// Rust EventBus candidate behind the language-neutral signal contract.
pub mod event;

/// Provider-neutral SystemBus metadata, dependency planning, and state values.
pub mod bus;

/// Rust candidate for the bounded lock IPC channel and registry.
pub mod ipc;

/// Provider-neutral interrupt values and bounded IRQ bookkeeping.
pub mod interrupt;

/// Rust-native cancellation token for bounded kernel waits.
pub mod cancellation;

/// Rust bounded worker-pool candidate behind the WorkerPort contract.
pub mod worker;

/// Rust-native sharded state and bounded work-queue prototype for R1.
pub mod state_queue;

/// Rust-native R1 substrate values for ownership and hot-path metrics.
pub mod substrate;

/// Rust-native scheduler candidate joining process state and bounded work.
pub mod scheduler;

/// Rust-owned execution host candidate for the clean-break kernel.
pub mod runtime;

// ── Process ownership ──

/// Rust process-table candidate behind the Python PCB contract.
pub mod process;

/// Rust-owned bounded one-shot process adapter candidate.
pub mod process_adapter;

/// Rust-owned bounded process lifecycle candidate.
pub mod managed_process;

/// ProcessTable ownership bridge for managed child execution.
pub mod process_bridge;

/// Fail-closed Agent process constraints for the Rust L1 admission boundary.
pub mod process_constraints;

/// Rust-native process-group ownership and bounded reaper planning.
pub mod process_group;

/// Rust-native coordination boundary for managed children and process groups.
pub mod process_group_runtime;

// ── Resource accounting ──

/// Rust resource-accounting candidates behind the Python allocator contracts.
pub mod allocator;

// ── Policy adjudication (fail-closed gates) ──

/// Rust candidate for the single capability execution authority.
pub mod capability;

/// Rust candidate for the pure G1-G5 capability gate chain.
pub mod gatechain;

/// Rust candidate for the pure Constitution rule/value/evaluation layer.
pub mod constitution;

/// Rust-native reputation ledger candidate for explicit GateChain inputs.
pub mod reputation;

/// Rust candidate for the bounded kernel audit trail.
pub mod audit;

// ── Session truth & protocol host ──

/// Sharded Rust session truth for the clean-break kernel.
pub mod session;

/// Session identity triple separation for the host session boundary.
pub mod session_identity;

/// Session lifecycle FSM and record for the host session boundary.
pub mod session_lifecycle;

/// Durable Rust-owned session checkpoints for the clean-break kernel.
pub mod session_store;

/// Durable Rust-owned execution checkpoint for sessions, terminals, and loops.
pub mod execution_store;

/// Rust-owned terminal/session substrate for the clean-break kernel.
pub mod terminal;

/// Injected terminal capability discovery for the Rust L1 boundary.
pub mod terminal_probe;

/// Rust-owned AgentLoop routing state for the clean-break kernel.
pub mod agent_loop;

/// Bounded per-session outbox registry, per-view ack cursors, and eviction metrics mirroring `ProtocolHost.
pub mod outbox_registry;

/// Versioned, transport-neutral protocol boundary for the clean-break kernel.
pub mod protocol;

/// Bounded Rust JSONL protocol gate for the clean-break kernel.
pub mod protocol_host;

/// Kind-by-kind host dispatch boundary for the Rust protocol host.
pub mod host_dispatch;

/// Aggregate-only input activity probe for the Rust/TS boundary.
pub mod input_activity;

/// Bounded deterministic snapshot pages for Rust-owned registry books.
pub mod snapshot;

// ── Networking peers ──

/// Transport-neutral peer bookkeeping for the Rust-first kernel.
pub mod network;

// ── Lifecycle, state & persistence ──

/// Declarative boot-plan assembly for the Rust-first kernel.
pub mod boot;

/// Provider-neutral lifecycle state machine and checkpoint record candidate.
pub mod lifecycle;

/// JSON schema version and migration registry candidate for kernel persistence.
pub mod versioning;

/// Ordered schema migration runner candidate for install-time kernel work.
pub mod migration;

/// Rust-owned kernel assembly boundary for the clean-break build.
pub mod assembly;

/// Rust-owned state layout and fresh-state recovery decisions.
pub mod state_layout;

/// Rust-owned fresh-root state store and durable lifecycle checkpoint adapter.
pub mod state_store;

/// Rust-owned configuration root for the clean-break kernel.
pub mod config_store;

/// Rust candidate for the append-only kernel event journal.
pub mod persist;

/// Rust candidate for the bounded, provider-neutral Praxis virtual file system.
pub mod vfs;

// ── Benchmark evidence ──

/// Typed fixed-work benchmark schema for the Rust-first rewrite.
pub mod benchmark;

/// Run a Rust-native fixed-work queue contention candidate.
pub mod benchmark_runner;

// ── Crate contract descriptor ──

/// Version of the wire/contract surface this crate pins.
pub const KERNEL_CONTRACT_VERSION: u32 = 1;

/// The crate's contract descriptor handed to adapters and hosts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct KernelContract {
    /// Contract version; must match Python-side expectations.
    pub version: u32,
}

impl KernelContract {
    /// Return the current contract values.
    pub const fn current() -> Self {
        Self {
            version: KERNEL_CONTRACT_VERSION,
        }
    }
}
