# Configuration System

Praxis uses a **declarative, layered configuration architecture** with auto-discovery.

## File Layout

```
config/
  praxis.yaml              — Main project config (kernel, cell, LLM, gatechain, API, diff, etc.)
  commands.yaml            — L2 Shell command definitions and SubAgent specs
  tools.yaml               — Tool definitions by ring layer (RING_1 / RING_2_5 / RING_3)
  .praxis-rules.md         — Constitution rules (parsed by constitution.py)
  discovery/               — Auto-discovered structural config (overlays params defaults)
    agent_configs.yaml     — Agent roles, clearance, priorities, event types, injection patterns
    build_detectors.yaml   — Build/test framework auto-detection commands
    commits.yaml           — Commit-scan policy (types/scopes/placeholder/branch rules);
                             read directly by scripts/py/commit_scan.py — NOT registered
                             as a boot section (its keys are intentionally unregistered,
                             so boot discovery ignores it with a warning)
    danger_levels.yaml     — Tool danger levels, gate mappings, ring maps
    engineering_debug.yaml — Marker-gated engineering/debug defaults
    providers.yaml         — LLM provider URLs, model names, env vars, IPC sockets
```

## Configuration Layers (lowest to highest priority)

```
 1. params/*.py            — Compile-time defaults (timeouts, limits, thresholds)
    ↓ fallback
 2. config/discovery/*.yaml — Structural configuration (auto-discovered at boot)
    ↓ merge
 3. config/praxis.yaml     — Project-level deployment config (applied by config_handlers)
    ↓ override
 4. .praxis_settings.json  — Runtime overrides (set via API or L2 Shell)
```

### Layer 1: params/*.py

Atomic constants (timeouts, limits, thresholds) defined in eight sub-modules:

| File | Purpose | Example |
|------|---------|---------|
| `kernel.py` | Allocator, sync, process, gatechain, VFS | `ALLOCATOR_DEFAULTS.tokens=4096` |
| `allocator.py` | Token allocation + GC | `TOKEN_GC_INTERVAL=60.0` |
| `gatechain.py` | G1–G5 gate chain defaults | `GATECHAIN_ESCALATION_DANGER=80` |
| `sync.py` | Lock / semaphore / event defaults | `SYNC_EVENT_QUEUE_MAX=256` |
| `agent.py` | Agent roles, terminal, loop, card, scout | `AGENT_LOOP_DEFAULT_TIMEOUT=120.0` |
| `tool.py` | Tool danger, timeouts, rate limits, HTN | `TOOL_BUILD_TIMEOUT=300` |
| `api.py` | API gateway, LLM, network, IPC, env vars | `RPC_SERVER_PORT=42110` |
| `system.py` | Cache, memory rings, data paths, truncation | `LOG_TRUNC_200=200` |

### Layer 2: config/discovery/*.yaml (ConfigDiscovery)

Structural configuration discovered at boot by `l1.kernel.discovery`.

**Registration**: `_init_discovery()` boot step registers a fixed set of
params-derived default sections; `config/discovery/*.yaml` overrides them.
Current registered sections (defaults live in `src/l1/kernel/params/` unless
noted):

`build_detectors`, `test_detectors`, `provider_urls`, `ring_gates`,
`gatechain_danger_levels`, `constitution`, `tool_rates`, `services`,
`skill_dirs`, `shell_aliases`, `shells`, `tool`, `persistence`,
`service_limits`, `engineering_debug`, `automation`, `posture`, `review`,
`departments`, `diff_languages`, `diff_dictionary`, `dvg`, `identities`,
`subagent_specs`, `identity_roles`

YAML files only carry the sections that override the code defaults:

| YAML file | Section names |
|-----------|---------------|
| `agent_configs.yaml` | `skill_dirs`, `shell_aliases` |
| `build_detectors.yaml` | `build_detectors`, `test_detectors` |
| `danger_levels.yaml` | `gatechain_danger_levels`, `ring_gates` |
| `engineering_debug.yaml` | `engineering_debug` |
| `providers.yaml` | `provider_urls` |
| `service_limits.yaml` | `service_limits` |
| `automation.yaml` | `automation` |
| `shells.yaml` | `shells` |
| `posture.yaml` | `posture` |
| `review.yaml` | `review` |
| `departments.yaml` | `departments` |
| `diff_languages.yaml` | `diff_languages`, `diff_dictionary` |
| `identity_roles.yaml` | `identities`, `identity_roles` |
| `subagent_specs.yaml` | `subagent_specs` |
| `dvg.yaml` / `tool_registry.yaml` | per-tool dynamic declarations (read by boot steps, not boot sections) |

