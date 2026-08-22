"""API handlers for structured diff queries — exposes sandbox diff data to frontends.

Gated by ``diff_heavy_api_enabled`` setting (default False).
"""

from __future__ import annotations

import logging

from l1.kernel.params.system import PAGER_RECALL_LIMIT

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    """Check whether the heavy diff API is enabled.

    Precedence: env var > config file > disabled by default.
    """
    import os

    env = os.environ.get("PRAXIS_DIFF_HEAVY_API", "").lower()
    if env in ("1", "true", "yes"):
        return True
    try:
        from l3.config.settings_center import get_center

        return bool(get_center().get("diff.heavy_api_enabled", False))
    except Exception:
        return False


def _lsp_diagnostics(rel_path: str) -> list[dict]:
    """Fetch LSP diagnostics for a file as extra review context (2.1).

    The review department consumes these alongside the structured hunks to
    spot hazards (type errors, syntax issues) the diff alone hides.
    Degrades to [] when the LSP manager is unavailable or the file type is
    unsupported — the review must never fail because of LSP.
    """
    if not rel_path:
        return []
    try:
        from l4.lsp.lsp_manager import get_manager

        r = get_manager().get_diagnostics(rel_path)
        return r.get("diagnostics", []) if r.get("success") else []
    except Exception as e:
        logger.debug("api_handlers_diff: lsp diagnostics skipped: %s", e)
        return []


def _ast_symbols(rel_path: str) -> list[dict]:
    """Extract AST symbols for a file as extra review context (2.1).

    Lets the review department correlate hunks with the symbols they touch
    (function/class definitions + line numbers). Uses SymbolSearch's cached
    AST trees; degrades to [] for non-Python or unreadable files.
    """
    if not rel_path:
        return []
    try:
        from l4.search.search_engine import SymbolSearch

        r = SymbolSearch().symbols_in_file(rel_path)
        return r.get("symbols", []) if r.get("success") else []
    except Exception as e:
        logger.debug("api_handlers_diff: ast symbols skipped: %s", e)
        return []


def diff_structured(body: dict) -> dict:
    """POST /api/diff/structured — Get structured diff for a sandbox-staged file.

    Request body::

        {"path": "src/foo.py",          # required
         "mode": "agent"|"human"|"summary",  # optional, default "agent"
         "cell_id": "cell-1"}           # optional, searches all cells if omitted

    Returns:
      agent mode   → raw hunks (full structure, for LLM)
      human mode   → unified diff text
      summary mode → lightweight structured summary (for dashboard, cached)
    """
    if not _is_enabled():
        return {"success": False, "error": "diff heavy API is disabled (set diff.heavy_api_enabled=true)"}
    path = body.get("path", "")
    if not path:
        return {"success": False, "error": "path required"}
    mode = body.get("mode", "agent")
    if mode not in ("agent", "human", "summary", "colored"):
        return {"success": False, "error": f"invalid mode: {mode!r}"}
    cell_id = body.get("cell_id", "")

    try:
        from l4.sandbox import get_manager as _get_sb

        sb_mgr = _get_sb()
    except Exception as e:
        return {"success": False, "error": f"sandbox unavailable: {e}"}

    found_cell: str = ""
    result = None
    entry = None

    if cell_id:
        sb = sb_mgr.get_cell(cell_id)
        if sb:
            if mode == "summary":
                result = sb.get_entry_summary(path)
            else:
                entry = sb.get_entry(path)
                if entry:
                    result = entry.hunks if mode == "agent" else entry.to_human_readable()
            if result:
                found_cell = cell_id
    else:
        try:
            status = sb_mgr.status()
            for cid in status:
                sb = sb_mgr.get_cell(cid)
                if not sb:
                    continue
                if mode == "summary":
                    result = sb.get_entry_summary(path)
                else:
                    entry = sb.get_entry(path)
                    if entry:
                        result = entry.hunks if mode == "agent" else entry.to_human_readable()
                if result:
                    found_cell = cid
                    break
        except Exception:
            logger.debug("api_handlers_diff: cell scan in diff_structured failed")

    if not result:
        return {"success": False, "error": f"no sandbox entry for {path}"}

    return _diff_structured_response(mode, entry, result, path, found_cell)


