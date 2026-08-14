"""Decision-layer conversation-context JSON (3.3, P1-①).

Every L3A (decision-layer) session records its conversation context into a
compact JSON file, separate from the thought chain (P1-②) and the tool
results (P1-③). The JSON holds ONLY the user-input / model-answer pairs:

  - Upper layer: the user input — tagged with ``tag="user"``, the session
    id, and an input-sequence id (assigned the moment the input enters
    L3A), so it can be referenced into R4/R5 later.
  - Lower layer: the model answer — one entry per user input, tagged
    ``tag="assistant"``, paired 1:1 with the upper layer.

Storage: ``<data_dir>/l3a/sessions/<session_id>_conversation.json``
(compact JSON, no pretty-printing). The thought chain lives in a separate
file (P1-②) and the two are linked by the session id + sequence tags.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_500, SESSION_HISTORY_ENABLED_DEFAULT

logger = logging.getLogger(__name__)

_lock = threading.RLock()
# session_id -> next input sequence id (assigned at input entry)
_seq: dict[str, int] = {}
# History-module operator switch (API + L2), default ON.
_history_state: dict = {"enabled": SESSION_HISTORY_ENABLED_DEFAULT}
_history_lock = threading.Lock()


def history_status() -> dict:
    """Return the session-history switch state."""
    with _history_lock:
        return {"enabled": bool(_history_state["enabled"])}


def set_history(enabled: bool | None = None) -> dict:
    """Set the session-history operator switch.

    Args:
        enabled: master switch (None = keep current). Default ON.

    Returns:
        dict with success flag and the effective switch.
    """
    with _history_lock:
        if enabled is not None:
            _history_state["enabled"] = bool(enabled)
        return {"success": True, **history_status()}


def reset_history() -> None:
    """Reset the history switch (tests / lifecycle)."""
    with _history_lock:
        _history_state["enabled"] = SESSION_HISTORY_ENABLED_DEFAULT


def _session_dir() -> Path:
    try:
        from l1.kernel.paths import get_paths as _gp

        return Path(_gp().data_dir) / "l3a" / "sessions"
    except Exception:
        return Path(".praxis") / "l3a" / "sessions"


def _conversation_path(session_id: str) -> Path:
    return _session_dir() / f"{session_id}_conversation.json"


def next_input_seq(session_id: str) -> int:
    """Assign the next input-sequence id for a session (called at input
    entry, when the user input enters L3A)."""
    with _lock:
        _seq[session_id] = _seq.get(session_id, 0) + 1
        return _seq[session_id]


def append_turn(
    session_id: str,
    input_seq: int,
    user_text: str,
    assistant_text: str,
    user_tag: str = "user",
    assistant_tag: str = "assistant",
) -> dict:
    """Append one tagged user-input / model-answer pair to the conversation
    JSON (upper = tagged user input, lower = 1:1 model answer).

    Args:
        session_id: the L3A session id (file scope + reference key).
        input_seq: the input-sequence id assigned at input entry.
        user_text: the user input text.
        assistant_text: the model answer text.
        user_tag / assistant_tag: layer tags for R4/R5 referencing.

    Returns:
        dict with success flag and the entry count.
    """
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        path = _conversation_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"session_id": session_id, "entries": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {"session_id": session_id, "entries": []}
        entry = {
            "seq": input_seq,
            "user": {"tag": user_tag, "content": user_text},
            "assistant": {"tag": assistant_tag, "content": assistant_text},
        }
        # 1:1 pairing — replace any existing entry with the same seq.
        entries = [e for e in data.get("entries", []) if e.get("seq") != input_seq]
        entries.append(entry)
        entries.sort(key=lambda e: int(e.get("seq", 0)))
        data["entries"] = entries
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return {"success": True, "session_id": session_id, "entries": len(entries)}
    except Exception as e:
        logger.debug("session_json: append_turn failed: %s", e)
        return {"success": False, "error": str(e)}


def load_conversation(session_id: str) -> dict:
    """Load a session's conversation JSON ({} when absent)."""
    path = _conversation_path(session_id)
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("session_json: load failed: %s", e)
        return {}


# ── Thought-chain JSON (3.3, P1-②) ──
# The chain-of-thought lives in a SEPARATE file per session
# (``<session_id>_thoughts.json``), linked to the conversation JSON by the
# session id + input-sequence tags. R5 analyzes this file for knowledge-
# graph / skill distillation.

_THOUGHT_SUFFIX = "_thoughts.json"


def _thought_path(session_id: str) -> Path:
    return _session_dir() / f"{session_id}{_THOUGHT_SUFFIX}"


def append_thought(
    session_id: str,
    turn: int,
    input_seq: int,
    reasoning_text: str,
    tag: str = "thought",
) -> dict:
    """Append one tagged thought-chain entry to the session's thoughts JSON.

    The chain-of-thought is captured with an automatic tag (session id +
    turn + input seq) so the recorder classifies it into the correct JSON
    file (separate from the conversation context, linked by tags).

    Args:
        session_id: the L3A session id.
        turn: the turn number the reasoning belongs to.
        input_seq: the input-sequence id (links to the conversation entry).
        reasoning_text: the folded chain-of-thought text.
        tag: automatic classification tag.

    Returns:
        dict with success flag and the thought count.
    """
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        path = _thought_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"session_id": session_id, "thoughts": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {"session_id": session_id, "thoughts": []}
        thoughts = [t for t in data.get("thoughts", []) if not (t.get("turn") == turn and t.get("seq") == input_seq)]
        thoughts.append(
            {
                "turn": turn,
                "seq": input_seq,
                "tag": tag,
                "content": reasoning_text,
            }
        )
        thoughts.sort(key=lambda t: (int(t.get("turn", 0)), int(t.get("seq", 0))))
        data["thoughts"] = thoughts
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return {"success": True, "session_id": session_id, "thoughts": len(thoughts)}
    except Exception as e:
        logger.debug("session_json: append_thought failed: %s", e)
        return {"success": False, "error": str(e)}