**Adding new values**: Simply add new keys to the appropriate YAML file. No code changes needed.

```yaml
# Example: adding a Go build detector to build_detectors.yaml
build_detectors:
  go: {cmd: [go, build]}
```

### Layer 3: config/praxis.yaml

Main deployment configuration. Handlers registered in `config_loader.py`:

| Section | Handler | Loads into |
|---------|---------|------------|
| `kernel` | `cfg_kernel` | SettingsCenter |
| `cell` | `cfg_cell` | SettingsCenter |
| `llm` | `cfg_llm` | SettingsCenter |
| `diff` | `cfg_diff` | SettingsCenter + immediate color scheme |
| `constitution` | `cfg_constitution` | In-memory action sets |
| `gatechain` | `cfg_gatechain` | SettingsCenter |
| `card_gate` | `cfg_card_gate` | CardGate instance |
| ... | ... | ... |

### Layer 4: .praxis_settings.json

Runtime overrides persisted automatically. Modified via:

```
POST /api/settings     # set a key
L2 Shell /settings     # view/modify settings
```

## Per-executor Model Specs (`model_spec`)

`config/praxis.yaml` section `model_spec:` configures model / context /
reasoning strength per executor. Resolution cascade in
`ModelService.resolve_dict(spec_name)` (higher wins):

```
1. overrides (per-call, e.g. spec.model_config)
2. model_spec.{name}            (exact spec, e.g. model_spec.scout.temperature)
3. model_spec.{prefix}.defaults (platform defaults, e.g. model_spec.scout.defaults.*)
4. llm.*                         (global llm section)
```

Supported executor spec names and their consumers:

| spec_name | Consumer | Default |
|-----------|----------|---------|
| `scout` | Scout pool (`scout.py`) | 2048 tokens / 0.3 temp |
| `l3a` | L3A session main model | 4096 tokens / 0.7 temp |
| `l3a_subagent` | L3A subagent pool (`l3a/subagent.py`) | 2048 / 0.3 |
| `subagent` | Cell SubAgent (`subagent_task.py`, spec.model_spec) | 2048 / 0.3 |
| `r4_agent` | R4 archive agent (`r4_agent.model_spec`) | 2048 / 0.3 |

Keys per spec: `max_tokens`, `temperature`, `reasoning_effort`
(`none|low|medium|high|xhigh|max` — modern models allocate reasoning tokens
adaptively server-side; effort is a behavioral signal, not a strict
budget), `thinking_budget` (legacy token budget, honored only by providers
that expose it: older Anthropic `budget_tokens`, Gemini `thinkingBudget`;
filtered out by capability probing on GPT-5.x / Claude Opus 5+ / DeepSeek
V4). `model` is omitted by default and inherits `llm.model`; set it
per executor to diverge.

Runtime override (persisted to `.praxis_settings.json`):

```
PUT /api/v2/model-spec/{name}   {"temperature": 0.5, "reasoning_effort": "medium"}
GET /api/v2/model-spec          # list resolved specs
```

### Named strategy packs (runtime switching)

`model_spec.strategies` in praxis.yaml defines named packs that switch an
executor's model/context/reasoning profile at runtime:

```yaml
model_spec:
  strategies:
    fast:     {max_tokens: 2048, temperature: 0.3, reasoning_effort: none,   thinking_budget: 0}
    balanced: {max_tokens: 4096, temperature: 0.5, reasoning_effort: low,    thinking_budget: 2048}
    deep:     {max_tokens: 8192, temperature: 0.7, reasoning_effort: high,   thinking_budget: 8192}
```

API:

```
PUT    /api/v2/model-spec/{name}/strategy  {"strategy": "deep"}     # apply pack (immediate)
GET    /api/v2/model-spec/{name}/strategy                           # current strategy + overrides
DELETE /api/v2/model-spec/{name}/strategy                           # restore defaults
PUT    /api/v2/model-spec/strategy/apply  {"strategy": "deep", "specs": ["l3a", "scout"]}  # batch; specs: ["all"]
```

