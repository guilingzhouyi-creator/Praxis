"""Cross-language conformance vectors for protocol v1 (legacy Python runner).

Consumes tests/fixtures/protocol_v1_conformance.json, frozen from the
normative TS engine (see docs/architecture/l2-shell-engine.md rulings).
The legacy Python implementation must satisfy the same canonical bytes,
rejection behavior, and R1 outbox semantics. R6 route classification is a
documented legacy exception (frozen historical order until G6).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from l2.protocol import KIND_INTENT, Outbox, decode_message, encode_message, make_message

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "protocol_v1_conformance.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case", _fixture()["canonical_envelopes"], ids=[c["name"] for c in _fixture()["canonical_envelopes"]]
)
def test_canonical_encoding_matches_frozen_bytes(case: dict) -> None:
    """Canonical JSON is byte-identical across the three implementations."""
    fields = case["fields"]
    msg = make_message(
        fields["session_id"],
        fields["seq"],
        fields["kind"],
        fields["payload"],
        trace_id=fields["trace_id"],
        ts=fields["ts"],
    )
    assert encode_message(msg) == case["expected_line"]
    decoded, err = decode_message(case["expected_line"])
    assert err is None and decoded == json.loads(case["expected_line"])


@pytest.mark.parametrize("case", _fixture()["invalid_frames"], ids=[c["name"] for c in _fixture()["invalid_frames"]])
def test_invalid_frames_fail_closed(case: dict) -> None:
    """Every implementation rejects the frame; error text may vary."""
    _, err = decode_message(case["line"])
    assert err is not None
    assert any(fragment in err for fragment in case["error_contains_any"]), err


@pytest.mark.parametrize(
    "case",
    _fixture()["outbox_recovery"],
    ids=[c["name"] for c in _fixture()["outbox_recovery"]],
)
def test_outbox_recovery_semantics_r1(case: dict) -> None:
    """R1: ack advances the cursor only; recovery replays the retained window."""
    box = Outbox(maxlen=case["maxlen"])
    for seq in case["append_seqs"]:
        box.append(make_message("s", seq, KIND_INTENT, {"text": "x"}))
    if case["ack"] is not None:
        box.ack(case["ack"])
    assert [m["seq"] for m in box.unacked()] == case["expect_default_unacked"]
    assert [m["seq"] for m in box.unacked(-1)] == case["expect_recovery_from_minus_one"]
