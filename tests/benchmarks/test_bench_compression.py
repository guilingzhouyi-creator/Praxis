"""Unit coverage for the L3A compression benchmark (3.1, G7)."""

from __future__ import annotations

from tests.benchmarks import bench_compression


def test_run_reports_compression_ratio_greater_than_one():
    """A synthetic session folds to a summary, so the ratio exceeds 1.0."""
    result = bench_compression.run(n_messages=12, keep_last=4, rounds=2)

    assert result["compression_ratio"] > 1.0
    assert result["compressed_msgs"] > 0
    assert result["before_tokens"] > result["after_tokens"]
    assert result["compress_ops_per_sec"] > 0


def test_run_keeps_last_messages_out_of_the_fold():
    """keep_last messages are retained, so compressed = total - keep_last."""
    result = bench_compression.run(n_messages=10, keep_last=4, rounds=1)

    # 10 user + 10 assistant = 20 messages; 4 kept -> 16 folded.
    assert result["compressed_msgs"] == 16
