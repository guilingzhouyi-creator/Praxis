//! Emit the Rust-native fixed-work session admission evidence.

use l1_kernel_rs::benchmark::{BenchmarkEvidence, BenchmarkMetadata, FixedWorkSpec};
use l1_kernel_rs::benchmark_runner::run_session_book;

fn env_or(name: &str, fallback: &str) -> String {
    std::env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| fallback.to_owned())
}

fn main() {
    let spec = FixedWorkSpec::new("session.book.admission", 4_096, vec![1, 2, 4], 3)
        .expect("session benchmark spec is valid");
    let report = run_session_book(spec, 16).expect("session benchmark completed");
    let metadata = BenchmarkMetadata::new(
        std::env::consts::OS,
        std::env::consts::ARCH,
        env_or("PRAXIS_RUST_RUNTIME", "rustc"),
        env_or("PRAXIS_GIT_REVISION", "unknown"),
        env_or("PRAXIS_RUST_RUNNER", env!("CARGO_PKG_VERSION")),
    )
    .expect("benchmark metadata is valid");
    let evidence = BenchmarkEvidence::new(metadata, report).expect("evidence is complete");
    println!(
        "{}",
        evidence.to_json().expect("evidence serializes to JSON")
    );
}
