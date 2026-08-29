//! Bounded Rust TCP/UDP transport adapter for the clean-break kernel.
//!
//! The adapter owns only socket lifecycle, bounded JSON framing, message
//! buffering, and panic-contained handler dispatch. Peer policy, EventBus
//! effects, TLS implementation, Cell/card semantics, and runtime authority
//! remain caller-owned. Hosts must provide explicit addresses and ports; the
//! adapter never scans the host or selects a shell/command implicitly.

use std::collections::BTreeMap;
use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream, ToSocketAddrs, UdpSocket};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, AtomicU16, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, PoisonError};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::channel::RingChannel;
use crate::contract::{JsonObject, JsonValue};
use crate::ports::{Endpoint, Message, PortResult};

/// Version of the explicit Rust transport contract.
pub const TRANSPORT_CONTRACT_VERSION: u32 = 1;
/// Default TCP service port inherited from the Python reference deployment.
pub const TRANSPORT_DEFAULT_PORT: u16 = 42_070;
/// Default UDP discovery port inherited from the Python reference deployment.
pub const TRANSPORT_DEFAULT_DISCOVERY_PORT: u16 = 42_069;
/// Default interval between explicit UDP announcements.
pub const TRANSPORT_DEFAULT_BROADCAST_INTERVAL_MS: u64 = 15_000;
/// Default socket read/write timeout.
pub const TRANSPORT_DEFAULT_SOCKET_TIMEOUT_MS: u64 = 10_000;
/// Default maximum accepted JSON frame.
pub const TRANSPORT_DEFAULT_MAX_FRAME_BYTES: usize = 1 << 20;
/// Default bounded receive queue capacity.
pub const TRANSPORT_DEFAULT_CHANNEL_CAPACITY: usize = 256;
/// Default TCP listen backlog requested from the host.
pub const TRANSPORT_DEFAULT_LISTEN_BACKLOG: i32 = 5;
/// Default wire version advertised in discovery announcements.
pub const TRANSPORT_WIRE_VERSION: &str = "1.0";

const TRANSPORT_ACCEPT_POLL_MS: u64 = 10;
const TRANSPORT_SOCKET_ERROR_POLL_MS: u64 = 25;
const TRANSPORT_UDP_BUFFER_BYTES: usize = 65_536;

/// Explicit transport deployment values.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransportConfig {
    /// Host address on which the TCP listener binds.
    pub host: String,
    /// TCP service port; zero asks the host for an ephemeral port.
    pub port: u16,
    /// UDP discovery port; zero asks the host for an ephemeral port.
    pub discovery_port: u16,
    /// Whether UDP discovery listener/announcer threads are enabled.
    pub enable_discovery: bool,
    /// Explicit IPv4 broadcast or unicast destination for announcements.
    pub broadcast_address: String,
    /// Interval between announcements.
    pub broadcast_interval: Duration,
    /// Per-connection read/write timeout.
    pub socket_timeout: Duration,
    /// Maximum JSON frame size, excluding the optional newline delimiter.
    pub max_frame_bytes: usize,
    /// Capacity of the inbound message queue.
    pub channel_capacity: usize,
    /// Whether a future TLS provider is requested.
    pub tls_enabled: bool,
}

impl Default for TransportConfig {
    /// Build a deployment using the Python reference's documented defaults.
    fn default() -> Self {
        Self {
            host: "0.0.0.0".to_owned(),
            port: TRANSPORT_DEFAULT_PORT,
            discovery_port: TRANSPORT_DEFAULT_DISCOVERY_PORT,
            enable_discovery: true,
            broadcast_address: "255.255.255.255".to_owned(),
            broadcast_interval: Duration::from_millis(TRANSPORT_DEFAULT_BROADCAST_INTERVAL_MS),
            socket_timeout: Duration::from_millis(TRANSPORT_DEFAULT_SOCKET_TIMEOUT_MS),
            max_frame_bytes: TRANSPORT_DEFAULT_MAX_FRAME_BYTES,
            channel_capacity: TRANSPORT_DEFAULT_CHANNEL_CAPACITY,
            tls_enabled: false,
        }
    }
}

impl TransportConfig {
    /// Build a loopback, ephemeral-port configuration for isolated hosts.
    pub fn loopback_ephemeral() -> Self {
        Self {
            host: "127.0.0.1".to_owned(),
            port: 0,
            discovery_port: 0,
            enable_discovery: false,
            broadcast_address: "127.0.0.1".to_owned(),
            broadcast_interval: Duration::from_millis(100),
            socket_timeout: Duration::from_millis(500),
            max_frame_bytes: TRANSPORT_DEFAULT_MAX_FRAME_BYTES,
            channel_capacity: TRANSPORT_DEFAULT_CHANNEL_CAPACITY,
            tls_enabled: false,
        }
    }