def _diff_structured_response(mode: str, entry, result, path: str, found_cell: str) -> dict:
    """Build the success response for a resolved sandbox entry."""
    if mode == "summary":
        return {
            "success": True,
            "path": path,
            "cell_id": found_cell,
            "summary": result,
        }

    # colored mode uses to_colored_diff() instead of raw hunks
    if mode == "colored":
        colored = entry.to_colored_diff()
        return {
            "success": True,
            "path": path,
            "cell_id": found_cell,
            "colored_diff": colored,
        }

    return {
        "success": True,
        "path": path,
        "cell_id": found_cell,
        "agent_id": entry.agent_id,
        "task_id": entry.task_id,
        "status": entry.status,
        "conflict_level": entry.conflict_level,
        "stats": entry.stats,
        "modified_at": entry.modified_at,
        "hunks": result if mode == "agent" else None,
        "human_readable": result if mode == "human" else None,
    }


def diff_tier(body: dict) -> dict:
    """POST /api/v2/diff/tier — three-tier topology diff view (2.1-D1).

    Body::

        {"tier": "build"|"review"|"conflict",   # required
         "old_text": str, "new_text": str,       # build/review (text pair)
         "rel_path": str, "agent_id": str,       # attribution
         "tool_name": str,
         "path_index": {...}, "entries": {...}}  # conflict only

    Returns the tier-shaped diff:
      build    → precise hunks + unified view + stats
      review   → hunks + per-hunk attribution + context
      conflict → cross-cell conflict level (none/warn/block/ping_pong)
    """
    if not _is_enabled():
        return {"success": False, "error": "diff heavy API is disabled (set diff.heavy_api_enabled=true)"}
    tier = body.get("tier", "")
    if tier not in ("build", "review", "conflict"):
        return {"success": False, "error": f"invalid tier: {tier!r} (build|review|conflict)"}
    try:
        from l4.sandbox.sandbox_diff import build_diff, conflict_diff, review_diff

        if tier == "conflict":
            result = conflict_diff(
                rel_path=str(body.get("rel_path", "")),
                agent_id=str(body.get("agent_id", "")),
                path_index=body.get("path_index") or {},
                entries=body.get("entries") or {},
            )
        else:
            old_text = str(body.get("old_text", ""))
            new_text = str(body.get("new_text", ""))
            kwargs = {
                "agent_id": str(body.get("agent_id", "")),
                "tool_name": str(body.get("tool_name", "")),
                "timestamp": float(body.get("timestamp", 0.0) or 0.0),
            }
            if tier == "review":
                result = review_diff(
                    old_text,
                    new_text,
                    rel_path=str(body.get("rel_path", "")),
                    context_lines=int(body.get("context_lines", 0) or 0),
                    **kwargs,
                )
                # 2.1: attach LSP diagnostics as extra review context so the
                # review department can spot hazards beyond the diff hunks.
                result["lsp_diagnostics"] = _lsp_diagnostics(str(body.get("rel_path", "")))
                # 2.1: attach AST symbols so the review can correlate hunks
                # with the functions/classes they touch.
                result["ast_symbols"] = _ast_symbols(str(body.get("rel_path", "")))
                # 2.1 Phase 1: attach the structure-aware frame (dictionary-
                # coded hunks + 8-byte plaintext header) so consumers can
                # read the bypass threshold (hunk count) without decompressing.
                hunks = result.get("hunks") or []
                if hunks:
                    from l4.sandbox.diff_codec import FRAME_REVIEW, encode_hunks, parse_frame_header

                    frame = encode_hunks(hunks, frame_type=FRAME_REVIEW)
                    result["frame"] = frame
                    result["frame_header"] = parse_frame_header(frame)
                # 2.1 Phase 3: AST tree-edit frame for declared languages
                # (tree_backend=python_ast) — semantic INS/DEL/MOV/UPD script
                # instead of row hunks. Non-python / unparseable files keep
                # the hunk frame (declarative fallback, never a hard error).
                rel = str(body.get("rel_path", ""))
                if rel:
                    try:
                        from l4.sandbox.diff_language import get_registry

                        tree_backend = ""
                        reg = get_registry()
                        lang = reg.detect_language(rel)
                        if lang:
                            tree_backend = reg._languages[lang].get("tree_backend", "none")
                        if tree_backend == "python_ast":
                            from l4.sandbox.ast_edit import tree_edit_script
                            from l4.sandbox.diff_codec import encode_ast_script
                            from l4.sandbox.diff_dict import get_dictionary

                            script = tree_edit_script(old_text, new_text)
                            if script is not None:
                                ast_frame = encode_ast_script(
                                    script,
                                    frame_type=FRAME_REVIEW,
                                    dictionary=get_dictionary(),
                                    hunk_count=len(hunks),
                                )
                                result["ast_frame"] = ast_frame
                                result["ast_frame_header"] = parse_frame_header(ast_frame)
                    except Exception:
                        logger.debug("api_handlers_diff: ast frame skipped")
            else:
                result = build_diff(old_text, new_text, **kwargs)
        return {"success": True, "tier": tier, "diff": result}
    except Exception as e:
        logger.warning("api_handlers_diff: diff_tier failed: %s", e)
        return {"success": False, "error": str(e)}


