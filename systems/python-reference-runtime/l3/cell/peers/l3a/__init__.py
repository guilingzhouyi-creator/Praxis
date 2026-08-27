"""L3A — session management system.

Package structure:
  params.py     — constants
  model.py      — L3AModelConfig (model provider config, inheritance chain)
  types.py      — shared enums and dataclasses
  context.py    — ContextSource, ContextEpoch, ContextRegistry
  inbox.py      — PromptInbox (durable admission/promotion)
  pipeline.py   — ManagedToolOutput (oversized tool result spill)
  archive.py    — R4 archive store/restore
  session.py    — Session, SessionHistory, SessionManager
  daemon.py     — L3ADaemon lifecycle + registry builders + singleton
  helpers.py    — cardwrite handler, prompt builder, convergence
  api.py        — L2 Shell command routing
  __init__.py   — re-exports only (facade)

Architecture (above Cell, below L5 CLI):
  L3ADaemon (persistent process)
    ├── SessionManager (active session registry)
    ├── ContextRegistry (all context sources)
    └── L3AModelConfig (model config with inheritance)
"""

from __future__ import annotations

# ── Re-exports: models / registries (public package surface) ──
from .context import ContextEpoch, ContextRegistry, ContextSource
from .daemon import L3ADaemon, dispatch, get_daemon, reset_daemon, start, stop

# ── Re-exports: helpers / subagents / summaries / task tables ──
from .helpers import build_l3a_prompt, cardwrite_handler, get_convergence_queue  # noqa: E402
from .model import L3AModelConfig
from .session import Session, SessionHistory, SessionManager
from .subagent import L3ASubAgentPool  # noqa: E402
from .subagent import get_pool as get_l3a_pool  # noqa: E402
from .summaries import L3ASummary, L3ASummaryStore  # noqa: E402
from .summaries import get_store as get_summary_store  # noqa: E402
from .task_table import SessionTask, SessionTaskTable  # noqa: E402
from .types import AssemblyMode, CardType, L3ATask, L3ATaskGroup, SessionRecord, TaskCard  # noqa: E402

start_l3a_daemon = start
stop_l3a_daemon = stop

__all__ = [
    "L3ADaemon",
    "Session",
    "SessionHistory",
    "SessionManager",
    "ContextEpoch",
    "ContextRegistry",
    "ContextSource",
    "L3AModelConfig",
    "AssemblyMode",
    "CardType",
    "SessionRecord",
    "TaskCard",
    "L3ATask",
    "L3ATaskGroup",
    "SessionTask",
    "SessionTaskTable",
    "L3ASummary",
    "L3ASummaryStore",
    "L3ASubAgentPool",
    "build_l3a_prompt",
    "cardwrite_handler",
    "get_convergence_queue",
    "get_daemon",
    "get_l3a_pool",
    "get_summary_store",
    "reset_daemon",
    "start",
    "stop",
    "dispatch",
    "start_l3a_daemon",
    "stop_l3a_daemon",
]
