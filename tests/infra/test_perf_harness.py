"""Contract tests for the repeatable performance sampling harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "py" / "_lib"))

from perf_sampling import (  # noqa: E402
    PERF_HARNESS_MAD_WARN_PCT,
    PERF_HARNESS_SAMPLE_ROUNDS,
    PERF_HARNESS_WARMUP_ROUNDS,
    SCHEMA_VERSION,
    PerfHarnessConfigError,
    load_config,
    run_benchmark,
    run_suite,
    write_json,
)


def test_shipped_config_drives_compatibility_defaults() -> None:
    """The checked-in quality config supplies the legacy harness aliases."""
    config = load_config()

    assert config.warmup_rounds == PERF_HARNESS_WARMUP_ROUNDS == 1
    assert config.sample_rounds == PERF_HARNESS_SAMPLE_ROUNDS == 7
    assert config.mad_warn_pct == PERF_HARNESS_MAD_WARN_PCT == 3.0


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "section"),
        ({"perf_harness": {"schema_version": 2}}, "schema_version"),
        (
            {"perf_harness": {"schema_version": 1, "warmup_rounds": -1, "sample_rounds": 7, "mad_warn_pct": 3}},
            "warmup_rounds",
        ),
        (
            {"perf_harness": {"schema_version": 1, "warmup_rounds": 1, "sample_rounds": 0, "mad_warn_pct": 3}},
            "sample_rounds",
        ),
        (
            {"perf_harness": {"schema_version": 1, "warmup_rounds": 1, "sample_rounds": 7, "mad_warn_pct": 0}},
            "mad_warn_pct",
        ),
        (
            {
                "perf_harness": {
                    "schema_version": 1,
                    "warmup_rounds": 1,
                    "sample_rounds": 7,
                    "mad_warn_pct": 3,
                    "extra": True,
                }
            },
            "unknown",
        ),
    ],
)
def test_config_validation_rejects_invalid_payloads(tmp_path: Path, payload: dict, message: str) -> None:
    """Missing, malformed, and unknown settings fail closed with context."""
    path = tmp_path / "perf-harness.yaml"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PerfHarnessConfigError, match=message):
        load_config(path)


def test_config_validation_reports_missing_file(tmp_path: Path) -> None:
    """A missing quality config cannot silently restore runtime defaults."""
    with pytest.raises(PerfHarnessConfigError, match="cannot read"):
        load_config(tmp_path / "missing.yaml")


def test_run_benchmark_records_warmups_and_samples() -> None:
    """Warmups are discarded and every measured round is represented."""
    calls: list[int] = []
    result = run_benchmark("test.case", lambda count: calls.append(count), 4, warmups=2, samples=5)

    assert calls == [4] * 7
    assert len(result.samples) == 5
    document = result.as_dict()
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["summary"]["ops_per_sec"] > 0
    assert document["summary"]["latency_p95_ms"] >= document["summary"]["latency_ms"]
    assert document["platform"]["python"]


def test_run_suite_emits_versioned_document() -> None:
    """A suite document contains platform metadata and named benchmark cases."""
    document = run_suite([("test.one", lambda count: None, 2)], warmups=0, samples=2)

    assert document["schema_version"] == SCHEMA_VERSION
    assert document["generated_at"]
    assert [item["name"] for item in document["benchmarks"]] == ["test.one"]
    assert document["platform"]["system"]


def test_schema_declares_every_harness_field() -> None:
    """The JSON schema covers the complete generated benchmark contract."""
    schema_path = Path(__file__).resolve().parents[2] / "config" / "quality" / "perf-schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    document = run_suite([("test.schema", lambda count: None, 2)], warmups=0, samples=2)
    benchmark = document["benchmarks"][0]
    platform_required = schema["$defs"]["platform"]["required"]
    benchmark_required = schema["$defs"]["benchmark"]["required"]
    summary_required = schema["$defs"]["benchmark"]["properties"]["summary"]["required"]
    sample_required = schema["$defs"]["sample"]["required"]

    assert set(document).issubset(schema["properties"])
    assert all(field in document["platform"] for field in platform_required)
    assert all(field in benchmark for field in benchmark_required)
    assert all(field in benchmark["summary"] for field in summary_required)
    assert all(all(field in sample for field in sample_required) for sample in benchmark["samples"])


def test_schema_covers_perf_quality_diagnostics() -> None:
    """The schema accepts the variance diagnostics emitted by perf_quality."""
    schema_path = Path(__file__).resolve().parents[2] / "config" / "quality" / "perf-schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    diagnostics = schema["properties"]["diagnostics"]
    warning = schema["$defs"]["variance_warning"]

    assert "diagnostics" in schema["properties"]
    assert diagnostics["properties"]["variance_warnings"]["items"]["$ref"] == "#/$defs/variance_warning"
    assert set(warning["required"]) == set(warning["properties"])


def test_write_json_round_trips(tmp_path: Path) -> None:
    """Structured reports can be persisted and loaded without mutation."""
    path = tmp_path / "nested" / "result.json"
    document = {"schema_version": SCHEMA_VERSION, "benchmarks": []}

    write_json(path, document)

    assert json.loads(path.read_text(encoding="utf-8")) == document


@pytest.mark.parametrize(
    ("iterations", "warmups", "samples"),
    [(0, 0, 1), (1, -1, 1), (1, 0, 0)],
)
def test_run_benchmark_rejects_invalid_sizes(iterations: int, warmups: int, samples: int) -> None:
    """Invalid sampling sizes fail before invoking benchmark work."""
    with pytest.raises(ValueError):
        run_benchmark("test.invalid", lambda count: None, iterations, warmups=warmups, samples=samples)
