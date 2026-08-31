# L3 — Tool Layer (78 definitions, 22 handlers + tool system)

The tool layer is what agents can do. 78 tool definitions live in
`config/tools.yaml` (ring/danger/parameters); 22 handler modules in
`l3/tools/` produce structured dicts for the 9-step pipeline;
`l3/tool_system/` (13 files) defines how tools are declared, registered,
gated, and executed (plus the security evidence chain,
`security_evidence.py` — see
[security-evidence.md](security-evidence.md)).

## Tool inventory (by domain)

| Domain | Tools | Notes |
|--------|-------|-------|
| **File** | `_files.py` read_file / write_file / list_dir / edit / copy / delete … | via resource_buffer; the biggest family |
| **Search** | `_search.py` grep / glob / file_search | cross-platform (rg/grep + pure-Python fallback) |
| **Git** | `_git.py` git_commit / git_push / git_status … | |
| **Build** | `_build.py` build_project / test_project / deploy / db_migrate / rollback | detector-command lists (no hardcoded toolchain) |
| **Code** | `_code.py` symbol_search / issue detection | regex scanners |
| **Web** | `_web.py` web_fetch / web_search | urllib + truncation |
| **Package** | `_package.py` pip/npm/apt/cargo install/list | PackageManager service |
| **Terminal** | `_terminal.py` execute_shell | RING_3 approval-gated; cross-platform `ProcessPort.run` |
| **Memory** | `_memory.py` memory_store / memory_retrieve | L3 MemoryManager |
| **Archive** | `_archive.py` archive save/load/query | SQLite fonds/series/ref-code |
| **Config** | `_config.py` config_get / config_set | SettingsCenter |
| **Env** | `_env.py` env_get / env_list / reset_workspace | reset = RING_3 factory reset |
| **Comm** | `_comm.py` ask_user / confirm | L3A awaiting flow, headless degrade |
| **Peer** | `_peer.py` agent_list / agent_heartbeat | IPC keepalive |
| **SubAgent** | `_subagent.py` review (read-only) / deploy (write+approval) / scout (async) | mounts a subagent as one tool |
| **LSP** | `_lsp.py` go-to-def / find-refs / hover | wraps L4 LspManager, Ring 1 read-only |
| **Skill** | `_skills.py` list_skills / use_skill | tag/tool filters |
| **Logging** | `_logging.py` log_info / log_error | per-agent tagged |
| **Deps** | `_deps.py` check_version | importlib.metadata |

## Tool system (how tools are declared and gated)

| Module | Role |
|--------|------|
| `tool_spec.py` | ToolSpec — plugin registration, `tools_*.py` auto-discovery, execution middleware, categories, JSON export |
| `tool_registry.py` | ToolRegistry — MapRegistry-based: mute system, plugins, middleware |
| `tool_policy.py` | 3-layer visibility (handler / LLM context / pipeline) — SESSION > AGENT > ROLE > CELL > GLOBAL; `require_approval` |
| `tool_pipeline.py` | **9-step pipeline**: DVG prerequisites → clearance → approval → rate limit → constitution → GateChain G1–G5 → sandbox → execute → record |
| `tool_params.py` | ParamSpec / ReturnSpec declarations with type validation |
| `tool_mode.py` | global read/write mode (write = all rings, read = Ring 1 only) |
| `tool_config.py` | `tools.yaml`-driven definitions; three-ring integration chain-filter API |
| `dvg.py` | Declarative prerequisite DAG; cycle-safe execution plans for tool admission |

### Cross-runtime projection

`ToolSpec.to_data_only()` is the Python reference serializer for the public
tool contract. It returns detached name/description/category/ring/danger,
gates, parameter, return, parallel-safety, and sandbox fields while excluding
handlers, middleware, plugin state, and arbitrary metadata. The independent
TypeScript L3 projection (`l3/tools/tool-projection.ts`) consumes that shape,
sorts and bounds the registry, and maps provider `tool_call` values to the Rust
`tool.invoke` capability seam. Rust receipts fold back into bounded
`ToolResult` data; neither runtime shares executable tool objects.

