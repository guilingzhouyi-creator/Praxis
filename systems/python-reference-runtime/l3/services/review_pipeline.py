"""Review pipeline (2.1-D3) — bypass monitor + directed fix/rework.

Consumes a tier-2 (review) diff and decides the disposition:

  small  — changed lines <= the config-driven threshold: the review
           department applies a directed fix/supplement in place.
  large  — above the threshold: the change is routed back through the
           Cell-to-Cell channel for rework, and an async report is sent
           to the L3A info queue.

Both the pipeline enable switch and the threshold are config-driven
(config/discovery/review.yaml, params fallbacks) and adjustable at
runtime via PUT /api/v2/review/threshold.
"""

from __future__ import annotations

import logging
import threading

from l3.params import REVIEW_AUTOFIX_ENABLED_DEFAULT, REVIEW_PIPELINE_ENABLED_DEFAULT, REVIEW_SMALL_CHANGE_MAX_LINES

logger = logging.getLogger(__name__)

_pipeline_lock = threading.RLock()
_pipeline: ReviewPipeline | None = None


class ReviewPipeline:
    """Disposition engine for review diffs (small → fix, large → rework)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._max_small_lines = REVIEW_SMALL_CHANGE_MAX_LINES
        self._enabled = REVIEW_PIPELINE_ENABLED_DEFAULT
        self._autofix_enabled = REVIEW_AUTOFIX_ENABLED_DEFAULT

    # ── Config surface ──

    def set_threshold(self, max_small_lines: int) -> dict:
        """Adjust the small-change threshold at runtime (API)."""
        if max_small_lines < 1:
            return {"success": False, "error": "max_small_lines must be >= 1"}
        with self._lock:
            self._max_small_lines = int(max_small_lines)
        return {"success": True, "max_small_lines": self._max_small_lines}

    def set_enabled(self, enabled: bool, autofix: bool | None = None) -> dict:
        """Flip the pipeline / autofix switches (config or API)."""
        with self._lock:
            self._enabled = bool(enabled)
            if autofix is not None:
                self._autofix_enabled = bool(autofix)
        return {"success": True, "enabled": self._enabled, "autofix_enabled": self._autofix_enabled}

    def threshold(self) -> dict:
        """Current disposition settings (status surface)."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "autofix_enabled": self._autofix_enabled,
                "max_small_change_lines": self._max_small_lines,
            }

    # ── Disposition ──

    def dispose(
        self,
        review_diff: dict,
        rel_path: str = "",
        agent_id: str = "",
        cell_id: str = "",
        frame: bytes | None = None,
        intent: str = "",
        domain: str = "",
    ) -> dict:
        """Decide the disposition of a tier-2 review diff.

        Args:
            review_diff: Output of sandbox_diff.review_diff (has "stats").
            rel_path: Optional file path for reporting.
            agent_id: Optional agent attribution for reporting.
            cell_id: Optional producing Cell (directed rework channel).
            frame: Optional structure-aware frame (diff_codec.encode_hunks).
                When provided, the bypass threshold is decided from the
                8-byte plaintext header (hunk count) without decompressing
                the payload — the Phase-1 fast path; the stats-derived line
                count is used only as a tiebreak when header disagrees.
            intent: Driving task intent — HTN-C identity hit (build/test/
                review) is attached to the rework payload so the producing
                peer agent knows which identity must rework.
            domain: Optional card domain hint for identity matching.

        Returns:
            ``{"disposition": "small"|"large"|"disabled",
              "changed_lines": N, "fixed": bool, "rework": bool,
              "reported_to_l3a": bool, "line_records": [...]}``.
        """
        with self._lock:
            enabled = self._enabled
            autofix = self._autofix_enabled
            threshold = self._max_small_lines
        if not enabled:
            return {"disposition": "disabled", "changed_lines": 0}
        stats = (review_diff or {}).get("stats", {}) or {}
        changed = int(stats.get("changed_lines", 0) or 0)
        # HTN-C identity hit (peer agents): resolve the driving identity
        # from the intent/domain so the rework message tells the producing
        # peer which identity must fix the change. Empty when no hit.
        hit_identity = ""
        if intent or domain:
            try:
                from l3.bus.htn_planner import match_identity

                hit_identity = match_identity(intent, domain=domain)
            except Exception:
                hit_identity = ""
        # 2.1 Phase 1: bypass-threshold fast path — read the 8-byte frame
        # header (hunk count) without decompressing; large hunk counts
        # immediately route to rework even if the stats tiebreak disagrees.
        header_hunks = None
        if frame:
            try:
                from l4.sandbox.diff_frame import parse_frame_header

                head = parse_frame_header(frame)
                if head is not None:
                    header_hunks = int(head.get("hunk_count", 0))
            except Exception:
                header_hunks = None
        # 2.1: external knowledge-base reference (web_search) — the review
        # department consults the network knowledge base for extra reference
        # experience when hunks are present. Non-blocking, degrades to [].
        references = self._fetch_external_references(review_diff)
        # 2.1-D7 wiring: every reviewed diff emits line-precise records for
        # RC collection (feeds memory / training-corpus aggregation).
        line_records = self._emit_line_records(review_diff, rel_path)
        if changed <= threshold and (header_hunks is None or header_hunks <= threshold):
            fixed = autofix and changed > 0
            applied = self._apply_small_fix(review_diff, rel_path) if fixed else 0
            return {
                "disposition": "small",
                "changed_lines": changed,
                "fixed": fixed,
                "applied": applied,
                "rework": False,
                "reported_to_l3a": False,
                "references": references,
                "line_records": line_records,
            }
        # Large change → rework via the auto-routed Cell-to-Cell channel +
        # async L3A report (2.1 topology routing). The HTN-C identity hit
        # rides the rework message so the producing peer knows which
        # identity must fix the change.
        reported = self._report_l3a(rel_path, agent_id, changed, cell_id=cell_id, hit_identity=hit_identity)
        return {
            "disposition": "large",
            "changed_lines": changed,
            "fixed": False,
            "applied": 0,
            "rework": True,
            "reported_to_l3a": reported,
            "hit_identity": hit_identity,
            "references": references,
            "line_records": line_records,
        }

    def _fetch_external_references(self, review_diff: dict) -> list[dict]:
        """Query the external network knowledge base for reference experience.

        Builds a search query from the first hunk's added lines (the
        semantic change), then calls the web_search tool (l3.tools._web).
        The top results are returned as extra reference material for the
        review department. Degrades to [] when the tool is unavailable.

        Returns:
            List of ``{"title": ..., "url": ...}`` reference hits.
        """
        hunks = (review_diff or {}).get("hunks") or []
        if not hunks:
            return []
        try:
            from l1.kernel.params.system import LOG_TRUNC_120
            from l3.tools._web import web_search

            sample = hunks[0].get("added_lines", []) or hunks[0].get("removed_lines", []) or []
            query = " ".join(ln.strip() for ln in sample[:2])[:LOG_TRUNC_120]
            if not query:
                return []
            result = web_search({"query": query, "max_results": 3}, agent_id="review_pipeline")
            items = result.get("items") or []
            return [
                {"title": str(it.get("title", "")), "url": str(it.get("url", "") or it.get("href", ""))}
                for it in items[:3]
            ]
        except Exception as e:
            logger.debug("review_pipeline: external references skipped: %s", e)
            return []

    def _apply_small_fix(self, review_diff: dict, rel_path: str) -> int:
        """Directed fix execution: apply small reviewed hunks to the file.

        Builds a DiffEdit per hunk (old = removed lines, new = added lines)
        and runs it through the EditEngine (file_editor) so the review
        department's small fixes actually land on disk. Returns the number
        of hunks applied; degrades gracefully (0) when hunks are absent or
        the path is empty.
        """
        if not rel_path:
            return 0
        hunks = (review_diff or {}).get("hunks") or []
        if not hunks:
            return 0
        applied = 0
        try:
            from l3.services.file_editor import DiffEdit, get_engine

            engine = get_engine()
            for hunk in hunks:
                removed = "".join(hunk.get("removed_lines", []) or [])
                added = "".join(hunk.get("added_lines", []) or [])
                if not removed and not added:
                    continue
                edit = DiffEdit(
                    old_str=removed,
                    new_str=added,
                    path=rel_path,
                    description="review-directed small fix",
                )
                result = engine.diff_edit(edit)
                if result.get("success"):
                    applied += 1
        except Exception as e:
            logger.debug("review_pipeline: directed fix skipped: %s", e)
        return applied

    def _emit_line_records(self, review_diff: dict, rel_path: str) -> list[dict]:
        """Build and archive line-precise records for the reviewed hunks."""
        try:
            from l3.services.diff_record_source import build_line_records

            hunks = (review_diff or {}).get("hunks") or []
            records = build_line_records(rel_path, hunks, reviewed=True)
            if records:
                from l3.memory.tiered_cache import get_tiered_cache

                tc = get_tiered_cache()
                existing = tc.get_archive_index("diff:line_records") or {}
                existing["records"] = list(existing.get("records", [])) + records
                tc.index_archive("diff:line_records", existing)
            return records
        except Exception as e:
            logger.debug("review_pipeline: line records skipped: %s", e)
            return []

    def _report_l3a(
        self, rel_path: str, agent_id: str, changed: int, cell_id: str = "", hit_identity: str = ""
    ) -> bool:
        """Report a large-change rework: directed Cell channel + L3A queue.

        First attempts the auto-routed Cell-to-Cell channel (2.1 topology):
        a REVIEW_REWORK message is delivered hop-by-hop to the producing
        Cell's composite. The HTN-C identity hit (build/test/review) rides
        the payload so the producing peer knows which identity must fix the
        change. Then always emits the async L3A info-queue event as the
        coordination backstop. Both degrade gracefully.

        Returns:
            True when at least one report path succeeded.
        """
        directed = False
        if cell_id:
            try:
                from l3.bus.l3b_bus import L3BMessageType
                from l3.bus.l3b_bus import get_bus as get_l3b

                r = get_l3b().route_to_cell(
                    sender="",
                    target_cell=cell_id,
                    msg_type=L3BMessageType.REVIEW_REWORK,
                    payload={
                        "rel_path": rel_path,
                        "agent_id": agent_id,
                        "changed_lines": changed,
                        "hit_identity": hit_identity,
                    },
                )
                directed = bool(r.get("success"))
                if not directed:
                    logger.debug("review_pipeline: directed rework unrouted: %s", r.get("error", "?"))
            except Exception as e:
                logger.debug("review_pipeline: directed rework skipped: %s", e)
        try:
            from l1.kernel.event import get_bus

            get_bus().emit_event(
                "review_rework_requested",
                {"rel_path": rel_path, "agent_id": agent_id, "changed_lines": changed, "cell_id": cell_id},
                source="review_pipeline",
            )
            return True
        except Exception as e:
            logger.debug("review_pipeline: L3A report skipped: %s", e)
            return directed


def get_review_pipeline() -> ReviewPipeline:
    """Get the global ReviewPipeline singleton."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            _pipeline = ReviewPipeline()
        return _pipeline


def reset_review_pipeline() -> None:
    """Reset the singleton (used by tests)."""
    global _pipeline
    with _pipeline_lock:
        _pipeline = None
