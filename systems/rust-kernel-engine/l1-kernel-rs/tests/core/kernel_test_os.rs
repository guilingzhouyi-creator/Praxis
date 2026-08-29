//! Independent OS lifecycle-coordinator tests for the Rust kernel.

use std::sync::{
    Arc, Barrier, Mutex,
    atomic::{AtomicUsize, Ordering},
    mpsc,
};
use std::thread;
use std::time::{Duration, Instant};

use l1_kernel_rs::os::{
    DEFAULT_WATCHDOG_INTERVAL_MS, OS_CONTRACT_VERSION, OsCoordinator, OsError, OsState, get_os,
    reset_os,
};
use l1_kernel_rs::watchdog::{WATCHDOG_CONTRACT_VERSION, WatchdogReport};
use serde_json::json;

fn report() -> WatchdogReport {
    WatchdogReport {
        contract_version: WATCHDOG_CONTRACT_VERSION,
        process_count: 0,
        zombie_count: 0,
        zombie_limit_exceeded: false,
        idle_processes: Vec::new(),
        interrupt_alerts: Vec::new(),
    }
}

#[test]
fn missing_boot_handler_fails_closed() {
    let os = OsCoordinator::new();

    assert_eq!(os.boot(None), Err(OsError::NoBootHandler));
    assert_eq!(os.status().state, OsState::Crashed);
}

#[test]
fn boot_success_preserves_result_and_agent_count() {
    let os = OsCoordinator::new();
    os.register_boot_handler(|config| {
        assert_eq!(config, Some(json!({"profile": "test"})));
        Ok(json!({"success": true, "agent_count": 3, "source": "host"}))
    });

    let boot = os
        .boot(Some(json!({"profile": "test"})))
        .expect("boot should succeed");
    assert_eq!(boot.contract_version, OS_CONTRACT_VERSION);
    assert!(boot.success);
    assert_eq!(boot.state, OsState::Running);
    assert_eq!(boot.agent_count, 3);
    assert_eq!(boot.data["source"], "host");
    assert_eq!(os.status().state, OsState::Running);
}

#[test]
fn boot_error_and_panic_enter_crashed_state() {
    let failed = OsCoordinator::new();
    failed.register_boot_handler(|_| Err("configuration rejected".to_owned()));
    assert_eq!(
        failed.boot(None),
        Err(OsError::HandlerFailed {
            stage: "boot".to_owned(),
            message: "configuration rejected".to_owned(),
        })
    );
    assert_eq!(failed.status().state, OsState::Crashed);

    let panicked = OsCoordinator::new();
    panicked.register_boot_handler(|_| panic!("test panic"));
    assert_eq!(
        panicked.boot(None),
        Err(OsError::HandlerFailed {
            stage: "boot".to_owned(),
            message: "callback panicked".to_owned(),
        })
    );
    assert_eq!(panicked.status().state, OsState::Crashed);
}

#[test]
fn boot_rejects_reentrant_active_request() {
    let os = OsCoordinator::new();
    let entered = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let entered_handler = Arc::clone(&entered);
    let release_handler = Arc::clone(&release);
    os.register_boot_handler(move |_| {
        entered_handler.wait();
        release_handler.wait();
        Ok(json!({"agent_count": 1}))
    });

    let boot_os = os.clone();
    let thread = thread::spawn(move || boot_os.boot(None));
    entered.wait();
    assert_eq!(
        os.boot(None),
        Err(OsError::AlreadyActive(OsState::Starting))
    );
    release.wait();
    assert!(thread.join().expect("boot thread").is_ok());
}

