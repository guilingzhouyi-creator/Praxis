//! Emit a release-mode fixed-work Rust runtime batch-admission report.

use l1_kernel_rs::benchmark::{BenchmarkEvidence, BenchmarkMetadata, FixedWorkSpec};
use l1_kernel_rs::benchmark_runner::run_runtime_batch;

fn env_or(name: &str, fallback: &str) -> String {
    std::env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| fallback.to_owned())
}

fn env_usize(name: &str, fallback: usize) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(fallback)
}

fn main() {
    let spec = FixedWorkSpec::new("runtime.batch_submit_reap", 4_096, vec![1, 2, 4], 3)
        .expect("benchmark specification is valid");
    let batch_size = env_usize("PRAXIS_RUNTIME_BATCH_SIZE", 32);
    let report = run_runtime_batch(spec, batch_size).expect("runtime batch benchmark completed");
    let metadata = BenchmarkMetadata::new(
        std::env::consts::OS,
        std::env::consts::ARCH,
        env_or("PRAXIS_RUST_RUNTIME", "rustc"),
        env_or("PRAXIS_GIT_REVISION", "unknown"),
        env_or("PRAXIS_RUST_RUNNER", env!("CARGO_PKG_VERSION")),
    )
    .expect("benchmark metadata is valid");
    let evidence = BenchmarkEvidence::new(metadata, report).expect("evidence is complete");
    println!("{}", evidence.to_json().expect("benchmark serializes"));
}