    /// Validate deployment values before opening any socket.
    ///
    /// # Errors
    ///
    /// Returns a stable field name when a value is empty, zero, or contains
    /// an embedded NUL. TLS is checked at `start` because this build has no
    /// provider implementation.
    pub fn validate(&self) -> Result<(), TransportError> {
        if self.host.trim().is_empty() || self.host.contains('\0') {
            return Err(TransportError::InvalidConfig("host"));
        }
        if self.enable_discovery
            && (self.broadcast_address.trim().is_empty() || self.broadcast_address.contains('\0'))
        {
            return Err(TransportError::InvalidConfig("broadcast_address"));
        }
        if self.broadcast_interval.is_zero() {
            return Err(TransportError::InvalidConfig("broadcast_interval"));
        }
        if self.socket_timeout.is_zero() {
            return Err(TransportError::InvalidConfig("socket_timeout"));
        }
        if self.max_frame_bytes == 0 {
            return Err(TransportError::InvalidConfig("max_frame_bytes"));
        }
        if self.channel_capacity == 0 {
            return Err(TransportError::InvalidConfig("channel_capacity"));
        }
        Ok(())
    }
}

/// Structured transport failures that never leak socket or handler panics.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransportError {
    /// A deployment field failed validation.
    InvalidConfig(&'static str),
    /// A host callback or socket operation could not be completed.
    Io { operation: String, message: String },
    /// The adapter has already been started.
    AlreadyRunning,
    /// A send/receive operation requires a running adapter.
    NotRunning,
    /// TLS was requested without an injected TLS provider.
    TlsUnsupported,
    /// A frame exceeded the configured bound.
    FrameTooLarge { actual: usize, max: usize },
    /// A frame was not valid UTF-8 or JSON.
    InvalidFrame(String),
    /// The message value failed the retained port contract.
    InvalidMessage(String),
    /// A handler name is invalid.
    InvalidHandlerName,
    /// No socket address could be resolved from an endpoint.
    InvalidEndpoint(String),
    /// A worker/listener thread could not be started.
    ThreadStart(String),
}

impl std::fmt::Display for TransportError {
    /// Render a stable transport diagnostic.
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidConfig(field) => write!(formatter, "invalid transport config: {field}"),
            Self::Io { operation, message } => write!(formatter, "{operation} failed: {message}"),
            Self::AlreadyRunning => formatter.write_str("transport is already running"),
            Self::NotRunning => formatter.write_str("transport is not running"),
            Self::TlsUnsupported => formatter.write_str("TLS requires an injected provider"),
            Self::FrameTooLarge { actual, max } => {
                write!(formatter, "transport frame is too large: {actual} > {max}")
            }
            Self::InvalidFrame(message) => write!(formatter, "invalid transport frame: {message}"),
            Self::InvalidMessage(message) => {
                write!(formatter, "invalid transport message: {message}")
            }
            Self::InvalidHandlerName => formatter.write_str("transport handler name is invalid"),
            Self::InvalidEndpoint(endpoint) => {
                write!(formatter, "invalid transport endpoint: {endpoint}")
            }
            Self::ThreadStart(message) => {
                write!(formatter, "transport thread failed to start: {message}")
            }
        }
    }
}

impl std::error::Error for TransportError {}

/// Report returned once the listener and optional discovery sockets are live.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransportStartReport {
    /// Transport contract version.
    pub contract_version: u32,
    /// Node identity announced to peers.
    pub node_id: String,
    /// Actual TCP port after binding.
    pub port: u16,
    /// Actual UDP discovery port, or zero when disabled.
    pub discovery_port: u16,
    /// Whether discovery threads were started.
    pub discovery_enabled: bool,
}

/// Report returned after all listener threads have been joined.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransportStopReport {
    /// Transport contract version.
    pub contract_version: u32,
    /// Whether the adapter reached the stopped state.
    pub success: bool,
    /// Messages still buffered at stop time.
    pub remaining_messages: usize,
}