#[test]
fn shutdown_runs_hooks_persistence_and_resets_in_order() {
    let os = OsCoordinator::new();
    os.register_boot_handler(|_| Ok(json!({"agent_count": 2})));
    os.boot(None).expect("boot");

    let order = Arc::new(Mutex::new(Vec::<String>::new()));
    let record = |label: &'static str, order: &Arc<Mutex<Vec<String>>>| {
        let order = Arc::clone(order);
        move || {
            order.lock().expect("order lock").push(label.to_owned());
            Ok(())
        }
    };
    os.on_shutdown(record("hook_0", &order));
    os.on_shutdown(record("hook_1", &order));

    let persistence_order = Arc::clone(&order);
    os.register_shutdown_handler(move || {
        persistence_order
            .lock()
            .expect("order lock")
            .push("memories".to_owned());
        Ok(json!({"results": {"saved": 2}}))
    });
    let terminal_order = Arc::clone(&order);
    os.register_terminal_reset(move || {
        terminal_order
            .lock()
            .expect("order lock")
            .push("reset_term".to_owned());
        Ok(())
    });
    let cell_order = Arc::clone(&order);
    os.register_cell_reset(move || {
        cell_order
            .lock()
            .expect("order lock")
            .push("reset_cell".to_owned());
        Ok(())
    });

    let shutdown = os.shutdown(Some(Duration::from_millis(100)));
    assert_eq!(shutdown.contract_version, OS_CONTRACT_VERSION);
    assert!(shutdown.success);
    assert_eq!(shutdown.state, OsState::Down);
    assert_eq!(shutdown.results["hook_0"], "ok");
    assert_eq!(shutdown.results["hook_1"], "ok");
    assert_eq!(shutdown.results["memories"], json!({"saved": 2}));
    assert_eq!(shutdown.results["reset_term"], "ok");
    assert_eq!(shutdown.results["reset_cell"], "ok");
    assert_eq!(shutdown.results["reset"], "ok");
    assert_eq!(
        *order.lock().expect("order lock"),
        vec!["hook_0", "hook_1", "memories", "reset_term", "reset_cell"]
    );
    assert_eq!(os.status().state, OsState::Down);
}

#[test]
fn shutdown_retains_callback_errors_panics_and_timeouts() {
    let os = OsCoordinator::new();
    os.on_shutdown(|| Err("hook failed".to_owned()));
    os.on_shutdown(|| panic!("hook panic"));
    os.on_shutdown(|| {
        thread::sleep(Duration::from_millis(100));
        Ok(())
    });
    os.register_shutdown_handler(|| Err("persistence failed".to_owned()));
    os.register_terminal_reset(|| panic!("terminal panic"));
    os.register_cell_reset(|| {
        thread::sleep(Duration::from_millis(100));
        Ok(())
    });

    let started = Instant::now();
    let shutdown = os.shutdown(Some(Duration::from_millis(10)));
    assert!(started.elapsed() < Duration::from_millis(250));
    assert!(shutdown.success);
    assert_eq!(shutdown.state, OsState::Down);
    assert_eq!(shutdown.results["hook_0"], "error: hook failed");
    assert_eq!(shutdown.results["hook_1"], "error: callback panicked");
    assert_eq!(shutdown.results["hook_2"], "timeout");
    assert_eq!(shutdown.results["memories"], "error: persistence failed");
    assert_eq!(shutdown.results["reset_term"], "error: callback panicked");
    assert_eq!(shutdown.results["reset_cell"], "timeout");
}

#[test]
fn restart_runs_shutdown_then_boot_and_preserves_handlers() {
    let os = OsCoordinator::new();
    let boots = Arc::new(AtomicUsize::new(0));
    let boot_count = Arc::clone(&boots);
    os.register_boot_handler(move |_| {
        let count = boot_count.fetch_add(1, Ordering::SeqCst) + 1;
        Ok(json!({"agent_count": count}))
    });
    os.register_shutdown_handler(|| Ok(json!({"results": {"persisted": true}})));
    os.boot(None).expect("initial boot");

    let (shutdown, boot) = os
        .restart(
            Some(json!({"restart": true})),
            Some(Duration::from_millis(100)),
        )
        .expect("restart");
    assert_eq!(shutdown.state, OsState::Down);
    assert_eq!(boot.state, OsState::Running);
    assert_eq!(boot.agent_count, 2);
    assert_eq!(boots.load(Ordering::SeqCst), 2);
}

