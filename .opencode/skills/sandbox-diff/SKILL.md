---
name: sandbox-diff
description: Use when writing or modifying Praxis sandbox or structured-diff code — per-hunk attribution, three-tier topology (build/review/conflict), structured hunk frames, tiered compression, diff_persist ring buffer, diff_languages registry, or the bypass monitor.
---

## Overview

Architecture guide for the sandbox / structured diff system (`systems/python-reference-runtime/l4/sandbox/`, `systems/python-reference-runtime/l1/kernel/diff_frame.py`, spec: `docs/architecture/sandbox-diff.md`). Every agent edit lands in the sandbox with per-hunk attribution; diffs are computed tier-shaped and compressed with shared dictionaries.

## Module Map

- **Entries**: `entry.py`, `sandbox_entry.py` — per-hunk attribution: `agent_id`, `tool_name`, `task_id`, `modified_at` (ISO 8601); entries keyed `path::agent_id` so parallel agents edit the same file independently
- **Managers**: `manager.py`, `sandbox_manager.py`, `cell_sandbox.py` — sandbox state (in-memory → Cell cache → persistent `.praxis/sandbox_state.json` in data_dir); `server.py` (MCP bridge)
- **Tiers**: `sandbox_diff.py` — `build_diff` (precise hunks), `review_diff` (structured hunks + `context_lines` + per-hunk attribution + `lsp_diagnostics`/`ast_symbols`), `conflict_diff` (cross-cell: none/warn/block/ping_pong). `POST /api/v2/diff/tier` serves them
- **Codec**: `diff_codec.py` — `encode_hunks`/`decode_hunks` (type/semantic dictionary-coded to bytes, delta-encoded original_start, zlib payload; 8-byte plaintext header in L1 `diff_frame.py`: frame_type | bitmask | threshold_score | hunk_count)
- **Compression**: `diff_dict.py` — shared Zstd dictionary (trained from `diff_languages.yaml` `diff_dictionary.samples_dir`, persisted, magic `PDZ`; zlib fallback `PD2`; L3 archive re-compresses zstd level 19 `PDZ19`); zstandard is an enhancement, never a hard dependency
- **Language registry**: `diff_language.py` — dispatcher over `config/discovery/diff_languages.yaml` (extensions / symbol_backend / semantic); new languages join by YAML edit, never a code change; fallback = language-agnostic line diff
- **Persistence**: `diff_persist.py` — ring buffer + fixed-interval JSONL flush (gated by `diff.persist.enabled`, frontend-heavy only; `DIFF_PERSIST_FILE` in paths.py) + crash `recover()`; ring overflow compresses oldest diff into R4 (`fonds="diff", series="stitched"`) and emits `diff_evicted_to_r4`
- **Consumers**: `ast_edit.py`, `diff_language.py` (Python AST via stdlib, others line-level); bypass monitor `l3/services/review_pipeline.py` (consumes tier-2 diff; small ≤ `config/discovery/review.yaml` `max_small_change_lines` → directed fixes; large → Cell-to-Cell channel `L3BBus.route_to_cell` + async L3A event)

## Core Conventions

- **Per-hunk attribution is load-bearing**: every sandbox write records agent/tool/task/timestamp per hunk; never write sandbox entries without attribution (cross-review and the bypass monitor depend on it).
- **Wire format shared between L1 and L4**: the 8-byte diff-frame header lives in L1 `diff_frame.py` so the L3 bypass monitor and the L4 codec share ONE format (exported via kernel `__all__`); `review_pipeline.dispose(frame=...)` reads hunk_count without decompressing (bypass fast path).
- **Diff views**: `agent` (attribution), `human` (readable), `summary` (stats-only), `colored` (semantic colorization; colors via `config/praxis.yaml` `diff.colors`, `POST /api/v2/diff/colors` get/set/reset).
- **Card linkage**: `ci_review._run_review_disposition` runs the review pipeline over a card's changed files on completion, merging structured dispositions into the report context.
- **Degrade gracefully**: every enhancement (LSP diagnostics, AST symbols, zstd) degrades to `[]`/fallback — never a hard dependency.

## Tests

- `python -m pytest tests/l4/test_sandbox.py -x -q`
- `python -m pytest tests/ -k "sandbox or diff" -x -q`
