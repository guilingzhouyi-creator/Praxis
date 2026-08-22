//! Independent fixed-work benchmark schema tests for the Rust kernel.

use l1_kernel_rs::benchmark::{
    BENCHMARK_SCHEMA_VERSION, BenchmarkReport, BenchmarkResources, BenchmarkSample, FixedWorkSpec,
};

fn spec() -> FixedWorkSpec {
    FixedWorkSpec::new("substrate.queue", 100, vec![1, 2, 4], 2).expect("valid spec")
}

fn sample(workers: u32, round: u32) -> BenchmarkSample {
    BenchmarkSample {
        workers,
        round,
        completed_work_items: 100,
        elapsed_ns: 1_000,
        p95_latency_ns: 40,
        p99_latency_ns: 50,
        queue_wait_ns: 10,
        lock_wait_ns: 5,
        rejected: 0,
        errors: 0,
        resources: BenchmarkResources::unavailable(),
    }
}

#[test]
fn fixed_work_spec_rejects_invalid_sweeps() {
    assert!(FixedWorkSpec::new("x", 0, vec![1], 1).is_err());
    assert!(FixedWorkSpec::new("x", 1, vec![0], 1).is_err());
    assert!(FixedWorkSpec::new("x", 1, vec![1, 1], 1).is_err());
    assert!(FixedWorkSpec::new("x", 1, vec![1], 0).is_err());
}

#[test]
fn resource_samples_require_explicit_availability_sources() {
    let mut resources = BenchmarkResources::unavailable();
    resources.cpu_time_ns = Some(1);
    assert_eq!(
        resources.validate(),
        Err("CPU resource value and source disagree")
    );
    resources.cpu_source = "test.cpu".to_owned();
    assert!(resources.validate().is_ok());
    resources.memory_source.clear();
    assert_eq!(
        resources.validate(),
        Err("resource sample sources must not be empty")
    );
}

#[test]
fn report_rejects_incomplete_or_unknown_samples() {
    let mut report = BenchmarkReport::new(spec());
    assert!(report.push(sample(8, 0)).is_err());
    let mut incomplete = sample(1, 0);
    incomplete.completed_work_items = 99;
    assert!(report.push(incomplete).is_err());
    let mut invalid_round = sample(1, 2);
    invalid_round.round = 2;
    assert!(report.push(invalid_round).is_err());
    let mut invalid_tail = sample(1, 0);
    invalid_tail.p99_latency_ns = 39;
    assert!(report.push(invalid_tail).is_err());
}

#[test]
fn validate_rejects_duplicates_after_deserialization() {
    let mut report = BenchmarkReport::new(spec());
    report.push(sample(1, 0)).expect("valid sample");
    report.samples.push(sample(1, 0));
    assert_eq!(report.validate(), Err("duplicate worker/round sample"));
}

#[test]
fn report_round_trips_and_validates_schema() {
    let mut report = BenchmarkReport::new(spec());
    report.push(sample(1, 0)).expect("valid sample");
    assert_eq!(report.schema_version, BENCHMARK_SCHEMA_VERSION);
    let encoded = serde_json::to_string(&report).expect("report serializes");
    let decoded: BenchmarkReport = serde_json::from_str(&encoded).expect("report parses");
    assert_eq!(decoded, report);
    assert!(decoded.validate().is_ok());
    assert!(decoded.validate_complete().is_err());
    assert_eq!(decoded.samples[0].throughput_ops_per_sec(), 100_000_000);
}

#[test]
fn evidence_envelope_round_trips_only_complete_reports() {
    let configured = spec();
    let mut report = BenchmarkReport::new(configured.clone());
    for &workers in &configured.workers {
        for round in 0..configured.rounds {
            report.push(sample(workers, round)).expect("valid sample");
        }
    }
    let metadata =
        l1_kernel_rs::benchmark::BenchmarkMetadata::new("linux", "x86_64", "rustc", "rev", "test")
            .expect("valid metadata");
    let evidence = l1_kernel_rs::benchmark::BenchmarkEvidence::new(metadata, report)
        .expect("complete evidence");
    let encoded = evidence.to_json().expect("evidence serializes");
    assert_eq!(
        l1_kernel_rs::benchmark::BenchmarkEvidence::from_json(&encoded).expect("evidence parses"),
        evidence
    );
    assert!(
        l1_kernel_rs::benchmark::BenchmarkMetadata::new("", "x86_64", "rustc", "rev", "test")
            .is_err()
    );
}

#[test]
fn complete_report_covers_every_worker_and_round() {
    let configured = spec();
    let mut report = BenchmarkReport::new(configured.clone());
    for &workers in &configured.workers {
        for round in 0..configured.rounds {
            report.push(sample(workers, round)).expect("valid sample");
        }
    }
    assert!(report.validate_complete().is_ok());
}
