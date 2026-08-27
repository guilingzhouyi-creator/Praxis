"""Detect the agent framework / model driving the current commit session.

Co-Authored-By attribution must reflect who ACTUALLY executed the work, not
what the agent guesses from context — and NOT what a config file merely
declares (any process can read settings.yaml and claim that model). This
detector reads EXECUTION EVIDENCE first: the harness session log records
the real (provider, model) route of every LLM call, written by the harness,
never by the agent, so it cannot be forged from within the session.

Evidence tiers (strongest first):
  A. execution record — the live DSH session log ($DSH_SESSION_JSONL)
     records request/context + assistant/chunk.finish.replayState with the
     actual provider/model route + responseId (harness-written, unfakeable).
     Other frameworks: their own session stores (.opencode/ .atomcode/
     .claude/) when parseable.
  B. operator pin — explicit PRAXIS_AUTHOR / PRAXIS_MODEL (trusted only
     when the operator sets it deliberately; still NOT proof of execution).
  C. config declaration — ~/.dsh/settings.yaml agent-default-model (what
     the deployment CONFIGURES, not what this commit ran).
  D. weak signals — CLAUDE_CODE_* env, provider keys, parent-process chain,
     workspace agent dirs. These identify the FRAMEWORK only; the model is
     left unknown (never invented).

Output (--json): {"framework", "agent", "model", "provider",
"evidence" (A|B|C|D), "confidence" (high|medium|low|none),
"signals" (matched signal names), "note" (human caveat)}

Exit: 0 always (detection is informational; the gate decides policy).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

CACHE_TTL_S = 30.0
CACHE_PATH = Path(".praxis") / "detect_agent_cache.json"


def _dsh_home() -> Path:
    """Locate the DSH home directory."""
    env = os.environ.get("DSH_HOME", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".dsh"


def _read_session_log() -> tuple[str, str] | None:
    """Read the REAL (provider, model) route from the live DSH session log.

    $DSH_SESSION_JSONL is a zstd-compressed JSONL written by the harness:
    every LLM round-trip appends a `request/context` record (provider/model)
    and `assistant/chunk` finish records carry replayState with the same
    route + a responseId. This is EXECUTION evidence — the agent cannot
    alter the log it is running inside. Returns (provider, model) of the
    MOST RECENT request, or None when the log is unreadable.
    """
    path = os.environ.get("DSH_SESSION_JSONL", "").strip()
    if not path or not Path(path).is_file():
        return None
    try:
        import zstandard

        with open(path, "rb") as f:
            raw = zstandard.ZstdDecompressor().stream_reader(f).read()
        provider = model = ""
        for line in raw.decode("utf-8", errors="replace").splitlines()[-400:]:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            # request/context carries the authoritative route.
            if rec.get("type") == "request/context":
                data = rec.get("data") or {}
                provider = str(data.get("provider") or "").strip()
                model = str(data.get("model") or "").strip()
            elif rec.get("type") == "assistant/chunk":
                rs = ((rec.get("data") or {}).get("chunk") or {}).get("replayState") or {}
                if rs.get("model"):
                    provider = str(rs.get("provider") or provider or "").strip()
                    model = str(rs.get("model") or "").strip()
        if model:
            return provider, model
    except Exception:
        return None
    return None


def _dsh_default_model() -> str:
    """Config-declared default model (~/.dsh/settings.yaml) — fallback only.

    This is what the deployment CONFIGURES, not proof this commit ran it.
    Used only when execution evidence is unavailable, and the confidence is
    downgraded accordingly.
    """
    cfg = _dsh_home() / "settings.yaml"
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
                names.append(f.read().strip())
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
    return [n for n in (".opencode", ".atomcode", ".claude", ".dsh") if Path(n).is_dir()]


def detect() -> dict:  # noqa: PLR0911 — each evidence tier returns its own identity
    """Return the author identity from the strongest available evidence."""
    signals: list[str] = []

    # Tier A — EXECUTION EVIDENCE (unfakeable, strongest).
    if os.environ.get("DSH_SESSION_JSONL"):
        signals.append("session:DSH_SESSION_JSONL")
        route = _read_session_log()
        if route:
            provider, model = route
            signals.append("evidence:session-log")
            return {
                "framework": "dsh",
                "agent": "DeepSeek",
                "model": model,
                "provider": provider,
                "evidence": "A",
                "confidence": "high",
                "signals": signals,
                "note": "model read from the live harness session log (execution evidence)",
            }
        # DSH env present but log unreadable — downgrade to config.
        model = _dsh_default_model()
        signals.append("evidence:config")
        return {
            "framework": "dsh",
            "agent": "DeepSeek",
            "model": model,
            "provider": "",
            "evidence": "C",
            "confidence": "low" if model else "none",
            "signals": signals,
            "note": "session log unreadable; model from config declaration only (NOT execution proof)",
        }

    # Tier B — operator pin (deliberate override, still not execution proof).
    pin_agent = os.environ.get("PRAXIS_AUTHOR", "").strip()
    pin_model = os.environ.get("PRAXIS_MODEL", "").strip()
    if pin_agent:
        signals.append("env:PRAXIS_AUTHOR")
        return {
            "framework": "pinned",
            "agent": pin_agent,
            "model": pin_model or "",
            "provider": "",
            "evidence": "B",
            "confidence": "medium" if pin_model else "low",
            "signals": signals,
            "note": "operator-pinned identity (not execution evidence)",
        }

    env = os.environ
    # Tier D1 — Known AI Assistant envs (framework identity).
    if any(k.startswith("ANTIGRAVITY_") for k in env) or env.get("AI_AGENT") == "antigravity":
        signals.append("env:ANTIGRAVITY_*")
        model = env.get("ANTIGRAVITY_MODEL") or env.get("GEMINI_MODEL") or env.get("PRAXIS_MODEL") or ""
        return {
            "framework": "antigravity",
            "agent": "Antigravity",
            "model": model,
            "provider": "google",
            "evidence": "D",
            "confidence": "medium" if model else "low",
            "signals": signals,
            "note": "framework from Antigravity environment; model from env/pin"
            if model
            else "framework from Antigravity environment; model not execution-verified (use PRAXIS_MODEL to pin)",
        }
    if any(k.startswith("CLAUDE_CODE_") for k in env):
        signals.append("env:CLAUDE_CODE_*")
        model = env.get("CLAUDE_MODEL") or env.get("PRAXIS_MODEL") or ""
        return {
            "framework": "claude-code",
            "agent": "Claude",
            "model": model,
            "provider": "",
            "evidence": "D",
            "confidence": "medium" if model else "low",
            "signals": signals,
            "note": "framework from env; model from env/pin"
            if model
            else "framework from env; model unknown unless CLAUDE_MODEL/PRAXIS_MODEL set",
        }

    # Tier D2 — provider keys (framework identity only; model NEVER invented).
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
    elif env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY"):
        provider_agent = ("Gemini", "noreply@google.com")
        signals.append("env:GOOGLE_API_KEY")
    if provider_agent:
        agent, email = provider_agent
        return {
            "framework": "provider-key",
            "agent": agent,
            "model": "",
            "provider": "",
            "evidence": "D",
            "confidence": "low",
            "signals": signals,
            "note": "provider key present; specific model unknown — do not invent one",
        }

    # Tier D3 — parent-process chain (framework only).
    chain = [c.lower() for c in _parent_chain()]
    for marker, agent, _email in (
        ("dsh", "DeepSeek", "noreply@deepseek.com"),
        ("opencode", "OpenCode", "noreply@opencode.dev"),
        ("claude", "Claude", "noreply@anthropic.com"),
        ("atomcode", "AtomCode", "noreply@atomgit.com"),
        ("antigravity", "Antigravity", "noreply@google.com"),
        ("agy", "Antigravity", "noreply@google.com"),
    ):
        if any(marker in c for c in chain):
            signals.append(f"proc:{marker}")
            model = _dsh_default_model() if marker == "dsh" else ""
            return {
                "framework": marker,
                "agent": agent,
                "model": model,
                "provider": "",
                "evidence": "D",
                "confidence": "low" if not model else "medium",
                "signals": signals,
                "note": "framework from process chain; model not execution-verified"
                if marker != "dsh"
                else "model from config (not execution proof)",
            }

    # Tier D4 — workspace agent dirs (weakest).
    dirs = _workspace_dirs()
    for name in (".opencode", ".atomcode", ".claude", ".dsh"):
        if name in dirs:
            signals.append(f"dir:{name}")
    if signals:
        return {
            "framework": "workspace-dir",
            "agent": "",
            "model": "",
            "provider": "",
            "evidence": "D",
            "confidence": "none",
            "signals": signals,
            "note": "workspace dirs only — cannot identify agent or model; do not guess",
        }

    return {
        "framework": "unknown",
        "agent": "",
        "model": "",
        "provider": "",
        "evidence": "",
        "confidence": "none",
        "signals": [],
        "note": "no framework or model evidence found; do not guess",
    }


def _cache_path() -> Path:
    return CACHE_PATH


def _read_cache() -> dict | None:
    cp = _cache_path()
    if not cp.exists():
        return None
    try:
        data = json.loads(cp.read_text(encoding="utf-8"))
        if time.time() - data.get("_cached_at", 0) < CACHE_TTL_S:
            data.pop("_cached_at", None)
            return data
    except (ValueError, KeyError, OSError):
        pass
    return None


def _write_cache(result: dict) -> None:
    cp = _cache_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    data = {**result, "_cached_at": time.time()}
    cp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def cached_detect(use_cache: bool = True) -> dict:
    """Return the detected identity, optionally bypassing the disk cache.

    The cache file (.praxis/detect_agent_cache.json) is written inside the
    workspace and is therefore WRITABLE by the very process being detected —
    a forged cache entry could spoof high-confidence attribution for one
    TTL window. Gate-context callers (_lib/commit_policy.py) MUST pass
    use_cache=False so attribution is always computed from live evidence.
    """
    if not use_cache:
        return detect()
    cached = _read_cache()
    if cached is not None:
        return cached
    result = detect()
    _write_cache(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect the agent framework/model from execution evidence")
    parser.add_argument("--json", action="store_true", help="emit JSON (default behavior; kept for CLI compatibility)")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="bypass the writable disk cache — REQUIRED for gate/attribution contexts",
    )
    args = parser.parse_args()
    print(json.dumps(cached_detect(use_cache=not args.no_cache), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