/// Read-only lifecycle and counter snapshot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransportStatus {
    /// Transport contract version.
    pub contract_version: u32,
    /// Whether sockets and listener threads are active.
    pub running: bool,
    /// Current node identity.
    pub node_id: String,
    /// Actual bound TCP port.
    pub port: u16,
    /// Actual discovery port, or zero when disabled.
    pub discovery_port: u16,
    /// Number of queued inbound messages.
    pub queued_messages: usize,
    /// Number of messages rejected by the bounded queue.
    pub dropped_messages: u64,
    /// Number of decoded inbound messages.
    pub received_messages: u64,
    /// Number of successful outbound writes.
    pub sent_messages: u64,
    /// Number of handler panics/errors contained at the boundary.
    pub handler_errors: u64,
    /// Number of listener or announcement socket errors.
    pub listener_errors: u64,
    /// Number of malformed inbound frames.
    pub decode_errors: u64,
}

/// Handler callback invoked after a message is admitted to the queue.
pub type MessageHandler = Arc<dyn Fn(Message) + Send + Sync + 'static>;

#[derive(Default)]
struct TransportCounters {
    dropped_messages: AtomicU64,
    received_messages: AtomicU64,
    sent_messages: AtomicU64,
    handler_errors: AtomicU64,
    listener_errors: AtomicU64,
    decode_errors: AtomicU64,
}

struct TransportInner {
    running: AtomicBool,
    node_id: Mutex<String>,
    port: AtomicU16,
    discovery_port: AtomicU16,
    config: Mutex<Option<TransportConfig>>,
    channel: Mutex<Option<Arc<RingChannel>>>,
    handlers: Mutex<BTreeMap<String, MessageHandler>>,
    counters: TransportCounters,
}

impl Default for TransportInner {
    fn default() -> Self {
        Self {
            running: AtomicBool::new(false),
            node_id: Mutex::new(String::new()),
            port: AtomicU16::new(0),
            discovery_port: AtomicU16::new(0),
            config: Mutex::new(None),
            channel: Mutex::new(None),
            handlers: Mutex::new(BTreeMap::new()),
            counters: TransportCounters::default(),
        }
    }
}

struct StopControl {
    stopped: Mutex<bool>,
    wake: Condvar,
}

impl StopControl {
    fn new() -> Self {
        Self {
            stopped: Mutex::new(false),
            wake: Condvar::new(),
        }
    }

    fn stop(&self) {
        let mut stopped = self.stopped.lock().unwrap_or_else(PoisonError::into_inner);
        *stopped = true;
        self.wake.notify_all();
    }

    fn is_stopped(&self) -> bool {
        *self.stopped.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn wait(&self, duration: Duration) -> bool {
        let stopped = self.stopped.lock().unwrap_or_else(PoisonError::into_inner);
        if *stopped {
            return true;
        }
        let (stopped, _) = self
            .wake
            .wait_timeout(stopped, duration)
            .unwrap_or_else(PoisonError::into_inner);
        *stopped
    }
}

struct TransportThreads {
    stop: Arc<StopControl>,
    handles: Vec<JoinHandle<()>>,
}

/// Rust TCP/UDP transport adapter with explicit lifecycle and bounds.
pub struct TransportAdapter {
    inner: Arc<TransportInner>,
    threads: Mutex<Option<TransportThreads>>,
}

impl Default for TransportAdapter {
    /// Create a stopped adapter with no implicit host side effects.
    fn default() -> Self {
        Self::new()
    }
}

impl TransportAdapter {
    /// Create a stopped adapter.
    pub fn new() -> Self {
        Self {
            inner: Arc::new(TransportInner::default()),
            threads: Mutex::new(None),
        }
    }

    /// Register or replace one message handler before or after start.
    ///
    /// # Errors
    ///
    /// Empty, whitespace-only, or NUL-containing names are rejected.
    pub fn register_handler<F>(
        &self,
        message_type: impl Into<String>,
        handler: F,
    ) -> Result<(), TransportError>
    where
        F: Fn(Message) + Send + Sync + 'static,
    {
        let message_type = message_type.into();
        if message_type.trim().is_empty() || message_type.contains('\0') {
            return Err(TransportError::InvalidHandlerName);
        }
        self.lock_handlers().insert(message_type, Arc::new(handler));
        Ok(())
    }

    /// Remove one handler, returning whether it existed.
    pub fn unregister_handler(&self, message_type: &str) -> bool {
        self.lock_handlers().remove(message_type).is_some()
    }

