# Engineering Debug Mode — Code Review (2026-08-16)

> Scope: uncommitted engineering-debug feature on `feature/engineering-debug-mode`
> (worktree `praxis-engineering-debug`, base `aba0148`). 43 files: 35 tracked
> modifications (+630/−44) + 8 untracked new files. Reviewed read-only from the
> GPT review-docs worktree; the source worktree was not modified.
> Verdict: **APPROVE WITH P1 FIXES** — no P0 findings.

## 1. What was reviewed

| Area | Files |
|---|---|
| Core manager | `systems/python-reference-runtime/l3/tool_system/engineering_debug.py` (469 L) |
| Input privacy controller | `systems/python-reference-runtime/l3/tool_system/input_activity.py` (176 L) |
| Port abstractions | `systems/python-reference-runtime/l1/kernel/ports/service.py` (InputActivityPort), `types.py` (InputActivitySnapshot), `__init__.py` exports |
| Params constants | `systems/python-reference-runtime/l1/kernel/params/system.py` (11 `ENGINEERING_DEBUG_*`) |
| L1 prompt registry | `systems/python-reference-runtime/l1/kernel/prompts.py` (set/get/restore/clear override + versioning) |
| L3 wiring | `prompt_monitor.py`, `boot/discovery.py`, `boot/lifecycle.py`, `config_handlers*.py`, `config_loader.py`, `settings_center.py` |
| L4 API | `api_handlers_engineering_debug.py`, `api_routes.py` (7 routes), `api_endpoints.py`, handler class wiring |
| L2 Shell | `commands/engineering_debug.py` (`/debug-mode`), `commands/input_activity.py` (`/debug-input`) |
| Config | `config/discovery/engineering_debug.yaml`, `config/praxis.yaml`, `config/commands.yaml`, 4 locale files |
| Docs | `docs/architecture/{README,l1-kernel,l3-cell-os,l3-prompt-architecture}.md`, `configuration/overview.md`, `llms*.txt` |
| Tests | `tests/l3/tool_system/test_engineering_debug.py` (11 tests), `test_input_activity.py` (2 tests) |

## 2. Design assessment — sound

- **Marker hard gate**: `.praxis/debug_mode.flag` (regular file, symlinks rejected)
  is the activation boundary; `auto` defaults to production without it, and an
  explicit runtime `on` still refuses without the marker (fail-closed).
- **Authorization**: every write path (`set_mode`, prompt set/rollback, input
  enable) requires developer role or ring ≥ 3 via `_authorize()`.
- **Privacy by construction**: input monitoring only keeps aggregate
  keyboard/pointer state; `capture_content` is hard-coded `False` in the
  status surface — no raw input is ever retained.
- **Prompt overlays with baseline restore**: `_load_prompt_overrides` snapshots
  the pre-overlay registry state (`_prompt_baseline`) and `_restore_prompt_overrides`
  rolls back on mode exit — no leakage between debug and production runs.
- **Effects idempotence**: `_effects_signature` short-circuits repeated
  transitions; marker re-checks are cached on `ENGINEERING_DEBUG_MARKER_RECHECK_INTERVAL`.
- **Observability**: transitions publish to event bus + reference channel +
  metrics center (all best-effort).

## 3. Convention compliance — passed

| Rule (AGENTS.md) | Status |
|---|---|
| Magic numbers in `params/` | ✅ 11 constants in `params/system.py` |
| New kernel modules exported in `__init__.py` `__all__` | ✅ `InputActivityPort` / `InputActivitySnapshot` |
| Config defaults registered in `kernel/settings.py` `DEFAULTS` | ✅ (see P1-2) |
| Test singleton resets in `tests/conftest.py` `_RESETS` | ✅ `reset_engineering_debug` / `reset_input_activity` |
| Cross-layer imports allowlisted | ✅ `test_layer_imports.py` +2 entries |
| API routes kebab-case, manifest registered | ✅ `/api/v2/engineering-debug*` (GET/PUT/POST) |
| i18n across 4 locales | ✅ `usage_debug_mode` / `usage_debug_input` |
| Architecture docs synced in same change | ✅ README/l1/l3/overview/llms refreshed |
| English comments/docstrings | ✅ |
| `RLock` for re-entrant critical sections | ✅ |
| `except Exception` (no bare except) | ✅ |

## 4. Findings

### P0 — none

### P1 — fix before merge

1. **Status `capture_content` hard-coded (privacy contract drift risk)** —
   `engineering_debug.py:292` and `input_activity.py:102` report
   `capture_content: False` unconditionally while
   `engineering_debug.input.capture_content` exists in config. If the config
   key is ever flipped on, the status surface still reports `False`, hiding the
   real behavior. Either read the config key or pin it with an explicit comment
   ("privacy invariant — never enabled in this build").
2. **Triple-declared defaults (drift surface)** — `engineering_debug.*`
   defaults now live in `params/system.py` (source), `kernel/settings.py`
   `DEFAULTS`, `settings_center.py` `_DEFAULTS`, AND
   `config/discovery/engineering_debug.yaml`. Four copies of the same truth.
   The discovery registration is params-driven (correct), but the two settings
   registries re-hardcode literals. Recommend: settings layers read from params
   or a consistency test pins them together.
3. **Input enable persists even when provider start fails** —
   `input_activity.py:141-151`: `started = self._provider.start()` result is
   reported but `_enabled` and the persisted setting stay `True` when the
   provider returns `False` (e.g. unavailable platform), leaving an
   `enabled=True / snapshot=unknown` inconsistency. Roll back `_enabled` and
   return the failure when `start()` reports `False`.
4. **Silent best-effort emission** — `_emit_transition` catches
   `Exception: pass` on all three channels (event bus / reference channel /
   metrics). Intent is documented, but a `logger.debug` on failure would keep
   the audit trail debuggable without noise.

### P2 — suggestions

1. `_parse_operator_flags` is a private helper in `commands/engineering_debug.py`
   imported cross-module by `commands/input_activity.py` — rename to a public
   helper (or move to a shared `_cmd_util`) to avoid private-name coupling.
2. `engineering_debug.py` at 469 lines mixes manager, module globals and
   helpers — a later split into `manager.py` / `registry.py` is reasonable,
   not required now.
3. `status()` calls `_refresh()` on every read and `_refresh(force=True)` on
   every write — fine at this scale; keep the cache window as the only guard.

## 5. Governance finding (docs, not code)

**Archive = untrack** policy: `.gitignore:114-115` excludes
`docs/design/archive/` entirely (commit `f21dbbd`), and
`docs/notes/随笔/` too. Consequences surfaced during this review:

- The archived review corpus (21 files incl. `praxis-architecture-actual.md`,
  the 1294-line architecture snapshot) exists **only on the main tree disk** —
  invisible to every worktree, CI, and clone. The architecture README's
  "archived at `memories/archives/architecture-v1/` (out of git)" points to a
  path that does not exist anywhere (git or disk).
- "History remains via `git log`" is only half-true: the content survives as
  blobs in deletion commits (`git show <commit>:<path>`), but no index or
  navigation exists for it.
- A doc-reorg plan must decide the archive contract explicitly before touching
  `docs/design/`: (a) keep untrack-archive but add a tracked manifest index,
  (b) re-track as `archive-v2/` with a status marker, or (c) keep the
  directory tracked and mark archived docs with a front-matter banner instead.

## 6. Recommendation

Land the feature after P1-1..3 are addressed (P1-4 optional, P2 discretionary).
The docs-governance question in §5 should be settled by the maintainer before
the docs reorganization proceeds; it changes where "dead" design docs go and
what the top-level docs index must guarantee.