Applied packs write the exact layer (`model_spec.{name}.{key}`, L3,
persisted), which outranks the executor defaults in the resolve cascade.

Notes:

- **Clamping**: resolved values are clamped to `think.max_reasoning` /
  `think.max_budget` (same ceilings as Cell peer agents); a clamped value
  logs a warning. Set `enabled: false` on a strategy pack to forbid it at
  runtime (`apply` then fails with "unknown or disabled strategy").
- **Phase/executor strategy**: `CardPhase.strategy` (via cardwrite phase
  dicts) and `SubAgentSpec.strategy` attach a named pack to a card phase or
  a subagent spec — opusplan-style stage-level reasoning switching.
- **thinking_budget semantics**: only honored by providers that expose a
  user-defined thinking budget (Anthropic `budget_tokens`, Gemini
  `thinkingBudget`); OpenAI/DeepSeek ignore it via capability filtering.

## Kernel settings facade (`src/l1/kernel/settings.py`)

Kernel code reads settings through this module — it never imports L3. The
facade is dependency-inverted: the authoritative `Settings` instance lives
in `l3.config.settings_adapter` and is **injected at boot** via
`set_settings_provider()`; before injection (standalone kernel use, L1-only
tests) a pure kernel fallback backed by `DEFAULTS` answers.

```python
# src/l1/kernel/settings.py
DEFAULTS                      # dict of ~50 dotted keys (see below)
set_settings_provider(s)      # inject the authoritative Settings (L3) at boot
get_settings()                # current Settings (fallback or injected)
reset_settings()              # clear the injected provider (testing)
inject_enabled()              # whether system-prompt injection is on
```

`DEFAULTS` covers the dotted keys consumed by kernel/L3 callers, grouped:

| Domain | Example keys |
|---|---|
| allocator / swapper / syscall | `l1.kernel.allocator.tokens=4096`, `l1.kernel.swapper.interval=30.0`, `l1.kernel.syscall.audit_max=5000` |
| cell / card | `cell.terminal.workers=4`, `cell.terminal.poll=0.05`, `cell.card.timeout=30.0` |
| llm / device | `llm.provider="ollama"`, `llm.model`, `llm.max_tokens=2048`, `device.rate_limit_default=10` |
| persistence / memory | `persistence.enabled=True`, `memory.graph.enabled=False`, `memory.compaction_mode="deterministic"` |
| prompt injection switches | `prompt.inject.profile/constitution/skills/verification/memory/identity` (all `True`) |
| departments / l3a secretary | `departments.enabled=False`, `l3a.secretary.enabled=True` |
| l3a compression (3.1) | `l3a.digest.enabled`, `l3a.tool_result.enabled`, `l3a.sensitive.enabled`, `l3a.compression_guard.recursion_threshold` |
| ci review | `ci.review.enabled=True`, `ci.review.llm_review=False`, `ci.control.api.writable=True` |
| shells / engineering debug | `shells.enabled=True`, `shells.default="terminal"`, `engineering_debug.mode="auto"`, `engineering_debug.marker_file=".praxis/debug_mode.flag"` |

The compression defaults mirror `l1.kernel.params.system` constants
(`DIGEST_ENABLED_DEFAULT`, `TOOL_RESULT_OFFLOAD_*`, `SENSITIVE_DETECT_*`,
`COMPRESSION_*`); the LLM model default comes from
`l1.kernel.params.api.DEFAULT_MODEL_OLLAMA_CODER`. Callers reference the
dotted keys via `get_settings().get("domain.key", default)`; runtime
writes from the API/L2 (`setting` command, `/api/v2/settings`) persist
through the injected provider to `.praxis_settings.json`.

## Reading Configuration in Code

```python
from l1.kernel.discovery import get_config

# Read from discovery (falls back to params defaults)
detectors = get_config("build_detectors") or {}

# For atomic params constants, import directly from params
from l1.kernel.params.tool import TOOL_BUILD_TIMEOUT
```

## Prompt Template Overrides (`prompts`)

Prompt templates are registry-driven: built-in defaults live in
`src/l1/kernel/prompts.py` (`_DEFAULTS`), and `config/praxis.yaml`'s
`prompts:` section overrides them at boot. Each override replaces the
built-in template of the same dot-notation key (priority:
override > built-in > caller-passed default).