    /// Start the explicit TCP listener and optional UDP discovery threads.
    ///
    /// # Errors
    ///
    /// Binding, configuration, TLS, or thread-start failures are returned
    /// without publishing a partially running adapter.
    pub fn start(
        &self,
        node_id: impl Into<String>,
        config: TransportConfig,
    ) -> Result<TransportStartReport, TransportError> {
        config.validate()?;
        if config.tls_enabled {
            return Err(TransportError::TlsUnsupported);
        }
        let node_id = node_id.into();
        if node_id.trim().is_empty() || node_id.contains('\0') {
            return Err(TransportError::InvalidConfig("node_id"));
        }
        let mut threads = self.lock_threads();
        if threads.is_some() || self.inner.running.load(Ordering::Acquire) {
            return Err(TransportError::AlreadyRunning);
        }

        let listener = TcpListener::bind((config.host.as_str(), config.port)).map_err(|error| {
            TransportError::Io {
                operation: "tcp bind".to_owned(),
                message: error.to_string(),
            }
        })?;
        listener
            .set_nonblocking(true)
            .map_err(|error| TransportError::Io {
                operation: "tcp nonblocking".to_owned(),
                message: error.to_string(),
            })?;
        let port = listener
            .local_addr()
            .map_err(|error| TransportError::Io {
                operation: "tcp local address".to_owned(),
                message: error.to_string(),
            })?
            .port();

        let discovery = if config.enable_discovery {
            let socket = UdpSocket::bind(("0.0.0.0", config.discovery_port)).map_err(|error| {
                TransportError::Io {
                    operation: "udp bind".to_owned(),
                    message: error.to_string(),
                }
            })?;
            socket
                .set_nonblocking(true)
                .map_err(|error| TransportError::Io {
                    operation: "udp nonblocking".to_owned(),
                    message: error.to_string(),
                })?;
            socket
                .set_broadcast(true)
                .map_err(|error| TransportError::Io {
                    operation: "udp broadcast".to_owned(),
                    message: error.to_string(),
                })?;
            let discovery_port = socket
                .local_addr()
                .map_err(|error| TransportError::Io {
                    operation: "udp local address".to_owned(),
                    message: error.to_string(),
                })?
                .port();
            let announcer_socket =
                UdpSocket::bind(("0.0.0.0", 0)).map_err(|error| TransportError::Io {
                    operation: "udp announcer bind".to_owned(),
                    message: error.to_string(),
                })?;
            announcer_socket
                .set_nonblocking(true)
                .map_err(|error| TransportError::Io {
                    operation: "udp announcer nonblocking".to_owned(),
                    message: error.to_string(),
                })?;
            announcer_socket
                .set_broadcast(true)
                .map_err(|error| TransportError::Io {
                    operation: "udp announcer broadcast".to_owned(),
                    message: error.to_string(),
                })?;
            Some((socket, announcer_socket, discovery_port))
        } else {
            None
        };

        let channel = Arc::new(
            RingChannel::new(config.channel_capacity, false)
                .map_err(|_| TransportError::InvalidConfig("channel_capacity"))?,
        );
        {
            *self.lock_node_id() = node_id.clone();
            self.inner.port.store(port, Ordering::Release);
            self.inner.discovery_port.store(
                discovery.as_ref().map_or(0, |(_, _, value)| *value),
                Ordering::Release,
            );
            *self.lock_config() = Some(config.clone());
            *self.lock_channel() = Some(Arc::clone(&channel));
            self.inner.running.store(true, Ordering::Release);
        }

        let stop = Arc::new(StopControl::new());
        let mut handles = Vec::with_capacity(if config.enable_discovery { 3 } else { 1 });
        let tcp_inner = Arc::clone(&self.inner);
        let tcp_stop = Arc::clone(&stop);
        let tcp_config = config.clone();
        let tcp_handle = match thread::Builder::new()
            .name("praxis-rust-transport-tcp".to_owned())
            .spawn(move || tcp_listener_loop(listener, tcp_inner, tcp_stop, tcp_config))
        {
            Ok(handle) => handle,
            Err(error) => {
                self.abort_start(&stop, handles);
                return Err(TransportError::ThreadStart(error.to_string()));
            }
        };
        handles.push(tcp_handle);

        if let Some((socket, announcer_socket, discovery_port)) = discovery {
            let listener_inner = Arc::clone(&self.inner);
            let listener_stop = Arc::clone(&stop);
            let listener_config = config.clone();
            let listener_handle = match thread::Builder::new()
                .name("praxis-rust-transport-discovery-listener".to_owned())
                .spawn(move || {
                    udp_listener_loop(
                        socket,
                        listener_inner,
                        listener_stop,
                        listener_config,
                        discovery_port,
                    )
                }) {
                Ok(handle) => handle,
                Err(error) => {
                    self.abort_start(&stop, handles);
                    return Err(TransportError::ThreadStart(error.to_string()));
                }
            };
            handles.push(listener_handle);

            let announcer_inner = Arc::clone(&self.inner);
            let announcer_stop = Arc::clone(&stop);
            let announcer_config = config.clone();
            let announcer_handle = match thread::Builder::new()
                .name("praxis-rust-transport-discovery-announcer".to_owned())
                .spawn(move || {
                    udp_announcer_loop(
                        announcer_socket,
                        announcer_inner,
                        announcer_stop,
                        announcer_config,
                        discovery_port,
                    )
                }) {
                Ok(handle) => handle,
                Err(error) => {
                    self.abort_start(&stop, handles);
                    return Err(TransportError::ThreadStart(error.to_string()));
                }
            };
            handles.push(announcer_handle);
        }

        *threads = Some(TransportThreads { stop, handles });
        Ok(TransportStartReport {
            contract_version: TRANSPORT_CONTRACT_VERSION,
            node_id,
            port,
            discovery_port: self.inner.discovery_port.load(Ordering::Acquire),
            discovery_enabled: config.enable_discovery,
        })
    }

