//! Typed fixed-work benchmark schema for the Rust-first rewrite.

use std::collections::HashSet;

use serde::{Deserialize, Serialize};

/// Version of the benchmark report consumed by the R2 evidence gate.
pub const BENCHMARK_SCHEMA_VERSION: u32 = 2;
const NANOSECONDS_PER_SECOND: u128 = 1_000_000_000;

/// Fixed workload and worker sweep supplied by a benchmark runner.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FixedWorkSpec {
    /// Schema version for report consumers.
    pub schema_version: u32,
    /// Stable workload identifier.
    pub workload: String,
    /// Total work shared across all worker counts.
    pub total_work_items: u64,
    /// Worker counts that the report must cover.
    pub workers: Vec<u32>,
    /// Number of repeated samples per worker count.
    pub rounds: u32,
}

impl FixedWorkSpec {
    /// Build a validated fixed-work specification.
    pub fn new(
        workload: impl Into<String>,
        total_work_items: u64,
        workers: Vec<u32>,
        rounds: u32,
    ) -> Result<Self, &'static str> {
        if total_work_items == 0 {
            return Err("total work must be positive");
        }
        if workers.is_empty() || workers.contains(&0) {
            return Err("worker sweep must contain only positive counts");
        }
        let unique_workers: HashSet<u32> = workers.iter().copied().collect();
        if unique_workers.len() != workers.len() {
            return Err("worker sweep must not contain duplicates");
        }
        if rounds == 0 {
            return Err("rounds must be positive");
        }
        Ok(Self {
            schema_version: BENCHMARK_SCHEMA_VERSION,
            workload: workload.into(),
            total_work_items,
            workers,
            rounds,
        })
    }

    /// Return whether a worker count belongs to this sweep.
    pub fn accepts_workers(&self, workers: u32) -> bool {
        self.workers.contains(&workers)
    }
}

/// One fixed-work measurement row; all durations are integer nanoseconds.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BenchmarkSample {
    /// Worker count for this sample.
    pub workers: u32,
    /// Zero-based repetition number within the worker count.
    pub round: u32,
    /// Work items completed by this sample.
    pub completed_work_items: u64,
    /// Wall-clock duration for the fixed work.
    pub elapsed_ns: u64,
    /// P95 operation or batch latency.
    pub p95_latency_ns: u64,
    /// P99 operation or batch latency.
    pub p99_latency_ns: u64,
    /// Aggregate scheduler queue wait.
    pub queue_wait_ns: u64,
    /// Aggregate queue-admission lock/backpressure wait.
    pub lock_wait_ns: u64,
    /// Work rejected by a bounded queue.
    pub rejected: u64,
    /// Work that failed with an execution error.
    pub errors: u64,
}

impl BenchmarkSample {
    /// Derive whole completed operations per second without adding a wire field.
    pub fn throughput_ops_per_sec(&self) -> u64 {
        if self.elapsed_ns == 0 {
            return 0;
        }
        let throughput = u128::from(self.completed_work_items) * NANOSECONDS_PER_SECOND
            / u128::from(self.elapsed_ns);
        throughput.min(u128::from(u64::MAX)) as u64
    }
}

/// Evidence report that rejects incomplete or non-fixed-work samples.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BenchmarkReport {
    /// Schema version for report consumers.
    pub schema_version: u32,
    /// Fixed workload specification.
    pub spec: FixedWorkSpec,
    /// Recorded samples, usually one row per worker/round pair.
    pub samples: Vec<BenchmarkSample>,
}

/// Explicit host and runner metadata attached to one evidence report.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BenchmarkMetadata {
    /// Operating-system identifier supplied by the runner.
    pub platform: String,
    /// Target architecture supplied by the runner.
    pub architecture: String,
    /// Runtime/compiler identifier supplied by the runner.
    pub runtime: String,
    /// Source revision supplied by the build environment.
    pub git_revision: String,
    /// Runner version or package identifier.
    pub runner: String,
}

impl BenchmarkMetadata {
    /// Build metadata and reject empty identity fields.
    pub fn new(
        platform: impl Into<String>,
        architecture: impl Into<String>,
        runtime: impl Into<String>,
        git_revision: impl Into<String>,
        runner: impl Into<String>,
    ) -> Result<Self, &'static str> {
        let metadata = Self {
            platform: platform.into(),
            architecture: architecture.into(),
            runtime: runtime.into(),
            git_revision: git_revision.into(),
            runner: runner.into(),
        };
        metadata.validate()?;
        Ok(metadata)
    }

    /// Validate that evidence can be attributed to a concrete runner.
    pub fn validate(&self) -> Result<(), &'static str> {
        if [
            self.platform.as_str(),
            self.architecture.as_str(),
            self.runtime.as_str(),
            self.git_revision.as_str(),
            self.runner.as_str(),
        ]
        .iter()
        .any(|value| value.is_empty())
        {
            return Err("benchmark metadata fields must not be empty");
        }
        Ok(())
    }
}

