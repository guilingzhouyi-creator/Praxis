"""Detect the agent framework / model driving the current commit session.

Co-Authored-By attribution must reflect who ACTUALLY did the work, not what
the agent guesses from context. This detector reads authoritative runtime
signals (environment, parent process chain, DSH session) and reports the
most likely author identity as JSON, so the commit-msg gate can compare it
against the trailer the agent wrote.

Signals, strongest first:
  1. explicit PRAXIS_AUTHOR / PRAXIS_MODEL overrides (operator-pinned)
  2. DSH harness env (DSH_* set) — the DeepSeek Harness is the current host
  3. CLAUDE_CODE_* env — Claude Code / claude agent
  4. OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY — provider key
  5. parent-process chain — a live opencode/claude/atomcode/dsh process
  6. workspace agent dirs (.opencode/ .atomcode/ .claude/ .dsh/)

Output (--json): {"framework", "agent", "model", "email",
"confidence" (high|medium|low), "signals" (list of matched signal names)}

Exit: 0 always (detection is informational; the gate decides policy).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _dsh_default_model() -> str:
    """Read the harness default model from ~/.dsh/settings.yaml (dynamic).

    The model name is NOT hardcoded here — it changes with the deployment.
    The DSH harness persists its agent-default-model (provider/model) in
    settings.yaml; read it live so attribution always names the CURRENT
    model, not a stale constant.
    """
    dsh_home = Path(os.environ.get("DSH_HOME", "")).expanduser() or Path.home() / ".dsh"
    cfg = dsh_home / "settings.yaml"
    if not cfg.is_file():
        return ""
    try:
        import yaml

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        return ((data.get("agent-default-model") or {}).get("model") or "").strip()
    except Exception:
        return ""


def _parent_chain(max_depth: int = 6) -> list[str]:
    """Walk the parent-process chain, returning process command names."""
    names: list[str] = []
    pid = os.getppid()
    for _ in range(max_depth):
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                comm = f.read().strip()
            names.append(comm)
        except OSError:
            break
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
                parts = f.read().rsplit(")", 1)[-1].split()
            ppid = int(parts[1]) if len(parts) > 1 else 0
        except (OSError, ValueError, IndexError):
            break
        if ppid <= 1 or ppid == pid:
            break
        pid = ppid
    return names


def _workspace_dirs() -> list[str]:
    """Detect per-agent workspace directories (cheap existence probes)."""
    found: list[str] = []
    for name in (".opencode", ".atomcode", ".claude", ".dsh"):
        if Path(name).is_dir():
            found.append(name)
    return found


def detect() -> dict:  # noqa: PLR0911 — each signal tier returns its own identity
    """Return the best-effort author identity from runtime signals."""
    signals: list[str] = []

    # 1. Explicit operator pin — highest authority, no guessing.
    pin_agent = os.environ.get("PRAXIS_AUTHOR", "").strip()
    pin_model = os.environ.get("PRAXIS_MODEL", "").strip()
    if pin_agent:
        signals.append("env:PRAXIS_AUTHOR")
        return {
            "framework": "pinned",
            "agent": pin_agent,
            "model": pin_model or "",
            "email": f"noreply@{pin_agent.lower()}." if not pin_model else f"noreply@{pin_agent.lower()}.com",
            "confidence": "high",
            "signals": signals,
        }

    env = os.environ
    # 2. DSH harness — the DeepSeek Harness injects DSH_* on every session.
    if any(k.startswith("DSH_") for k in env):
        signals.append("env:DSH_*")
        # Model is read LIVE from ~/.dsh/settings.yaml (agent-default-model)
        # — never hardcoded, so a deployment model bump propagates.
        model = _dsh_default_model()
        if not model:
            # Fall back to the provider key / parent chain below rather than
            # guessing a stale name.
            signals.append("env:DSH_*:no-model")
        return {
            "framework": "dsh",
            "agent": "DeepSeek",
            "model": model,
            "email": "noreply@deepseek.com",
            "confidence": "high" if model else "medium",
            "signals": signals,
        }

    # 3. Claude Code — CLAUDE_CODE_SSE_PORT etc. mark a claude session.
    if any(k.startswith("CLAUDE_CODE_") for k in env):
        signals.append("env:CLAUDE_CODE_*")
        return {
            "framework": "claude-code",
            "agent": "Claude",
            "model": env.get("CLAUDE_MODEL", "claude"),
            "email": "noreply@anthropic.com",
            "confidence": "high",
            "signals": signals,
        }

    # 4. Provider keys — last-resort provider-level attribution. The provider
    #    fixes the AGENT identity; the specific model is unknown from a bare
    #    key (the session may use any model the provider offers), so model is
    #    left empty and the agent must not invent one.
    provider_agent = None
    if env.get("DEEPSEEK_API_KEY"):
        provider_agent = ("DeepSeek", "noreply@deepseek.com")
        signals.append("env:DEEPSEEK_API_KEY")
    elif env.get("ANTHROPIC_API_KEY"):
        provider_agent = ("Claude", "noreply@anthropic.com")
        signals.append("env:ANTHROPIC_API_KEY")
    elif env.get("OPENAI_API_KEY"):
        provider_agent = ("OpenAI", "noreply@openai.com")
        signals.append("env:OPENAI_API_KEY")
    if provider_agent:
        agent, email = provider_agent
        return {
            "framework": "provider-key",
            "agent": agent,
            "model": "",
            "email": email,
            "confidence": "medium",
            "signals": signals,
        }

    # 5. Parent-process chain — a live agent runner is authoritative.
    chain = _parent_chain()
    chain_lower = [c.lower() for c in chain]
    for marker, agent, email in (
        ("dsh", "DeepSeek", "noreply@deepseek.com"),
        ("opencode", "OpenCode", "noreply@opencode.dev"),
        ("claude", "Claude", "noreply@anthropic.com"),
        ("atomcode", "AtomCode", "noreply@atomgit.com"),
    ):
        if any(marker in c for c in chain_lower):
            signals.append(f"proc:{marker}")
            model = _dsh_default_model() if marker == "dsh" else ""
            return {
                "framework": marker,
                "agent": agent,
                "model": model,
                "email": email,
                "confidence": "medium",
                "signals": signals,
            }

    # 6. Workspace agent dirs — weak signal, low confidence.
    dirs = _workspace_dirs()
    for name in (".opencode", ".atomcode", ".claude", ".dsh"):
        if name in dirs:
            signals.append(f"dir:{name}")
    if signals:
        return {
            "framework": "workspace-dir",
            "agent": "",
            "model": "",
            "email": "",
            "confidence": "low",
            "signals": signals,
        }

    return {"framework": "unknown", "agent": "", "model": "", "email": "", "confidence": "none", "signals": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect the agent framework driving this session")
    parser.add_argument("--json", action="store_true", help="emit JSON (default)")
    parser.parse_args()
    print(json.dumps(detect(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
