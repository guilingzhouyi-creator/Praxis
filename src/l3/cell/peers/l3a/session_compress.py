"""SessionCompressMixin — history compression + memory accounting for L3A Session.

Extracted from session.py (P1-1 split).  ``Message`` is imported lazily from
session.py to avoid a circular import — by method-call time the session
module is fully loaded.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from l1.kernel.params.system import (
    HASH_TRUNC_MEDIUM,
    HASH_TRUNC_SHORTEST,
    LOG_TRUNC_200,
    LOG_TRUNC_300,
    SESSION_MSG_OVERHEAD,
    TOKEN_CHARS_PER_TOKEN,
)

from . import params as _p

if TYPE_CHECKING:
    from l3.cell.peers.l3a.session_history import Message, SessionHistory

logger = logging.getLogger(__name__)


class SessionCompressMixin:
    """SessionCompressMixin — rate-distortion-aware history compression."""

    # ── Attributes injected by the concrete Session (see session.py) ──
    id: str
    turn_count: int
    status: str
    _lock: threading.RLock
    history: SessionHistory

    def context_stats(self) -> dict:
        """Compute session context pressure (provided by SessionPromptMixin)."""
        raise NotImplementedError

    @staticmethod
    def _message_value(m: Message) -> int:
        """Rate a message's information value (rate-distortion weighting).

        3 = high value — user explicit intent, card results, convention
            references, prior compression summaries. Preserved in full.
        2 = medium     — assistant answers, tool-call records.
        1 = low        — verbose tool output, boilerplate.
        """
        if m.role == "user":
            return 3
        if m.role == "system":
            meta = m.metadata or {}
            if meta.get("card_id") or meta.get("compression"):
                return 3
            if meta.get("context_key"):
                return 2
            return 2
        return 2

    def _compression_guard_check(self) -> dict | None:
        """Return a blocked dict when the recursion circuit breaker trips."""
        try:
            from l3.agent.compression_guard import check_recursion

            guard = check_recursion(str(getattr(self, "id", "")))
            if guard.get("blocked"):
                return {
                    "success": False,
                    "error": guard.get("error", "compression guarded"),
                    "compressed": 0,
                    "kept": 0,
                    "compression_ratio": 0.0,
                }
        except Exception:
            logger.debug("l3a session: compression guard skipped")
        return None

    def _split_history(self, keep_last: int) -> tuple[list, list, int, int] | None:
        """Locked split: return (keep, old, total, before_tokens) or None when nothing to compress."""
        with self._lock:
            total = len(self.history._messages)
            if total <= keep_last:
                return None
            keep = self.history._messages[-keep_last:]
            old = self.history._messages[:-keep_last]
            before_tokens = sum(len(m.content) // TOKEN_CHARS_PER_TOKEN + SESSION_MSG_OVERHEAD for m in old)
        return keep, old, total, before_tokens

    def _archive_snapshot(self, old: list) -> str:
        """Lossless snapshot of the folded messages to R4 (deferred access, not loss)."""
        snapshot_ref = ""
        try:
            import json as _json

            from l3.tools._archive import _cmd_archive_store

            snapshot = {
                "session_id": self.id,
                "turn": self.turn_count,
                "compressed_at": time.time(),
                "compressed_count": len(old),
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at,
                        "metadata": m.metadata,
                    }
                    for m in old
                ],
            }
            r = _cmd_archive_store(
                fonds="AGENT:l3a",
                series="session_compression_snapshot",
                content=_json.dumps(snapshot, ensure_ascii=False, default=str),
                tags=f"l3a,session_compression,{self.id}",
            )
            if r.get("success"):
                snapshot_ref = f"snapshot:l3a:{self.turn_count}"
        except Exception:
            logger.debug("l3a session: compression snapshot failed")
        return snapshot_ref

    def _deduplicate_span(self, old: list) -> tuple[list, int]:
        """Drop stale duplicate user messages inside the folded span (content fingerprint)."""
        import hashlib

        deduplicated = 0
        seen_fp: set[str] = set()
        deduped: list[Any] = []
        for m in old:
            if m.role == "user":
                fp = hashlib.md5(m.content.encode("utf-8", errors="replace")).hexdigest()[:HASH_TRUNC_MEDIUM]
                if fp in seen_fp:
                    deduplicated += 1
                    continue
                seen_fp.add(fp)
            deduped.append(m)
        return deduped, deduplicated

    def _build_summary(self, deduped: list, summary: str) -> tuple[str, list, list, list, bool]:
        """Five-level value-weighted summary (raw/summarized/retained/skeleton/headline)."""
        # Level 1 (raw): high-value messages preserved verbatim.
        # Level 2 (summarized): medium-value messages condensed to previews.
        # Level 3 (retained): the most recent `keep_last` messages stay raw.
        # Level 4 (skeleton): low-value messages reduced to a count line.
        # Level 5 (headline): the earliest user intent becomes one headline.
        high = [m for m in deduped if self._message_value(m) >= 3]
        medium = [m for m in deduped if self._message_value(m) == 2]
        low = [m for m in deduped if self._message_value(m) <= 1]
        lines = []
        # Level 5: headline from the earliest user intent in the span.
        headline = ""
        earliest_user = next((m for m in deduped if m.role == "user"), None)
        if earliest_user is not None:
            headline = f"HEADLINE: {earliest_user.content[:LOG_TRUNC_200]}"
            lines.append(headline)
        if high:
            lines.append("Earlier key context (preserved in full):")
            for m in high:
                prefix = "USER" if m.role == "user" else "CARD"
                lines.append(f"- [{prefix}] {m.content[:LOG_TRUNC_300]}")
        if medium:
            user_med = [m for m in medium if m.role == "user"]
            if user_med:
                lines.append("Earlier user requests:")
                for m in user_med[:5]:
                    lines.append(f"- {m.content[:LOG_TRUNC_200]}")
                if len(user_med) > 5:
                    lines.append(f"- ... and {len(user_med) - 5} more")
        if low:
            lines.append(f"(dropped {len(low)} low-value items, see snapshot)")
        if not lines:
            lines.append("(prior conversation summarized)")
        summary_text = summary or "\n".join(lines)
        # Deterministic compaction extractor (decision-layer fidelity): when
        # the operator mode is not 'off', the assembled summary passes
        # through the hybrid extractor which keeps high-signal lines
        # (paths/commands/errors/decisions) while dropping filler — the
        # decision layer's folded context stays fact-dense. Degrades to the
        # assembled text unchanged on any failure.
        try:
            from l3.memory.memory_extract import compaction_status, extract

            if compaction_status().get("mode", "off") != "off":
                extracted = extract(summary_text)
                if extracted:
                    summary_text = extracted
        except Exception:
            logger.debug("l3a session: compaction extractor skipped")
        return summary_text, high, medium, low, bool(headline)

    def _persist_compression_memory(self, summary_text: str, old: list, high: list, snapshot_ref: str) -> None:
        """Persist the summary + compression index across the three memory rings."""
        try:
            from l3.memory.central_memory import get_l3a_memory

            mem = get_l3a_memory()
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="session_compression",
                content=f"[session:{self.id}] turn={self.turn_count}: {summary_text}",
                tags=["l3a", "compression", self.id],
                importance=0.6,
                ring=2,
            )
            # Link compression into all three rings:
            # R1 — compression action record (recent activity)
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_compression_action",
                content=f"[session:{self.id}] turn={self.turn_count}: "
                f"compressed {len(old)} msgs, snapshot={snapshot_ref}",
                tags=["l3a", "compression", self.id],
                importance=0.4,
                ring=1,
            )
            # R3 — long-term compression index with lossless snapshot ref
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_compression_index",
                content=f"[session:{self.id}] turn={self.turn_count}: "
                f"compressed {len(old)} msgs | high-value kept "
                f"{len(high)} | snapshot: {snapshot_ref or 'n/a'}",
                tags=["l3a", "compression", "index", self.id],
                importance=0.8,
                ring=3,
            )
        except Exception:
            logger.debug("l3a session: compression memory persist failed")

    def _apply_sensitive_policy(self, summary_text: str) -> tuple[str, list, bool]:
        """Apply the sensitive-info action policy (report/redact/block).

        Runs BEFORE the fold so redact actually changes the folded text and
        block refuses the fold instead of folding first.
        """
        action = "report"
        hits: list = []
        final_text = summary_text
        try:
            from l3.agent.sensitive_detect import redact_text, scan_text, sensitive_action

            action = sensitive_action()
            hits = scan_text(summary_text)
            if hits and action == "redact":
                final_text = redact_text(summary_text)
        except Exception:
            logger.debug("l3a session: sensitive policy skipped")
        if hits:
            logger.warning("l3a session %s: %d sensitive hit(s) in summary (action=%s)", self.id, len(hits), action)
        return final_text, hits, action == "block" and bool(hits)

    def _post_compress_scan(self) -> None:
        """Record the compression pass for the recursion-threshold bookkeeping."""
        try:
            from l3.agent.compression_guard import record_compress_pass

            record_compress_pass(str(getattr(self, "id", "")))
        except Exception:
            logger.debug("l3a session: compression guard bookkeeping skipped")

    def _compact_graph(self) -> None:
        """R5 swarm-domain graph reduction after compaction (derived layer, non-blocking)."""
        try:
            from l3.memory.memory_graph import get_graph as _gg

            g = _gg()
            if g.enabled:
                g.compact(min_degree=2, dry_run=False)
        except Exception:
            logger.debug("l3a session: graph compact after compress failed")

    def compress(self, keep_last: int = _p.SESSION_COMPRESS_KEEP, summary: str = "") -> dict:
        """Compress session history into a summary, keeping the last N messages.

        Rate-distortion aware:
          1. Lossless snapshot — the folded messages' full text is archived
             to R4 (fonds=AGENT:l3a, series=session_compression_snapshot)
             BEFORE folding, so compression = deferred access, not loss.
          2. Value-weighted summary — high-value messages (user intents,
             card results, convention refs) are preserved in full; medium
             ones get a preview list; low-value ones are only counted.
          3. Distortion report — returns role/type distribution, high-value
             preservation counts, and the snapshot archive_ref.
        """
        # Phase 3.1 B6: recursive-compression threshold + circuit breaker —
        # a tripped breaker or a reached threshold stops the pass before
        # anything is folded (default: recursive off, breaker on). Degrades
        # to a no-op guard when the module is unavailable.
        blocked = self._compression_guard_check()
        if blocked:
            return blocked
        try:
            return self._compress_impl(keep_last, summary)
        except Exception:
            self._report_compress_error()
            raise

    def _report_compress_error(self) -> None:
        """Report a compression failure to the circuit breaker (error-storm tracking)."""
        try:
            from l3.agent.compression_guard import report_compress_error

            report_compress_error(str(getattr(self, "id", "")))
        except Exception:
            logger.debug("l3a session: error-storm report skipped")

    def _compress_impl(self, keep_last: int = _p.SESSION_COMPRESS_KEEP, summary: str = "") -> dict:
        """Run the five-level compression pipeline (lossless snapshot + fold)."""
        from .session_history import Message as _Message

        split = self._split_history(keep_last)
        if split is None:
            return {
                "success": True,
                "note": "nothing to compress",
                "compressed": 0,
                "kept": len(self.history._messages),
                "compression_ratio": 0.0,
            }
        keep, old, _total, before_tokens = split

        # ── 1. Lossless snapshot to R4 (deferred access, not loss) ──
        snapshot_ref = self._archive_snapshot(old)

        # ── 2. Five-level pipeline (Claude Code-style progressive compaction) ──
        # Phase 3.1 B4: content-fingerprint dedup (drop stale duplicates) — repeated
        # identical user messages inside the folded span collapse to one
        # so stale duplicates never inflate the summary; the lossless R4
        # snapshot above still keeps every original message. The dropped
        # count is reported for the operator baseline.
        deduped, deduplicated = self._deduplicate_span(old)
        # Premise guard (decision-layer fidelity): anchors are collected
        # BEFORE the fold; after the summary is built, anchors missing from
        # it inject a one-shot reminder so a lost premise is surfaced, never
        # silently dropped. Degrades to a no-op when the module is unavailable.
        premise_anchors: list = []
        try:
            from l3.memory.premise_guard import check_summary, extract_anchors

            premise_anchors = extract_anchors(deduped)
        except Exception:
            logger.debug("l3a session: premise anchor extraction skipped")
        summary_text, high, medium, low, headline = self._build_summary(deduped, summary)
        if premise_anchors:
            try:
                from l3.memory.premise_guard import check_summary, guard_reminder

                missing = check_summary(premise_anchors, summary_text)
                reminder = guard_reminder(missing)
                if reminder:
                    summary_text = f"{summary_text}\n\n{reminder}"
            except Exception:
                logger.debug("l3a session: premise guard skipped")

        # Phase 3.1 G6: sensitive-info action policy (report/redact/block)
        # applied BEFORE the fold so redact changes the folded text and block
        # refuses the fold outright.
        summary_text, sensitive_hits, sensitive_blocked = self._apply_sensitive_policy(summary_text)
        if sensitive_blocked:
            return {
                "success": False,
                "error": "compression blocked by sensitive-info policy (block action)",
                "compressed": 0,
                "sensitive_hits": sensitive_hits,
            }

        # Persist the summary into L3A's own memory (ring 2) before folding
        self._persist_compression_memory(summary_text, old, high, snapshot_ref)

        with self._lock:
            summary_msg = _Message(
                id=f"sum-{uuid.uuid4().hex[:HASH_TRUNC_SHORTEST]}",
                role="system",
                content=f"[SESSION COMPRESSED at turn {self.turn_count}] {summary_text}",
                metadata={
                    "compression": True,
                    "compressed": len(old),
                    "snapshot_ref": snapshot_ref,
                    "high_value_preserved": len(high),
                    "kept": keep_last,
                },
            )
            self.history._messages = [summary_msg] + keep
        after_tokens = len(summary_text) // TOKEN_CHARS_PER_TOKEN + SESSION_MSG_OVERHEAD
        # Phase 3.1 B6: record the compression pass for the recursion
        # threshold (the sensitive scan now runs BEFORE the fold via
        # _apply_sensitive_policy — G6 action semantics).
        self._post_compress_scan()
        logger.info("l3a session %s: compressed %d msgs → summary (+%d kept)", self.id, len(old), keep_last)
        # ── R5 swarm-domain graph linkage: graph reduction after compaction (derived layer, failures non-blocking) ──
        self._compact_graph()
        # Phase 3.1 G5: structured compression event → ReferenceChannel for analysis.
        try:
            from l3.bus.reference_channel import get_rc

            get_rc().event(
                "l3a_compress",
                {
                    "session_id": str(self.id),
                    "compressed": len(old),
                    "kept": keep_last,
                    "deduplicated": deduplicated,
                    "compression_ratio": round(before_tokens / after_tokens, 2) if after_tokens > 0 else 0.0,
                    "sensitive_hits": len(sensitive_hits),
                    "levels_raw": len(high),
                    "levels_summarized": len(medium),
                    "levels_skeleton": len(low),
                },
                source="session_compress",
            )
        except Exception:
            logger.debug("l3a session: RC compress event skipped")
        return {
            "success": True,
            "session_id": self.id,
            "compressed": len(old),
            "kept": keep_last,
            # Phase 3.1 B4: stale-duplicate count dropped by content
            # fingerprint inside the folded span (0 = no dedup happened).
            "deduplicated": deduplicated,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            # Phase 3.1 B3: compression-ratio baseline — how much the folded
            # span shrank (before/after token counts). 0.0 when nothing was
            # compressed; guard against divide-by-zero on empty summaries.
            "compression_ratio": (round(before_tokens / after_tokens, 2) if after_tokens > 0 else 0.0),
            "sensitive_hits": sensitive_hits,
            "summary": summary_text,
            "snapshot_ref": snapshot_ref,
            # Phase 3.1 B5: five-level pipeline stats (raw/summarized/
            # retained/skeleton/headline) for the operator baseline.
            "levels": {
                "raw": len(high),
                "summarized": len(medium),
                "retained": keep_last,
                "skeleton": len(low),
                "headline": headline,
            },
            "distortion": {
                "high_value_preserved": len(high),
                "medium_value_summarized": len(medium),
                "low_value_dropped": len(low),
                "by_role": {
                    "user": sum(1 for m in old if m.role == "user"),
                    "assistant": sum(1 for m in old if m.role == "assistant"),
                    "system": sum(1 for m in old if m.role == "system"),
                },
                "note": ("high-value messages preserved in full; full text recoverable via snapshot_ref")
                if snapshot_ref
                else "snapshot unavailable",
            },
        }

    def auto_compress_check(self, force: bool = False) -> dict:
        """System-monitored auto-compression: checks context pressure against
        the configured threshold and compresses when exceeded.

        Strategy (SettingsCenter):
          l3a.auto_compress           — master switch (default True)
          l3a.auto_compress_threshold — pressure_ratio trigger (default 0.6)
          l3a.auto_compress_keep      — messages kept (default 10)
        """
        try:
            from l3.config.settings_center import get_center

            sc = get_center()
            enabled = bool(sc.get("l3a.auto_compress", True))
            threshold = float(sc.get("l3a.auto_compress_threshold", 0.6))
            keep = int(sc.get("l3a.auto_compress_keep", 10))
        except Exception:
            enabled, threshold, keep = True, 0.6, 10

        if not enabled and not force:
            return {"success": True, "action": "skipped", "reason": "auto_compress disabled"}
        if self.status != "active":
            return {"success": True, "action": "skipped", "reason": "session closed"}

        stats = self.context_stats()
        pressure = stats.get("pressure_ratio", 0.0)
        if pressure < threshold and not force:
            return {"success": True, "action": "none", "pressure": pressure, "threshold": threshold}
        if self.history.count() <= keep:
            return {
                "success": True,
                "action": "none",
                "pressure": pressure,
                "threshold": threshold,
                "reason": "history below keep size",
            }
        r = self.compress(keep_last=keep)
        r["action"] = "compressed"
        r["pressure_before"] = pressure
        r["threshold"] = threshold
        logger.info("l3a session %s: auto-compressed at pressure %.2f (threshold %.2f)", self.id, pressure, threshold)
        return r

    def memory_usage(self, window: float = _p.SESSION_MEMORY_WINDOW_SECONDS) -> dict:
        """Report the session's R1-R3 ring usage and ingress rates.

        window: seconds for the ingress-rate window (default 1h).
        Reads from L3A's own isolated memory instance via CentralMemory.
        """
        try:
            from l3.memory.central_memory import get_l3a_memory

            mem = get_l3a_memory()
            stats = mem.stats() if hasattr(mem, "stats") else {}
            now = time.time()
            since = now - window
            recent = mem.recall(agent_id=_p.AGENT_ID, rings=[1, 2, 3], limit=500)
            ingress: dict[str, Any] = {"count": 0, "by_type": {}}
            for e in recent:
                if getattr(e, "timestamp", 0) >= since:
                    ingress["count"] += 1
                    t = getattr(e, "entry_type", "?")
                    ingress["by_type"][t] = ingress["by_type"].get(t, 0) + 1
            pressure = mem.pressure() if hasattr(mem, "pressure") else {}
        except Exception as e:
            logger.debug("l3a session: memory_usage failed: %s", e)
            return {"success": False, "error": str(e)}
        return {
            "success": True,
            "session_id": self.id,
            "window_seconds": window,
            "rings": stats,
            "pressure": pressure,
            "ingress": {
                "count": ingress["count"],
                "per_hour": round(ingress["count"] / max(window / 3600.0, 0.001), 2),
                "by_type": dict(sorted(ingress["by_type"].items(), key=lambda x: x[1], reverse=True)),
            },
        }