### Pipeline (9 steps)

```
ring gate → rate limit → constitution → gatechain G1-G5 → approval policy
→ sandbox (profile-gated) → execute handler → result record → reference channel
```

**Single execution gate (W1.2):** `tool_spec._execute_tool_spec` is PRIVATE —
the registry-level executor runs only inside the pipeline. Every other caller
(L2 shell, MCP, API handlers) enters through the kernel capability seam
(`l1.kernel.invoke_capability`, W6.1) so no path reaches a handler without
clearance/approval/gatechain/sandbox/audit;
`tests/infra/test_single_execution_gate.py` statically forbids direct executor
calls, and LLM engines reject unwrapped specs (`ToolSpec.gated`). Boot is the
only place that connects the seam to the pipeline
(`boot_steps/tools.py::_register_capability_executor` → `invoke_gated`).

**GateChain posture linkage:** when the system posture is full-power attack
(`security.mode=security-test` + detection-bypass confirmed), G4 skips the
L3 review WARN for high-danger tools (`danger >= GATECHAIN_ESCALATION_DANGER`)
but still records the call for the audit trail. The full-power decision and
the G4 bypass are recorded via the injected L1 metric sink
(`security.gate.g4.full_power`) — the kernel never imports L3; boot wires
`set_metric_sink()` (same pattern as the posture provider).

## Config surface

- `config/tools.yaml` — 78 tool definitions by ring layer (danger, params)
- `config/discovery/tool_registry.yaml` — optional runtime definitions using
  the API's `ToolConfig.register_from_dict` path; `deps`/`depends_on` are
  supported, ring/cap checks apply, and handlers stay inside `l3.tools.*`.
- `config/discovery/dvg.yaml` — static tool → prerequisite declarations;
  dynamic dependency edges are restored after boot loading and cycles fail
  closed without taking down the registry.
- Ring tiers: Ring 1 (read-only), Ring 2.5 (write+approval), Ring 3 (danger)

### Runtime registration and DVG admission

`POST /api/v2/tools/register` and boot discovery share one registration path.
Successful registration updates the ToolRegistry, DVG, and G1 whitelist;
`unregister` removes all three references. `execution_plan(name)` exposes a
prerequisites-first plan. A cyclic registration is rejected atomically. The
pipeline uses the plan as an admission check and fails closed on a missing
prerequisite or cycle. It does not silently execute
prerequisite handlers: each tool remains an independently gated call, so side
effects cannot hide behind a composite registration.

Boot rebuilds G1 from the complete registry after static and dynamic loading,
preventing a stale or empty whitelist and keeping hot registration symmetric
with kernel gate cleanup.

## Harness — unified tool-usage control bar

`harness.mode` is the **unified tool-usage control bar** (`params/tool.py`
`HARNESS_PRESETS`): two classes split by a CONTROL LINE (the approval gate),
each level resolving a (skip-table, presentation, toolset) triple that the
pipeline reads in one place (`tool_pipeline.execute`).

| Level | Class | Process steps skipped | Presentation | Toolset |
|---|---|---|---|---|
| `governed` (default) | guarded (above line) | none (full control) | native | all |
| `code` (PTC) | guarded | none | `run_code` (programmatic) | all |
| `semi` | guarded (lowest) | approval, pool (keeps rate) | native | all |
| `minimal` | open (below line) | approval, rate, pool | native | bash + `str_replace_editor` |

- The bottom line (constitution, gatechain, sandbox, reference-channel
  recording) is NEVER skipped in any level — **no control, but still
  recorded** (minimal included).
- `tool_mode` (write/read) stays an independent read/write permission switch
  (ring muting) — orthogonal to the control bar, not merged into it.
- Switching `code` at the harness level syncs the presentation mode to
  `run_code` (`set_harness_mode("code")` → `presentation=code`); other
  levels sync to `native`.

## Integration

- `l3-card-lifecycle.md`: agents execute card steps through these tools.
- `l4-bridge.md`: MCP bridge + WS `rpc` expose tools to frontends.
