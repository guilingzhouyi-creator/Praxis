//! Run the read-only Rust kernel entry preflight.
//!
//! The command reads one JSON request from stdin and emits one JSON report.
//! It requires explicit assembly and host state observations; no defaults or
//! filesystem probes are performed.

use std::io::{self, Read};
use std::process::ExitCode;

use l1_kernel_rs::preflight::{PreflightRequest, inspect};

fn main() -> ExitCode {
    let mut input = String::new();
    if let Err(error) = io::stdin().read_to_string(&mut input) {
        eprintln!("rust kernel preflight input failed: {error}");
        return ExitCode::FAILURE;
    }
    let request = match serde_json::from_str::<PreflightRequest>(&input) {
        Ok(request) => request,
        Err(error) => {
            eprintln!("rust kernel preflight request rejected: {error}");
            return ExitCode::FAILURE;
        }
    };
    match inspect(request) {
        Ok(report) => match serde_json::to_string(&report) {
            Ok(encoded) => {
                println!("{encoded}");
                ExitCode::SUCCESS
            }
            Err(error) => {
                eprintln!("rust kernel preflight report failed: {error}");
                ExitCode::FAILURE
            }
        },
        Err(error) => {
            eprintln!("rust kernel preflight rejected: {error:?}");
            ExitCode::FAILURE
        }
    }
}