def load_thoughts(session_id: str) -> dict:
    """Load a session's thought-chain JSON ({} when absent).

    Feed for R5 analysis: the chain-of-thought is distilled into the
    knowledge graph / skill system.
    """
    path = _thought_path(session_id)
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("session_json: load_thoughts failed: %s", e)
        return {}


# ── Tool-result JSON (3.3, P1-③) ──
# Successful tool calls are DROPPED (deleted — their effect is already
# applied; keeping them would bloat the record); FAILED calls are recorded
# to ``<session_id>_tools.json`` for R5 analysis and skill formation.
# The compression pipeline already folds/drops successful outputs; this
# file keeps only the failure signal.

_TOOLS_SUFFIX = "_tools.json"


def _tools_path(session_id: str) -> Path:
    return _session_dir() / f"{session_id}{_TOOLS_SUFFIX}"


def record_failed_tool(session_id: str, turn: int, tool_name: str, error: str) -> dict:
    """Record ONE failed tool call into the session's tool-result JSON.

    Successful calls are intentionally NOT recorded (dropped). Failures
    keep tool_name + turn + error so R5 can analyze failure patterns and
    form skills.

    Args:
        session_id: the L3A session id.
        turn: the turn number the tool ran in.
        tool_name: the failed tool's name.
        error: the failure error text.

    Returns:
        dict with success flag and the failure count.
    """
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        path = _tools_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"session_id": session_id, "failures": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {"session_id": session_id, "failures": []}
        data.setdefault("failures", []).append({"turn": turn, "tool": tool_name, "error": error[:LOG_TRUNC_500]})
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return {"success": True, "session_id": session_id, "failures": len(data["failures"])}
    except Exception as e:
        logger.debug("session_json: record_failed_tool failed: %s", e)
        return {"success": False, "error": str(e)}


def load_tool_failures(session_id: str) -> dict:
    """Load a session's failed-tool JSON ({} when absent)."""
    path = _tools_path(session_id)
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("session_json: load_tool_failures failed: %s", e)
        return {}


# ── Session history (3.3, P2-①) ──
# Per-session lifecycle record: start time, end time, duration, and a task
# summary — queryable/retrievable for front-end recall and reload. Stored
# in ``<data_dir>/l3a/sessions/history.json`` (compact JSON).

_HISTORY_FILE = "history.json"


def _history_path() -> Path:
    return _session_dir() / _HISTORY_FILE


def _load_history() -> dict:
    path = _history_path()
    try:
        if not path.exists():
            return {"sessions": []}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"sessions": []}


def _save_history(data: dict) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def record_session_open(session_id: str, title: str = "") -> dict:
    """Record a session's start (started_at) in the history module."""
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        data = _load_history()
        data.setdefault("sessions", [])
        entry = next((s for s in data["sessions"] if s.get("session_id") == session_id), None)
        if entry is None:
            entry = {
                "session_id": session_id,
                "title": title,
                "started_at": time.time(),
                "ended_at": 0.0,
                "duration": 0.0,
                "task_summary": "",
            }
            data["sessions"].append(entry)
        else:
            entry["started_at"] = time.time()
        _save_history(data)
        return {"success": True, "session_id": session_id, "started_at": entry["started_at"]}
    except Exception as e:
        logger.debug("session_json: record_session_open failed: %s", e)
        return {"success": False, "error": str(e)}


def record_session_close(session_id: str, task_summary: str = "") -> dict:
    """Record a session's end (ended_at + duration) in the history module."""
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        data = _load_history()
        entry = next((s for s in data.get("sessions", []) if s.get("session_id") == session_id), None)
        if entry is None:
            return {"success": False, "error": f"session {session_id} not in history"}
        entry["ended_at"] = time.time()
        entry["duration"] = round(max(0.0, entry["ended_at"] - float(entry.get("started_at") or entry["ended_at"])), 3)
        if task_summary:
            entry["task_summary"] = task_summary[:LOG_TRUNC_500]
        _save_history(data)
        return {"success": True, "session_id": session_id, "duration": entry["duration"]}
    except Exception as e:
        logger.debug("session_json: record_session_close failed: %s", e)
        return {"success": False, "error": str(e)}


def query_session_history(limit: int = 20, session_id: str = "") -> dict:
    """Query session history records (recent-first), optional session filter."""
    with _history_lock:
        enabled = bool(_history_state["enabled"])
    if not enabled:
        return {"success": True, "count": 0, "sessions": [], "disabled": True}
    try:
        data = _load_history()
        sessions = data.get("sessions", [])
        if session_id:
            sessions = [s for s in sessions if s.get("session_id") == session_id]
        sessions.sort(key=lambda s: float(s.get("started_at") or 0), reverse=True)
        return {"success": True, "count": len(sessions[:limit]), "sessions": sessions[:limit]}
    except Exception as e:
        logger.debug("session_json: query_session_history failed: %s", e)
        return {"success": False, "error": str(e)}


def reset_sequences() -> None:
    """Reset the in-memory sequence counters (tests / lifecycle)."""
    with _lock:
        _seq.clear()
