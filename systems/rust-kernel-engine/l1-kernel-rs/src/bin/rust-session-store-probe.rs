//! Process-level probe for the Rust session-store checkpoint boundary.
//!
//! This binary exists only for cross-language contract tests. It creates one
//! deterministic unclean checkpoint or validates the checkpoint already
//! present under a supplied state root. It has no boot, host, or runtime
//! authority and must not be used as a production session service.

use std::env;
use std::path::Path;
use std::process::ExitCode;

use l1_kernel_rs::session::{SessionBook, SessionSpec};
use l1_kernel_rs::session_store::SessionStore;

fn usage() -> &'static str {
    "usage: rust-session-store-probe <emit|validate> <state-root>"
}

fn emit(root: &Path) -> Result<(), String> {
    let mut store = SessionStore::open(root).map_err(|error| error.to_string())?;
    let book = SessionBook::new(2).map_err(|error| format!("session book: {error:?}"))?;
    let session = book
        .create(SessionSpec::new(
            "session-probe",
            "agent-probe",
            "cell-probe",
            "operator",
            8,
        ))
        .map_err(|error| format!("session create: {error:?}"))?;
    session
        .activate()
        .map_err(|error| format!("session activate: {error:?}"))?;
    session
        .append_input("message-probe", "process-boundary", 42)
        .map_err(|error| format!("session input: {error:?}"))?;
    let document = store
        .save(&book, false)
        .map_err(|error| error.to_string())?;
    println!(
        "{}",
        serde_json::to_string(&document).map_err(|error| error.to_string())?
    );
    Ok(())
}

fn validate(root: &Path) -> Result<(), String> {
    let store = SessionStore::open(root).map_err(|error| error.to_string())?;
    let document = store.document().map_err(|error| error.to_string())?;
    println!(
        "{}",
        serde_json::to_string(&document).map_err(|error| error.to_string())?
    );
    Ok(())
}

fn run() -> Result<(), String> {
    let mut args = env::args_os();
    let _program = args.next();
    let command = args
        .next()
        .ok_or_else(|| usage().to_owned())?
        .to_string_lossy()
        .into_owned();
    let root = args.next().ok_or_else(|| usage().to_owned())?;
    if args.next().is_some() {
        return Err(usage().to_owned());
    }
    let root = Path::new(&root);
    match command.as_str() {
        "emit" => emit(root),
        "validate" => validate(root),
        _ => Err(usage().to_owned()),
    }
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("rust session-store probe failed: {error}");
            ExitCode::FAILURE
        }
    }
}
