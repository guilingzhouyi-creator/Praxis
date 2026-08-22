//! Typed fixed-work benchmark schema for the Rust-first rewrite.

use std::collections::HashSet;

use serde::{Deserialize, Serialize};

/// Version of the benchmark report consumed by the R2 evidence gate.
pub const BENCHMARK_SCHEMA_VERSION: u32 = 3;
const NANOSECONDS_PER_SECOND: u128 = 1_000_000_000;

/// CPU time unit used by the cross-language R2 contract.
pub const CPU_TIME_UNIT: &str = "ns";
/// Memory unit used by the cross-language R2 contract.
pub const MEMORY_UNIT: &str = "bytes";
/// Scope used to derive per-round resource values.
pub const RESOURCE_SCOPE: &str = "process_round_delta";

/// Resource measurements attached to one fixed-work sample.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BenchmarkResources {
    /// Process CPU time consumed during this sample, in nanoseconds.
    pub cpu_time_ns: Option<u64>,
    /// Increase in process high-water RSS during this sample, in bytes.
    pub memory_bytes: Option<u64>,
    /// Source used for the CPU measurement, or `unavailable`.
    pub cpu_source: String,
    /// Source used for the memory measurement, or `unavailable`.
    pub memory_source: String,
}

impl BenchmarkResources {
    /// Return an explicitly unavailable resource sample.
    pub fn unavailable() -> Self {
        Self {
            cpu_time_ns: None,
            memory_bytes: None,
            cpu_source: "unavailable".to_owned(),
            memory_source: "unavailable".to_owned(),
        }
    }

    /// Validate source attribution and optional-value semantics.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cpu_source.is_empty() || self.memory_source.is_empty() {
            return Err("resource sample sources must not be empty");
        }
        if self.cpu_time_ns.is_none() != (self.cpu_source == "unavailable") {
            return Err("CPU resource value and source disagree");
        }
        if self.memory_bytes.is_none() != (self.memory_source == "unavailable") {
            return Err("memory resource value and source disagree");
        }
        Ok(())
    }
}

/// Unit and scope metadata for all resource samples in one evidence report.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BenchmarkResourceMetadata {
    /// CPU time unit; fixed to nanoseconds for cross-language comparison.
    pub cpu_unit: String,
    /// Memory unit; fixed to bytes for cross-language comparison.
    pub memory_unit: String,
    /// Scope used to derive sample values.
    pub scope: String,
}

impl BenchmarkResourceMetadata {
    /// Return the standard process-round resource contract.
    pub fn standard() -> Self {
        Self {
            cpu_unit: CPU_TIME_UNIT.to_owned(),
            memory_unit: MEMORY_UNIT.to_owned(),
            scope: RESOURCE_SCOPE.to_owned(),
        }
    }

    /// Validate units and scope against the unified contract.
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cpu_unit != CPU_TIME_UNIT {
            return Err("unsupported CPU resource unit");
        }
        if self.memory_unit != MEMORY_UNIT {
            return Err("unsupported memory resource unit");
        }
        if self.scope != RESOURCE_SCOPE {
            return Err("unsupported resource sampling scope");
        }
        Ok(())
    }
}

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
    /// CPU and memory measurements for this fixed-work round.
    pub resources: BenchmarkResources,
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
    /// Units and scope for resource measurements.
    pub resource_sampling: BenchmarkResourceMetadata,
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
            resource_sampling: BenchmarkResourceMetadata::standard(),
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
        self.resource_sampling.validate()?;
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
        sample.resources.validate()?;
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
            sample.resources.validate()?;
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