/// Versioned report envelope for external evidence storage.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BenchmarkEvidence {
    /// Evidence schema version; shares the fixed-work report version.
    pub schema_version: u32,
    /// Host and runner attribution.
    pub metadata: BenchmarkMetadata,
    /// Complete fixed-work measurements.
    pub report: BenchmarkReport,
}

impl BenchmarkEvidence {
    /// Build an evidence envelope only from a complete report.
    pub fn new(metadata: BenchmarkMetadata, report: BenchmarkReport) -> Result<Self, &'static str> {
        let evidence = Self {
            schema_version: BENCHMARK_SCHEMA_VERSION,
            metadata,
            report,
        };
        evidence.validate()?;
        Ok(evidence)
    }

    /// Validate schema, metadata, and complete fixed-work coverage.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version != BENCHMARK_SCHEMA_VERSION {
            return Err("unsupported benchmark evidence schema version");
        }
        self.metadata.validate()?;
        self.report.validate_complete()
    }

    /// Serialize validated evidence as stable pretty JSON.
    pub fn to_json(&self) -> Result<String, &'static str> {
        self.validate()?;
        serde_json::to_string_pretty(self).map_err(|_| "benchmark evidence serialization failed")
    }

    /// Parse and validate evidence produced by an external runner.
    pub fn from_json(document: &str) -> Result<Self, String> {
        let evidence: Self = serde_json::from_str(document).map_err(|error| error.to_string())?;
        evidence.validate().map_err(str::to_owned)?;
        Ok(evidence)
    }
}

impl BenchmarkReport {
    /// Create an empty report for a validated specification.
    pub fn new(spec: FixedWorkSpec) -> Self {
        Self {
            schema_version: BENCHMARK_SCHEMA_VERSION,
            spec,
            samples: Vec::new(),
        }
    }

    /// Append one sample after validating its fixed-work invariants.
    pub fn push(&mut self, sample: BenchmarkSample) -> Result<(), &'static str> {
        if !self.spec.accepts_workers(sample.workers) {
            return Err("sample worker count is outside the sweep");
        }
        if sample.round >= self.spec.rounds {
            return Err("sample round is outside the configured rounds");
        }
        if self
            .samples
            .iter()
            .any(|row| row.workers == sample.workers && row.round == sample.round)
        {
            return Err("duplicate worker/round sample");
        }
        if sample.completed_work_items != self.spec.total_work_items {
            return Err("sample completed work does not match fixed total");
        }
        if sample.elapsed_ns == 0 {
            return Err("sample elapsed time must be positive");
        }
        if sample.p99_latency_ns < sample.p95_latency_ns {
            return Err("sample p99 latency must not be below p95 latency");
        }
        if sample.errors > sample.completed_work_items {
            return Err("sample errors exceed completed work");
        }
        self.samples.push(sample);
        Ok(())
    }

    /// Validate all rows after deserialization or aggregation.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version != BENCHMARK_SCHEMA_VERSION
            || self.spec.schema_version != BENCHMARK_SCHEMA_VERSION
        {
            return Err("unsupported benchmark schema version");
        }
        let mut seen = HashSet::with_capacity(self.samples.len());
        for sample in &self.samples {
            if !self.spec.accepts_workers(sample.workers) {
                return Err("sample worker count is outside the sweep");
            }
            if sample.round >= self.spec.rounds {
                return Err("sample round is outside the configured rounds");
            }
            if !seen.insert((sample.workers, sample.round)) {
                return Err("duplicate worker/round sample");
            }
            if sample.completed_work_items != self.spec.total_work_items {
                return Err("sample completed work does not match fixed total");
            }
            if sample.elapsed_ns == 0 {
                return Err("sample elapsed time must be positive");
            }
            if sample.p99_latency_ns < sample.p95_latency_ns {
                return Err("sample p99 latency must not be below p95 latency");
            }
            if sample.errors > sample.completed_work_items {
                return Err("sample errors exceed completed work");
            }
        }
        Ok(())
    }

    /// Require every configured worker/round pair to be present exactly once.
    pub fn validate_complete(&self) -> Result<(), &'static str> {
        self.validate()?;
        let expected = self
            .spec
            .workers
            .len()
            .checked_mul(self.spec.rounds as usize)
            .ok_or("benchmark sample count overflows")?;
        if self.samples.len() != expected {
            return Err("benchmark report is missing worker/round samples");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{BENCHMARK_SCHEMA_VERSION, BenchmarkReport, BenchmarkSample, FixedWorkSpec};

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
        let metadata = super::BenchmarkMetadata::new("linux", "x86_64", "rustc", "rev", "test")
            .expect("valid metadata");
        let evidence = super::BenchmarkEvidence::new(metadata, report).expect("complete evidence");
        let encoded = evidence.to_json().expect("evidence serializes");
        assert_eq!(
            super::BenchmarkEvidence::from_json(&encoded).expect("evidence parses"),
            evidence
        );
        assert!(super::BenchmarkMetadata::new("", "x86_64", "rustc", "rev", "test").is_err());
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
}