    /// Stop listeners, wake discovery loops, close the receive queue, and
    /// join every thread that is not the caller.
    pub fn stop(&self) -> TransportStopReport {
        let mut threads = self.lock_threads();
        let transport_threads = threads.take();
        let Some(transport_threads) = transport_threads else {
            let remaining = self
                .lock_channel()
                .as_ref()
                .map_or(0, |channel| channel.size());
            return TransportStopReport {
                contract_version: TRANSPORT_CONTRACT_VERSION,
                success: !self.inner.running.load(Ordering::Acquire),
                remaining_messages: remaining,
            };
        };
        self.inner.running.store(false, Ordering::Release);
        transport_threads.stop.stop();
        join_handles(transport_threads.handles);
        let channel = self.lock_channel().take();
        let remaining = channel.as_ref().map_or(0, |value| value.size());
        if let Some(channel) = channel {
            channel.close();
        }
        self.inner.port.store(0, Ordering::Release);
        self.inner.discovery_port.store(0, Ordering::Release);
        *self.lock_config() = None;
        drop(threads);
        TransportStopReport {
            contract_version: TRANSPORT_CONTRACT_VERSION,
            success: true,
            remaining_messages: remaining,
        }
    }

    /// Return the current adapter status and cumulative counters.
    pub fn status(&self) -> TransportStatus {
        let channel = self.lock_channel();
        TransportStatus {
            contract_version: TRANSPORT_CONTRACT_VERSION,
            running: self.inner.running.load(Ordering::Acquire),
            node_id: self.lock_node_id().clone(),
            port: self.inner.port.load(Ordering::Acquire),
            discovery_port: self.inner.discovery_port.load(Ordering::Acquire),
            queued_messages: channel.as_ref().map_or(0, |value| value.size()),
            dropped_messages: self.inner.counters.dropped_messages.load(Ordering::Acquire),
            received_messages: self
                .inner
                .counters
                .received_messages
                .load(Ordering::Acquire),
            sent_messages: self.inner.counters.sent_messages.load(Ordering::Acquire),
            handler_errors: self.inner.counters.handler_errors.load(Ordering::Acquire),
            listener_errors: self.inner.counters.listener_errors.load(Ordering::Acquire),
            decode_errors: self.inner.counters.decode_errors.load(Ordering::Acquire),
        }
    }

    /// Return whether the adapter is running.
    pub fn is_running(&self) -> bool {
        self.inner.running.load(Ordering::Acquire)
    }

    /// Receive one decoded message from the bounded inbound queue.
    pub fn receive(&self, timeout: Option<Duration>) -> Result<Option<Message>, TransportError> {
        if !self.is_running() {
            return Err(TransportError::NotRunning);
        }
        let channel = self
            .lock_channel()
            .clone()
            .ok_or(TransportError::NotRunning)?;
        let Some(value) = channel.get(timeout) else {
            return Ok(None);
        };
        decode_wire_message(value, "").map(Some).inspect_err(|_| {
            self.inner
                .counters
                .decode_errors
                .fetch_add(1, Ordering::Relaxed);
        })
    }

    /// Send a typed message to a TCP endpoint.
    pub fn send_message(&self, endpoint: &Endpoint, message: &Message) -> PortResult {
        if let Err(error) = message.validate() {
            return PortResult::fail(TransportError::InvalidMessage(error.to_owned()).to_string());
        }
        let mut value = match serde_json::to_value(message) {
            Ok(value) => value,
            Err(error) => {
                return PortResult::fail(format!("message serialization failed: {error}"));
            }
        };
        if let Some(object) = value.as_object_mut() {
            if let Some(source) = object.remove("source") {
                object.insert("from".to_owned(), source);
            }
            if let Some(target) = object.remove("target") {
                object.insert("to".to_owned(), target);
            }
        }
        let bytes = match serde_json::to_vec(&value) {
            Ok(bytes) => bytes,
            Err(error) => return PortResult::fail(format!("message encoding failed: {error}")),
        };
        self.send_bytes(endpoint, &bytes)
    }

