//! Emit Rust-native fixed-work registry admission and lookup evidence.

use l1_kernel_rs::benchmark::{BenchmarkEvidence, BenchmarkMetadata, FixedWorkSpec};
use l1_kernel_rs::benchmark_runner::run_registry_base;

fn env_or(name: &str, fallback: &str) -> String {
    std::env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| fallback.to_owned())
}

fn main() {
    let spec = FixedWorkSpec::new("registry.base.lookup", 4_096, vec![1, 2, 4], 3)
        .expect("registry benchmark spec is valid");
    let report = run_registry_base(spec).expect("registry benchmark completed");
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