def diff_history(body: dict) -> dict:
    """GET /api/diff/history — List all sandbox entries across cells.

    Request body::

        {"cell_id": "cell-1",           # optional, filter by cell
         "agent_id": "agent-a",         # optional, filter by agent
         "path": "src/foo.py",          # optional, filter by path
         "limit": 20}                   # optional, default 50
    """
    if not _is_enabled():
        return {"success": False, "error": "diff heavy API is disabled (set diff.heavy_api_enabled=true)"}
    cell_id = body.get("cell_id", "")
    agent_id = body.get("agent_id", "")
    path_filter = body.get("path", "")
    limit = body.get("limit", PAGER_RECALL_LIMIT)

    try:
        from l4.sandbox import get_manager as _get_sb

        sb_mgr = _get_sb()
    except Exception as e:
        return {"success": False, "error": f"sandbox unavailable: {e}"}

    entries: list[dict] = []
    try:
        status = sb_mgr.status()
        cells = [cell_id] if cell_id else list(status.keys())
        for cid in cells:
            sb = sb_mgr.get_cell(cid)
            if not sb:
                continue
            for entry in sb.get_entries():
                if path_filter and entry.path != path_filter:
                    continue
                if agent_id and entry.agent_id != agent_id:
                    continue
                if entry.status in ("flushed", "discarded"):
                    continue
                entries.append(
                    {
                        "path": entry.path,
                        "cell_id": cid,
                        "agent_id": entry.agent_id,
                        "tool_name": entry.tool_name,
                        "status": entry.status,
                        "task_id": entry.task_id,
                        "conflict_level": entry.conflict_level,
                        "stats": entry.stats,
                        "modified_at": entry.modified_at,
                    }
                )
                if len(entries) >= limit:
                    break
            if len(entries) >= limit:
                break
    except Exception:
        logger.debug("api_handlers_diff: cell scan in diff_history failed")

    return {"success": True, "entries": entries, "count": len(entries)}


def diff_colors(body: dict | None = None) -> dict:
    """GET /api/diff/colors — Get current color scheme.

    POST /api/diff/colors — Update color scheme.

    Request body (POST)::

        {"scheme": {"logic_change": "\\\\033[31m", ...}}

    All semantic keys are optional; only provided keys are updated.
    """
    from l4.sandbox.cell_sandbox import get_color_scheme, reset_color_scheme, set_color_scheme

    b = body or {}
    action = b.get("action", "get")
    if action == "get":
        return {"success": True, "scheme": get_color_scheme()}
    if action == "reset":
        reset_color_scheme()
        return {"success": True, "scheme": get_color_scheme(), "notice": "reset to defaults"}
    scheme = b.get("scheme", {})
    if not isinstance(scheme, dict):
        return {"success": False, "error": "scheme must be a dict"}
    set_color_scheme(scheme)
    return {"success": True, "scheme": get_color_scheme(), "updated": list(scheme.keys())}
