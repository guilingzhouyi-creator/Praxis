//! Run one explicit Rust kernel entry operation.
//!
//! The command reads one bounded JSON request from stdin. It requires an
//! explicit assembly, state root, runtime configuration, and operation; it
//! never infers host defaults or selects a Python fallback.

use std::io::{self, Read};
use std::process::ExitCode;

use l1_kernel_rs::entry::{EntryRequest, MAX_ENTRY_REQUEST_BYTES, execute};

fn main() -> ExitCode {
    let mut bytes = Vec::new();
    let limit = MAX_ENTRY_REQUEST_BYTES.saturating_add(1) as u64;
    if let Err(error) = io::stdin().lock().take(limit).read_to_end(&mut bytes) {
        eprintln!("rust kernel entry input failed: {error}");
        return ExitCode::FAILURE;
    }
    if bytes.len() > MAX_ENTRY_REQUEST_BYTES {
        eprintln!("rust kernel entry request exceeds {MAX_ENTRY_REQUEST_BYTES} bytes");
        return ExitCode::FAILURE;
    }
    let request = match serde_json::from_slice::<EntryRequest>(&bytes) {
        Ok(request) => request,
        Err(error) => {
            eprintln!("rust kernel entry request rejected: {error}");
            return ExitCode::FAILURE;
        }
    };
    match execute(request) {
        Ok(report) => match serde_json::to_string(&report) {
            Ok(encoded) => {
                println!("{encoded}");
                ExitCode::SUCCESS
            }
            Err(error) => {
                eprintln!("rust kernel entry report failed: {error}");
                ExitCode::FAILURE
            }
        },
        Err(error) => {
            eprintln!("rust kernel entry rejected: {error}");
            ExitCode::FAILURE
        }
    }
}
