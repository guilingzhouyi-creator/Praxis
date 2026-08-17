"""Reusable performance sampling harness with platform-aware summaries."""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from l1.kernel.params.system import (  # noqa: E402
    PERF_HARNESS_MAD_WARN_PCT,
    PERF_HARNESS_SAMPLE_ROUNDS,
    PERF_HARNESS_WARMUP_ROUNDS,
)

SCHEMA_VERSION = 1


def _quantile(values: list[float], probability: float) -> float:
    """Return a linearly interpolated quantile for a non-empty value list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _rss_bytes() -> int | None:
    """Return the process high-water RSS in bytes when the platform exposes it."""
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return int(value)
        return int(value * 1024)
    except (ImportError, OSError, AttributeError):
        return None


def platform_fingerprint() -> dict[str, Any]:
    """Return stable host metadata for comparing benchmark runs."""
    fingerprint: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
    }
    if platform.system() == "Linux":
        try:
            with open("/proc/version", encoding="utf-8", errors="replace") as stream:
                fingerprint["wsl"] = "microsoft" in stream.read().lower()
        except OSError:
            fingerprint["wsl"] = False
    return fingerprint


@dataclass(frozen=True)
class Sample:
    """One timed batch of benchmark operations."""

    elapsed_s: float
    operations: int
    rss_bytes: int | None = None

    @property
    def ops_per_sec(self) -> float:
        """Return batch throughput in operations per second."""
        return self.operations / self.elapsed_s if self.elapsed_s > 0 else 0.0

    @property
    def latency_ms(self) -> float:
        """Return average operation latency for this batch in milliseconds."""
        return self.elapsed_s * 1000 / self.operations if self.operations else 0.0

    def as_dict(self) -> dict[str, Any]:
        """Serialize the sample using the shared performance contract."""
        data: dict[str, Any] = {
            "elapsed_s": self.elapsed_s,
            "operations": self.operations,
            "ops_per_sec": self.ops_per_sec,
            "latency_ms": self.latency_ms,
        }
        if self.rss_bytes is not None:
            data["rss_bytes"] = self.rss_bytes
        return data


@dataclass(frozen=True)
class BenchmarkResult:
    """Robust summary for one benchmark case."""

    name: str
    iterations: int
    warmups: int
    samples: tuple[Sample, ...]
    platform: dict[str, Any]
    metadata: dict[str, Any]
    started_at: str

    @property
    def rates(self) -> list[float]:
        """Return recorded throughput values."""
        return [sample.ops_per_sec for sample in self.samples]

    @property
    def median_ops_per_sec(self) -> float:
        """Return median throughput across recorded samples."""
        return statistics.median(self.rates) if self.rates else 0.0

    @property
    def median_latency_ms(self) -> float:
        """Return median average-operation latency in milliseconds."""
        latencies = [sample.latency_ms for sample in self.samples]
        return statistics.median(latencies) if latencies else 0.0

    @property
    def mad_ops_per_sec(self) -> float:
        """Return the median absolute deviation of throughput."""
        if not self.rates:
            return 0.0
        median = self.median_ops_per_sec
        return statistics.median([abs(rate - median) for rate in self.rates])

    @property
    def coefficient_of_variation(self) -> float:
        """Return throughput standard deviation divided by median."""
        if len(self.rates) < 2 or self.median_ops_per_sec <= 0:
            return 0.0
        return statistics.pstdev(self.rates) / self.median_ops_per_sec

    @property
    def p95_latency_ms(self) -> float:
        """Return p95 of per-batch average operation latency."""
        return _quantile([sample.latency_ms for sample in self.samples], 0.95)

    @property
    def variance_warning(self) -> bool:
        """Return whether MAD indicates an unstable benchmark run."""
        return self.mad_ops_per_sec > self.median_ops_per_sec * (PERF_HARNESS_MAD_WARN_PCT / 100)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the result with summary, samples, and run metadata."""
        return {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "unit": "ops_per_sec",
            "iterations": self.iterations,
            "warmups": self.warmups,
            "started_at": self.started_at,
            "platform": self.platform,
            "metadata": self.metadata,
            "samples": [sample.as_dict() for sample in self.samples],
            "summary": {
                "ops_per_sec": self.median_ops_per_sec,
                "latency_ms": self.median_latency_ms,
                "latency_p95_ms": self.p95_latency_ms,
                "mad_ops_per_sec": self.mad_ops_per_sec,
                "coefficient_of_variation": self.coefficient_of_variation,
                "variance_warning": self.variance_warning,
            },
        }


def run_benchmark(
    name: str,
    operation: Callable[[int], Any],
    iterations: int,
    *,
    warmups: int = PERF_HARNESS_WARMUP_ROUNDS,
    samples: int = PERF_HARNESS_SAMPLE_ROUNDS,
    metadata: dict[str, Any] | None = None,
) -> BenchmarkResult:
    """Run a callable repeatedly and return a robust performance summary."""
    if not name:
        raise ValueError("benchmark name must not be empty")
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if warmups < 0:
        raise ValueError("warmups must not be negative")
    if samples < 1:
        raise ValueError("samples must be positive")

    for _ in range(warmups):
        operation(iterations)

    started_at = datetime.now(UTC).isoformat()
    measured: list[Sample] = []
    for _ in range(samples):
        rss_before = _rss_bytes()
        started = time.perf_counter()
        operation(iterations)
        elapsed = time.perf_counter() - started
        rss_after = _rss_bytes()
        rss_delta = None
        if rss_before is not None and rss_after is not None:
            rss_delta = max(0, rss_after - rss_before)
        measured.append(Sample(elapsed_s=elapsed, operations=iterations, rss_bytes=rss_delta))

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        warmups=warmups,
        samples=tuple(measured),
        platform=platform_fingerprint(),
        metadata=dict(metadata or {}),
        started_at=started_at,
    )


def run_suite(
    cases: Iterable[tuple[str, Callable[[int], Any], int]],
    *,
    warmups: int = PERF_HARNESS_WARMUP_ROUNDS,
    samples: int = PERF_HARNESS_SAMPLE_ROUNDS,
) -> dict[str, Any]:
    """Run named cases and return one schema-versioned suite document."""
    results = [
        run_benchmark(name, operation, iterations, warmups=warmups, samples=samples)
        for name, operation, iterations in cases
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": platform_fingerprint(),
        "benchmarks": [result.as_dict() for result in results],
    }


def write_json(path: str | Path, document: dict[str, Any]) -> None:
    """Write a benchmark document as stable, human-readable JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
