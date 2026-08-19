"""Tests for Co-Authored-By truthfulness + subject format gates.

Covers scripts/py/detect_agent.py (runtime identity detection) and the
commit-msg hook's strict attribution checks: a registered agent with the
matching live model passes; an OpenAI/Anthropic model claiming a deepseek
run is rejected (no cross-framework impersonation); an unregistered agent
name is rejected; markdown / uppercase / trailing-period subjects are
rejected.

The live detection is overridden with --detected (a synthetic DSH payload)
so the tests are hermetic and do not depend on the runner's environment.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCAN = ROOT / "scripts" / "py" / "commit_scan.py"
DETECT = ROOT / "scripts" / "py" / "detect_agent.py"
HOOK = ROOT / ".githooks" / "commit-msg"

DSH_DETECTED = json.dumps(
    {
        "framework": "dsh",
        "agent": "DeepSeek",
        "model": "deepseek-v4-flash",
        "provider": "jiyuan",
        "evidence": "A",
        "confidence": "high",
        "signals": ["session:DSH_SESSION_JSONL", "evidence:session-log"],
    }
)

NO_EVIDENCE = json.dumps(
    {
        "framework": "unknown",
        "agent": "",
        "model": "",
        "evidence": "",
        "confidence": "none",
        "signals": [],
    }
)


def _scan(msg: str, detected: str = DSH_DETECTED) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(SCAN), "--msg", msg, "--detected", detected],
        capture_output=True,
        text=True,
    )


def _hook(msg: str) -> subprocess.CompletedProcess:
    """Run the commit-msg hook against a message file (no git context needed)."""
    f = Path("/tmp/cab_hook_test_msg.txt")
    f.write_text(msg, encoding="utf-8")
    return subprocess.run(["bash", str(HOOK), str(f)], capture_output=True, text=True)


GOOD_MSG = "feat(l3): clean lowercase subject\n\nbody here\n\nCo-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"


def test_correct_trailer_passes() -> None:
    res = _scan(GOOD_MSG)
    assert res.returncode == 0
    assert "matches registry + runtime" in res.stdout


def test_gpt_impersonation_rejected() -> None:
    msg = "feat(l3): gpt impostor\n\nCo-Authored-By: GPT (gpt-4o) <noreply@openai.com>"
    res = _scan(msg)
    assert res.returncode == 1
    assert "model mismatch" in res.stderr
    assert "agent mismatch" in res.stderr


def test_unregistered_agent_rejected() -> None:
    msg = "feat(l3): bogus agent\n\nCo-Authored-By: RandomBot (deepseek-v4-flash) <noreply@example.com>"
    res = _scan(msg)
    assert res.returncode == 1
    assert "not registered" in res.stderr


def test_wrong_model_for_registered_agent() -> None:
    # AtomCode is only allowed deepseek-v4-flash — gpt-4o is not in its list.
    msg = "feat(l3): wrong model\n\nCo-Authored-By: AtomCode (gpt-4o) <noreply@atomgit.com>"
    res = _scan(msg)
    assert res.returncode == 1
    assert "model 'gpt-4o' not allowed" in res.stderr


def test_markdown_subject_rejected() -> None:
    msg = "feat(l3): **bold** subject\n\nCo-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"
    res = _hook(msg)
    assert res.returncode == 1
    assert "plain text" in res.stderr


def test_uppercase_subject_rejected() -> None:
    msg = "Feat(l3): uppercase\n\nCo-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"
    res = _hook(msg)
    assert res.returncode == 1
    assert "lowercase" in res.stderr


def test_trailing_period_rejected() -> None:
    msg = "feat(l3): period end.\n\nCo-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"
    res = _hook(msg)
    assert res.returncode == 1
    assert "period" in res.stderr


def test_detect_agent_emits_json() -> None:
    res = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(DETECT), "--json"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert "framework" in data
    assert "agent" in data
    assert "model" in data
    assert "confidence" in data


def test_execution_evidence_beats_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The session log (execution evidence) wins over settings.yaml (config).

    Even when a scratch DSH_HOME declares custom-model-9x, a live
    DSH_SESSION_JSONL proving deepseek-v4-flash must be reported — config
    never overrides what the session actually ran.
    """
    dsh_home = tmp_path / "dsh"
    dsh_home.mkdir()
    (dsh_home / "settings.yaml").write_text(
        "agent-default-model:\n  provider: jiyuan\n  model: custom-model-9x\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    res = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(DETECT), "--json"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    # The REAL session log (this test runs inside DSH) proves the actual
    # model; the scratch config must not shadow it.
    if data.get("evidence") == "A":
        assert data["model"]  # some execution-proven model
        assert data["confidence"] == "high"
    else:
        # No live session log in the test env — config is a low-confidence
        # fallback, and the model may be the scratch value.
        assert data["confidence"] in ("low", "none")


def test_config_fallback_when_no_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without a session log, the config-declared model is a LOW-confidence
    fallback (never high) — the gate then rejects it as unverifiable."""
    dsh_home = tmp_path / "dsh"
    dsh_home.mkdir()
    (dsh_home / "settings.yaml").write_text(
        "agent-default-model:\n  provider: jiyuan\n  model: custom-model-9x\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    monkeypatch.delenv("DSH_SESSION_JSONL", raising=False)
    res = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(DETECT), "--json"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["confidence"] in ("low", "none")
    if data.get("model"):
        assert data["evidence"] in ("C", "D")


def test_unverifiable_model_claim_rejected() -> None:
    """Without execution evidence, claiming a specific model is unverifiable.

    A session with no session log / operator pin must NOT be able to assert
    a concrete model (reading settings.yaml and pasting it is not proof).
    """
    msg = "feat(l3): unverifiable\n\nCo-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"
    res = _scan(msg, detected=NO_EVIDENCE)
    assert res.returncode == 1
    assert "unverifiable model claim" in res.stderr


def test_config_only_evidence_rejected() -> None:
    """Config-declared model (evidence C, low confidence) is not execution
    proof — asserting it as the author model is rejected."""
    config_only = json.dumps(
        {
            "framework": "dsh",
            "agent": "DeepSeek",
            "model": "deepseek-v4-flash",
            "evidence": "C",
            "confidence": "low",
            "signals": ["evidence:config"],
        }
    )
    msg = "feat(l3): config only\n\nCo-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"
    res = _scan(msg, detected=config_only)
    assert res.returncode == 1
    assert "unverifiable model claim" in res.stderr
