# Sandbox / Structured Diff System

Comprehensive description of the sandbox diff model, the three-tier topology,
and the phase-1/2/3 structured frames. Moved here from `AGENTS.md` so the
project index stays lean; behavior is unchanged.

## Attribution model

- **Per-hunk attribution**: each sandbox entry records `agent_id`,
  `tool_name`, `task_id`, `modified_at` (ISO 8601) per hunk — every edit is
  attributable.
- **Multi-agent entries**: keyed by `path::agent_id`; parallel agents can
  edit the same file independently, and the sandbox returns all entries for
  a path so cross-review sees every parallel edit.
- **Summary cache (L1→L3)**: in-memory per-entry stats → Cell-level shared
  cache → persistent `.praxis/sandbox_state.json` (in `data_dir`).
- **Diff views**: `agent` (attribution), `human` (readable), `summary`
  (stats-only), `colored` (semantic colorization). Colors configurable via
  `config/praxis.yaml` `diff.colors` (scheme defined in `config/praxis.yaml`); API:
  `POST /api/v2/diff/colors` get/set/reset.
- **Flow**: agent writes → entry with per-hunk attribution → cross-review
  reads all entries for the file → message shows who changed what, with
  which tool, and when.

## Three-tier topology (2.1)

- **`sandbox_diff.py`** computes three tier-shaped diffs: `build_diff`
  (precise hunks for the build unit), `review_diff` (structured hunks +
  `context_lines` file context + per-hunk attribution for the review
  department), `conflict_diff` (cross-cell conflict level:
  none/warn/block/ping_pong). `POST /api/v2/diff/tier` serves them.
- **Review context**: the review tier attaches `lsp_diagnostics`
  (`l4.lsp.lsp_manager`) and `ast_symbols` (`SymbolSearch.symbols_in_file`
  — top-level functions/classes/methods with line numbers, parent-aware
  method detection) so the reviewer reasons about the change without
  reopening the file. Both degrade to `[]`.
- **Bypass monitor**: `l3/services/review_pipeline.py` consumes a tier-2
  diff; small changes (≤ `config/discovery/review.yaml`
  `max_small_change_lines`, adjustable via `PUT /api/v2/review/threshold`)
  get directed fixes, large ones route back through the Cell-to-Cell
  channel (`L3BBus.route_to_cell` — BFS over registered `l3b-{a}-{b}`
  composites, hop-by-hop delivery of `REVIEW_REWORK` messages) plus an
  async L3A event. External knowledge-base references come from
  `web_search`.
- **Card linkage**: `ci_review._run_review_disposition` runs the review
  pipeline over a card's changed files on completion, merging structured
  dispositions into the report context.

## Structure-aware frames (Phase 1) + tiered compression (Phase 2)

- **Declarative language registry**: `config/discovery/diff_languages.yaml`
  declares languages with `extensions` / `symbol_backend` / `semantic` —
  new languages join by YAML edit, never a code change. The dispatcher
  `l4/sandbox/diff_language.py` routes symbol extraction to the declared
  backend (`python_ast` via stdlib ast; others line-level) and falls back
  to a language-agnostic line diff for unlisted extensions.
- **Structured hunk frames**: `l4/sandbox/diff_codec.py` `encode_hunks` /
  `decode_hunks` — hunk type/semantic dictionary-coded to byte codes,
  original_start rows delta-encoded, payload zlib-compressed. The 8-byte
  plaintext header (frame_type | bitmask | threshold_score | hunk_count)
  lives in L1 `l1/kernel/diff_frame.py` so the L3 bypass monitor and the
  L4 codec share one wire format (exported via kernel `__all__`).
  `review_pipeline.dispose(frame=...)` reads the header hunk_count without
  decompressing — the bypass fast path.
- **Tiered compression**: L2 review frames use the shared Zstd dictionary
  (`l4/sandbox/diff_dict.py`, trained from `diff_dictionary.samples_dir`
  in `diff_languages.yaml`, persisted to data_dir, magic `PDZ`) when
  zstandard is available, else fall back to zlib (`PD2`); L3 archive
  re-compresses with zstd level 19 (`PDZ19`) before the opaque latin-1 R4
  storage. Everything degrades gracefully — zstandard is an enhancement,
  never a hard dependency.
- **Frontend-heavy persist** (`l4/sandbox/diff_persist.py`, gated by
  `diff.persist.enabled`, frontend-heavy only): ring buffer + fixed-interval
  JSONL flush (`DIFF_PERSIST_FILE` in `paths.py`) + crash recovery
  (`recover()`), ring overflow compresses the oldest diff into R4
  (`fonds="diff", series="stitched"`) and emits `diff_evicted_to_r4`.