```yaml
# config/praxis.yaml
prompts:
  verifier.self_check: "Custom verification prompt..."
  agent_loop.system: "You are an agent in Praxis. Task: {task}"
```

Loading chain: `config_loader` (`cfg_prompts` handler) →
`l1.kernel.prompts.load_prompt_overrides()` → `get_prompt(key, default)`
→ consumers (agent_loop_context, verifier, review, ...) → LLM context
injection via `agent_loop_context._inject_extra_context`.

- Use `python -m l3...` / API `GET /api/v2/engineering-debug/prompts` or
  `list_prompts()` to enumerate available keys and their source.
- Prompt strings are data (registry-managed), not params constants:
  they stay in `prompts.py`/praxis.yaml rather than `params/`.

## Engineering Debug Mode (`engineering_debug`, 3.5)

Engineering diagnostics are configured declaratively but require two
independent gates at runtime: an explicit developer identity (or ring >= 3)
for mutating controls, and a regular marker file for the effective mode. The
default deployment configuration is fail-closed:

```yaml
engineering_debug:
  mode: auto                         # auto | on | off
  marker_file: .praxis/debug_mode.flag
  marker_required: true
  verbose_logging: true
  prompt_monitor: true
  input:
    enabled: false
    capture_content: false            # must remain false; raw input is never stored
```

`config/discovery/engineering_debug.yaml` supplies the same structural
defaults. `config/praxis.yaml` overrides them at deployment scope, and
`.praxis_settings.json` stores API/L2 runtime changes. Relative marker paths
are resolved from the deployment root; only a non-symlink regular file
satisfies the marker check.

| Requested setting | Marker | Effective mode | Behavior |
|-------------------|--------|----------------|----------|
| `auto` | absent | production | ordinary logging and prompt sources |
| `auto` | present | engineering | verbose logging, prompt monitor, and configured debug controls |
| `on` | absent | production | request rejected; marker cannot be bypassed |
| `on` | present | engineering | same linked controls as `auto` with a marker |
| `off` | either | production | explicit fail-closed lock |

The manager caches marker checks using
`ENGINEERING_DEBUG_MARKER_RECHECK_INTERVAL` and applies logging, prompt
monitor, and input-provider effects only on transitions. This keeps the
production path bounded and prevents repeated setup work on status reads.

### Developer prompt overlays

Engineering-only prompt overlays are distinct from the deployment `prompts:`
section. They are persisted under
`engineering_debug.prompt_overrides.<key>`, versioned by the L1 prompt
registry, bounded by `ENGINEERING_DEBUG_PROMPT_MAX_CHARS`, and rollbackable.
Production mode ignores these overlays and restores the built-in/deployment
prompt source when engineering mode ends. Overlay writes and rollback require
the same developer/ring-3 gate as mode changes.

### Input activity monitoring

`engineering_debug.input.enabled` is an additional opt-in. The L3 controller
uses the L1 `InputActivityPort` and reports only aggregate keyboard/pointer
state, idle duration, provider source, and permission. It does not collect key
values, pointer coordinates, or raw events. The default no-op adapter keeps
unsupported hosts inert; a platform adapter may be supplied without changing
the configuration or API contract.

### API and L2 controls

| Surface | Endpoints / commands |
|---------|----------------------|
| API | `GET/PUT /api/v2/engineering-debug` |
| API | `GET/PUT /api/v2/engineering-debug/prompts`; `POST .../prompts/rollback` |
| API | `GET/PUT /api/v2/engineering-debug/input` |
| L2 | `/debug-mode status\|auto\|on\|off\|reset` |
| L2 | `/debug-input status\|on\|off` |

Mode transitions emit an `engineering_debug_mode_changed` event to EventBus,
ReferenceChannel, and StatsCenter. Observability and input paths are
side-channels: failures degrade to no-ops and do not alter the main card or
agent flow.

## ConfigDiscovery Architecture

```python
src/l1/kernel/discovery.py
  register(name, defaults)       # Register a config section with Python-side defaults
  register_discovery_dir(path)   # Add a directory to scan for YAML snippets
  discover()                     # Scan YAML files and merge into registry
  get_config(name, default)      # Read merged config
  get_source(name, default)      # Read originally registered defaults only
  set_config(name, key, value)   # Runtime override
  reset()                        # Reset to defaults (for testing)
```

Boot sequence: `load_constitution → init_discovery → load_config → ...`