    /// Send one raw bounded frame to a TCP endpoint.
    pub fn send(&self, endpoint: &Endpoint, data: &[u8]) -> PortResult {
        self.send_bytes(endpoint, data)
    }

    /// Send one already-encoded JSON value to a TCP endpoint.
    pub fn send_value(&self, endpoint: &Endpoint, value: &Value) -> PortResult {
        let bytes = match serde_json::to_vec(value) {
            Ok(bytes) => bytes,
            Err(error) => return PortResult::fail(format!("message encoding failed: {error}")),
        };
        self.send_bytes(endpoint, &bytes)
    }

    /// Send one bounded frame to a TCP endpoint.
    pub fn send_bytes(&self, endpoint: &Endpoint, data: &[u8]) -> PortResult {
        if !self.is_running() {
            return PortResult::fail(TransportError::NotRunning.to_string());
        }
        if let Err(error) = endpoint.validate() {
            return PortResult::fail(error);
        }
        if endpoint.hint != "tcp" {
            return PortResult::fail(format!("unsupported transport hint: {}", endpoint.hint));
        }
        let config = match self.lock_config().clone() {
            Some(config) => config,
            None => return PortResult::fail(TransportError::NotRunning.to_string()),
        };
        if data.len() > config.max_frame_bytes {
            return PortResult::fail(
                TransportError::FrameTooLarge {
                    actual: data.len(),
                    max: config.max_frame_bytes,
                }
                .to_string(),
            );
        }
        let address = match endpoint.address.to_socket_addrs() {
            Ok(mut addresses) => addresses
                .next()
                .ok_or_else(|| TransportError::InvalidEndpoint(endpoint.address.clone())),
            Err(_) => Err(TransportError::InvalidEndpoint(endpoint.address.clone())),
        };
        let address = match address {
            Ok(address) => address,
            Err(error) => return PortResult::fail(error.to_string()),
        };
        let mut stream = match TcpStream::connect_timeout(&address, config.socket_timeout) {
            Ok(stream) => stream,
            Err(error) => return PortResult::fail(error.to_string()),
        };
        if let Err(error) = stream.set_write_timeout(Some(config.socket_timeout)) {
            return PortResult::fail(error.to_string());
        }
        if let Err(error) = stream.write_all(data).and_then(|_| {
            if data.last() == Some(&b'\n') {
                Ok(())
            } else {
                stream.write_all(b"\n")
            }
        }) {
            return PortResult::fail(error.to_string());
        }
        self.inner
            .counters
            .sent_messages
            .fetch_add(1, Ordering::Relaxed);
        let mut result = PortResult::ok();
        result.data.insert("sent".to_owned(), JsonValue::Bool(true));
        result.data.insert(
            "target".to_owned(),
            JsonValue::String(endpoint.address.clone()),
        );
        result
    }

    fn lock_threads(&self) -> MutexGuard<'_, Option<TransportThreads>> {
        self.threads.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn abort_start(&self, stop: &Arc<StopControl>, handles: Vec<JoinHandle<()>>) {
        self.inner.running.store(false, Ordering::Release);
        stop.stop();
        join_handles(handles);
        let channel = self.lock_channel().take();
        if let Some(channel) = channel {
            channel.close();
        }
        self.inner.port.store(0, Ordering::Release);
        self.inner.discovery_port.store(0, Ordering::Release);
        *self.lock_config() = None;
        *self.lock_node_id() = String::new();
    }

