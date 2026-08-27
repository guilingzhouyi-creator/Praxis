//! Emit fixed-work bounded TerminalBook snapshot-page evidence.

use l1_kernel_rs::benchmark::{BenchmarkEvidence, BenchmarkMetadata, FixedWorkSpec};
use l1_kernel_rs::benchmark_runner::run_terminal_book_snapshot_page;

fn env_or(name: &str, fallback: &str) -> String {
    std::env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| fallback.to_owned())
}

fn main() {
    let spec = FixedWorkSpec::new("terminal.book.snapshot_page", 4_096, vec![1, 2, 4], 3)
        .expect("snapshot page benchmark specification is valid");
    let report = run_terminal_book_snapshot_page(spec, 4_096, 64)
        .expect("snapshot page benchmark completed");
    let metadata = BenchmarkMetadata::new(
        std::env::consts::OS,
        std::env::consts::ARCH,
        env_or("PRAXIS_RUST_RUNTIME", "rustc"),
        env_or("PRAXIS_GIT_REVISION", "unknown"),
        env_or("PRAXIS_RUST_RUNNER", env!("CARGO_PKG_VERSION")),
    )
    .expect("benchmark metadata is valid");
    let evidence =
        BenchmarkEvidence::new(metadata, report).expect("benchmark evidence is complete");
    println!(
        "{}",
        evidence.to_json().expect("benchmark evidence serializes")
    );
}
