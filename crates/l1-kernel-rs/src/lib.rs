//! Contract-only Rust boundary for the Praxis L1 kernel migration.

#![forbid(unsafe_code)]

pub mod agent_loop;
pub mod allocator;
pub mod assembly;
pub mod audit;
pub mod benchmark;
pub mod benchmark_runner;
pub mod boot;
pub mod bus;
pub mod cancellation;
pub mod capability;
pub mod channel;
pub mod config_store;
pub mod constitution;
pub mod contract;
pub mod device;
pub mod discovery;
pub mod entry;
pub mod errors;
pub mod event;
pub mod execution_store;
pub mod gatechain;
pub mod health;
pub mod host_dispatch;
pub mod identity_binding;
pub mod identity_uid;
pub mod input_activity;
pub mod interrupt;
pub mod ipc;
pub mod lifecycle;
pub mod load_adaptive;
pub mod managed_process;
pub mod migration;
pub mod network;
pub mod notify;
pub mod outbox_registry;
pub mod paths;
pub mod persist;
pub mod platform;
pub mod ports;
pub mod preflight;
pub mod process;
pub mod process_adapter;
pub mod process_bridge;
pub mod process_constraints;
pub mod process_group;
pub mod process_group_runtime;
pub mod protocol;
pub mod protocol_host;
pub mod recovery;
pub mod registry;
pub mod registry_base;
pub mod reputation;
pub mod rule_descriptor;
pub mod runtime;
pub mod scheduler;
pub mod schema;
pub mod session;
pub mod session_identity;
pub mod session_lifecycle;
pub mod session_store;
pub mod snapshot;
pub mod state_layout;
pub mod state_queue;
pub mod state_store;
pub mod substrate;
pub mod swapper;
pub mod sync;
pub mod terminal;
pub mod terminal_probe;
pub mod territory;
pub mod tool_chain;
pub mod versioning;
pub mod vfs;
pub mod worker;

/// Version of the language-neutral L1 contract represented by this crate.
pub const KERNEL_CONTRACT_VERSION: u32 = 1;

/// Describe the contract boundary without implementing runtime authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct KernelContract {
    /// The contract version consumed by a future adapter.
    pub version: u32,
}

impl KernelContract {
    /// Return the current contract-only boundary descriptor.
    pub const fn current() -> Self {
        Self {
            version: KERNEL_CONTRACT_VERSION,
        }
    }
}