    fn lock_node_id(&self) -> MutexGuard<'_, String> {
        self.inner
            .node_id
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_config(&self) -> MutexGuard<'_, Option<TransportConfig>> {
        self.inner
            .config
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_channel(&self) -> MutexGuard<'_, Option<Arc<RingChannel>>> {
        self.inner
            .channel
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_handlers(&self) -> MutexGuard<'_, BTreeMap<String, MessageHandler>> {
        self.inner
            .handlers
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

impl Drop for TransportAdapter {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}

/// Accept one frame at a time from the bounded TCP listener.
fn tcp_listener_loop(
    listener: TcpListener,
    inner: Arc<TransportInner>,
    stop: Arc<StopControl>,
    config: TransportConfig,
) {
    while !stop.is_stopped() {
        match listener.accept() {
            Ok((mut stream, address)) => {
                if stream
                    .set_read_timeout(Some(config.socket_timeout))
                    .and_then(|_| stream.set_write_timeout(Some(config.socket_timeout)))
                    .is_err()
                {
                    inner
                        .counters
                        .listener_errors
                        .fetch_add(1, Ordering::Relaxed);
                    continue;
                }
                match read_frame(&mut stream, config.max_frame_bytes)
                    .and_then(|frame| decode_frame(&frame, &address.ip().to_string()))
                {
                    Ok(message) => dispatch_message(&inner, message),
                    Err(_) => {
                        inner.counters.decode_errors.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                if stop.wait(Duration::from_millis(TRANSPORT_ACCEPT_POLL_MS)) {
                    break;
                }
            }
            Err(_) => {
                inner
                    .counters
                    .listener_errors
                    .fetch_add(1, Ordering::Relaxed);
                if stop.wait(Duration::from_millis(TRANSPORT_SOCKET_ERROR_POLL_MS)) {
                    break;
                }
            }
        }
    }
}

/// Receive and dispatch UDP peer announcements.
fn udp_listener_loop(
    socket: UdpSocket,
    inner: Arc<TransportInner>,
    stop: Arc<StopControl>,
    config: TransportConfig,
    _discovery_port: u16,
) {
    let mut buffer = vec![0_u8; config.max_frame_bytes.clamp(1, TRANSPORT_UDP_BUFFER_BYTES)];
    while !stop.is_stopped() {
        match socket.recv_from(&mut buffer) {
            Ok((length, address)) => {
                match serde_json::from_slice::<Value>(&buffer[..length]).and_then(|value| {
                    let envelope = json!({
                        "type": "_peer_announce",
                        "from": address.ip().to_string(),
                        "payload": value,
                        "timestamp": 0.0,
                        "headers": {"remote_addr": address.ip().to_string()},
                    });
                    decode_wire_message(envelope, &address.ip().to_string())
                        .map_err(|error| serde_json::Error::io(io::Error::other(error.to_string())))
                }) {
                    Ok(message) => dispatch_message(&inner, message),
                    Err(_) => {
                        inner.counters.decode_errors.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                if stop.wait(Duration::from_millis(TRANSPORT_SOCKET_ERROR_POLL_MS)) {
                    break;
                }
            }
            Err(_) => {
                inner
                    .counters
                    .listener_errors
                    .fetch_add(1, Ordering::Relaxed);
                if stop.wait(Duration::from_millis(TRANSPORT_SOCKET_ERROR_POLL_MS)) {
                    break;
                }
            }
        }
    }
}

/// Periodically announce the node to the configured explicit destination.
fn udp_announcer_loop(
    socket: UdpSocket,
    inner: Arc<TransportInner>,
    stop: Arc<StopControl>,
    config: TransportConfig,
    discovery_port: u16,
) {
    let node_id = lock_string(&inner.node_id).clone();
    let port = inner.port.load(Ordering::Acquire);
    let announcement = serde_json::to_vec(&json!({
        "id": node_id,
        "port": port,
        "cells": 0,
        "version": TRANSPORT_WIRE_VERSION,
    }))
    .unwrap_or_default();
    let destination = format!("{}:{}", config.broadcast_address, discovery_port);
    while !stop.is_stopped() {
        if socket.send_to(&announcement, &destination).is_err() {
            inner
                .counters
                .listener_errors
                .fetch_add(1, Ordering::Relaxed);
        }
        if stop.wait(config.broadcast_interval) {
            break;
        }
    }
}

/// Admit a message to the bounded queue and invoke the matching handler.
fn dispatch_message(inner: &Arc<TransportInner>, message: Message) {
    if message.validate().is_err() {
        inner.counters.decode_errors.fetch_add(1, Ordering::Relaxed);
        return;
    }
    let value = match serde_json::to_value(&message) {
        Ok(value) => value,
        Err(_) => {
            inner.counters.decode_errors.fetch_add(1, Ordering::Relaxed);
            return;
        }
    };
    let queued = lock_channel(inner)
        .as_ref()
        .is_some_and(|channel| channel.put(value, Some(Duration::ZERO)));
    if !queued {
        inner
            .counters
            .dropped_messages
            .fetch_add(1, Ordering::Relaxed);
    }
    inner
        .counters
        .received_messages
        .fetch_add(1, Ordering::Relaxed);

    let handler = lock_handlers(inner).get(&message.message_type).cloned();
    if let Some(handler) = handler {
        let result = catch_unwind(AssertUnwindSafe(|| handler(message)));
        if result.is_err() {
            inner
                .counters
                .handler_errors
                .fetch_add(1, Ordering::Relaxed);
        }
    }
}

/// Decode a bounded UTF-8/JSON frame into the transport message contract.
fn decode_frame(frame: &[u8], remote_address: &str) -> Result<Message, TransportError> {
    let text = std::str::from_utf8(frame)
        .map_err(|error| TransportError::InvalidFrame(error.to_string()))?;
    let value: Value = serde_json::from_str(text)
        .map_err(|error| TransportError::InvalidFrame(error.to_string()))?;
    decode_wire_message(value, remote_address)
}

/// Normalize Python-style `from`/`to` fields into the Rust port message.
fn decode_wire_message(value: Value, remote_address: &str) -> Result<Message, TransportError> {
    let object = value.as_object().ok_or_else(|| {
        TransportError::InvalidMessage("message must be a JSON object".to_owned())
    })?;
    let message_type = object
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("message")
        .to_owned();
    let source = object
        .get("from")
        .or_else(|| object.get("source"))
        .and_then(Value::as_str)
        .unwrap_or(remote_address)
        .to_owned();
    let target = object
        .get("to")
        .or_else(|| object.get("target"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    let payload = object
        .get("payload")
        .cloned()
        .unwrap_or_else(|| value.clone());
    let payload: JsonValue = serde_json::from_value(payload)
        .map_err(|error| TransportError::InvalidMessage(error.to_string()))?;
    let timestamp = object
        .get("timestamp")
        .and_then(Value::as_f64)
        .unwrap_or(0.0);
    let locale = object
        .get("locale")
        .and_then(Value::as_str)
        .unwrap_or("en")
        .to_owned();
    let mut headers: JsonObject = object
        .get("headers")
        .cloned()
        .map(serde_json::from_value)
        .transpose()
        .map_err(|error| TransportError::InvalidMessage(error.to_string()))?
        .unwrap_or_default();
    if !remote_address.is_empty() {
        headers.insert(
            "remote_addr".to_owned(),
            JsonValue::String(remote_address.to_owned()),
        );
    }
    let message = Message {
        message_type,
        source,
        target,
        payload,
        timestamp,
        locale,
        headers,
    };
    message
        .validate()
        .map_err(|error| TransportError::InvalidMessage(error.to_owned()))?;
    Ok(message)
}

/// Read exactly one newline-delimited bounded frame from a stream.
fn read_frame(stream: &mut TcpStream, max_frame_bytes: usize) -> Result<Vec<u8>, TransportError> {
    let mut frame = Vec::with_capacity(max_frame_bytes.min(4096));
    let mut buffer = [0_u8; 4096];
    loop {
        let length = stream
            .read(&mut buffer)
            .map_err(|error| TransportError::Io {
                operation: "tcp read".to_owned(),
                message: error.to_string(),
            })?;
        if length == 0 {
            break;
        }
        if let Some(newline) = buffer[..length].iter().position(|byte| *byte == b'\n') {
            if frame.len().saturating_add(newline) > max_frame_bytes {
                return Err(TransportError::FrameTooLarge {
                    actual: frame.len().saturating_add(newline),
                    max: max_frame_bytes,
                });
            }
            frame.extend_from_slice(&buffer[..newline]);
            break;
        }
        if frame.len().saturating_add(length) > max_frame_bytes {
            return Err(TransportError::FrameTooLarge {
                actual: frame.len().saturating_add(length),
                max: max_frame_bytes,
            });
        }
        frame.extend_from_slice(&buffer[..length]);
    }
    if frame.is_empty() {
        return Err(TransportError::InvalidFrame("empty frame".to_owned()));
    }
    Ok(frame)
}

fn lock_string<'a>(mutex: &'a Mutex<String>) -> MutexGuard<'a, String> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

fn lock_channel<'a>(inner: &'a Arc<TransportInner>) -> MutexGuard<'a, Option<Arc<RingChannel>>> {
    inner.channel.lock().unwrap_or_else(PoisonError::into_inner)
}

fn lock_handlers<'a>(
    inner: &'a Arc<TransportInner>,
) -> MutexGuard<'a, BTreeMap<String, MessageHandler>> {
    inner
        .handlers
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
}

fn join_handles(handles: Vec<JoinHandle<()>>) {
    let current = thread::current().id();
    for handle in handles {
        if handle.thread().id() != current {
            let _ = handle.join();
        }
    }
}