#[test]
fn watchdog_ticks_and_repeated_start_are_bounded() {
    let os = OsCoordinator::new();
    let ticks = Arc::new(AtomicUsize::new(0));
    let tick_count = Arc::clone(&ticks);
    os.register_watchdog_handler(move || {
        tick_count.fetch_add(1, Ordering::SeqCst);
        Ok(report())
    });

    let started = Instant::now();
    os.watchdog_start(Duration::from_millis(5))
        .expect("watchdog start");
    os.watchdog_start(Duration::from_millis(5))
        .expect("duplicate start is idempotent");
    while ticks.load(Ordering::SeqCst) == 0 && started.elapsed() < Duration::from_millis(200) {
        thread::yield_now();
    }
    assert!(ticks.load(Ordering::SeqCst) > 0);
    assert!(os.status().watchdog);
    assert!(os.last_watchdog().is_some());

    let stop_started = Instant::now();
    os.watchdog_stop();
    assert!(stop_started.elapsed() < Duration::from_millis(100));
    assert!(!os.status().watchdog);
}

#[test]
fn watchdog_tick_reports_failures_and_keeps_last_success() {
    let os = OsCoordinator::new();
    os.register_watchdog_handler(|| Err("observer unavailable".to_owned()));
    assert_eq!(
        os.watchdog_tick(),
        Err(OsError::WatchdogFailed("observer unavailable".to_owned()))
    );
    assert_eq!(os.status().watchdog_errors, 1);
    assert!(os.last_watchdog().is_none());

    os.register_watchdog_handler(|| panic!("observer panic"));
    assert_eq!(
        os.watchdog_tick(),
        Err(OsError::WatchdogFailed("callback panicked".to_owned()))
    );
    assert_eq!(os.status().watchdog_errors, 2);

    os.register_watchdog_handler(|| Ok(report()));
    assert!(os.watchdog_tick().expect("watchdog tick").is_some());
    assert_eq!(os.status().watchdog_errors, 2);
    assert!(os.last_watchdog().is_some());
}

#[test]
fn watchdog_interval_zero_fails_closed_and_missing_handler_is_noop() {
    let os = OsCoordinator::new();
    assert_eq!(
        os.watchdog_start(Duration::ZERO),
        Err(OsError::InvalidWatchdogInterval)
    );
    assert_eq!(os.watchdog_tick(), Ok(None));
    assert_eq!(DEFAULT_WATCHDOG_INTERVAL_MS, 60_000);
}

#[test]
fn concurrent_shutdown_reports_already_stopping_without_duplicate_callbacks() {
    let os = OsCoordinator::new();
    let (entered_sender, entered_receiver) = mpsc::channel();
    let (release_sender, release_receiver) = mpsc::channel();
    let release_receiver = Arc::new(Mutex::new(release_receiver));
    let calls = Arc::new(AtomicUsize::new(0));
    let handler_calls = Arc::clone(&calls);
    let release_receiver_handler = Arc::clone(&release_receiver);
    os.register_shutdown_handler(move || {
        handler_calls.fetch_add(1, Ordering::SeqCst);
        entered_sender.send(()).expect("entered signal");
        release_receiver_handler
            .lock()
            .expect("release lock")
            .recv_timeout(Duration::from_secs(1))
            .expect("release signal");
        Ok(json!({"results": {}}))
    });

    let shutdown_os = os.clone();
    let first = thread::spawn(move || shutdown_os.shutdown(Some(Duration::from_secs(1))));
    entered_receiver
        .recv_timeout(Duration::from_secs(1))
        .expect("shutdown entered");
    let second = os.shutdown(Some(Duration::from_millis(10)));
    assert_eq!(second.state, OsState::Stopping);
    assert_eq!(second.results["reason"], "already stopping");
    release_sender.send(()).expect("release");
    assert_eq!(first.join().expect("shutdown thread").state, OsState::Down);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn process_wide_singleton_can_be_reset() {
    reset_os();
    let first = get_os();
    let second = get_os();
    assert!(Arc::ptr_eq(&first, &second));
    reset_os();
    let third = get_os();
    assert!(!Arc::ptr_eq(&first, &third));
    reset_os();
}
