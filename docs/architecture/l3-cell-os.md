# L3 — Cell Runtime (SoC components + boot + lifecycle)

A Cell is an agent's "system on a chip": 26 components in
`src/l3/cell/components/` map classic OS hardware onto the agent domain.
Boot brings the machine up; lifecycle takes it down cleanly. The Cell also
hosts the marker-gated engineering-debug control plane, which links
observability and developer prompt controls without changing production card
execution.

## Cell components (the SoC)

| Component | OS analogue | Role |
|-----------|-------------|------|
| `cell_icache.py` | **I-Cache** | instruction cache (LFU eviction): tool definitions, card templates, constitution, territory maps — never flushed to memory |
| `cell_cache.py` | **D-Cache** | L2 shared cache: Hot Ring + Index Chain + KV, TTL; flush/promote to L3 MemoryManager |
| `cell_mmu.py` | **MMU + TLB** | translates territory paths → physical agent id with ring permissions; TLB caches recent translations |
| `cell_pmu.py` | **PMU** | performance counters (cards/tools/cache/bus/token/watchdog), sampled snapshots → MonitorBus |
| `cell_watchdog.py` | **Watchdog timer** | per-agent HEALTHY→UNRESPONSIVE→CRASHED escalation; auto-restart or NMI |
| `cell_interrupt.py` | **Interrupt controller** | 4-priority IRQ (NMI/HIGH/NORMAL/LOW), NMI unmaskable, wraps EventBus |
| `cell_rollback.py` | **Transaction rollback** | checkpoint + file snapshot + sandbox discard + terminal reset |
| `cell_permission.py` | **Capability table** | subagent delegation state machine (DISABLED/CELL_ENABLED/AGENT_GRANTED) + kill switch |
| `cell_state.py` | **Persistent state** | Cell (agents/card_history) save/restore JSON |
| `cell_token_merger.py` | **Accounting** | per-cell token accumulator → TOKEN_USAGE events |
| `cell_cross_review.py` | **Code review board** | blocking wait for peer CROSS_REVIEW_RESP after writes/deletes |
| `cell_convention.py` | **Deliberation policy** | convene() activates deliberation memory; peer agents share the Cell ring |
| `cell_decompose.py` | **Scheduler partition** | decomposes a card into sub-cards routed by territory |
| `cell_execute.py` | **Executor** | `Cell.execute_card()`: raw→card, decomposed slices, snapshot injection |
| `cell_lifecycle.py` | **Power management** | boot/shutdown/emergency/reset/restart mixin |
| `cell_messaging.py` | **IPC** | inter-agent send/read/liveness with mailboxes |
| `cell_monitor.py` | **Health monitor** | rolling event log for L3A queries/visualization |
| `cell_buffer.py` | **Ring buffer** | fixed circular buffer for rollback context / card history / snapshots |
| `cell_agent.py` | **Process manager** | agent register/query/status, mailbox init |
| `cell_types.py` | — | shared dataclasses/enums/protocols |

## Boot (bringing the machine up)

| Module | Role |
|--------|------|
| `boot.py` | main sequence: constitution → kernel services → Cell with 3 peer agents → register with scheduler/IPC/ACB/identity → heartbeat → L3 coordinator |
| `boot_registry.py` | extensible boot-step registry with dependency ordering + timeout |
| `install.py` | first-run/upgrade: schema migration, seed defaults, version marker |
| `lifecycle.py` | unified shutdown: stop intake → persist memory → Ring3 archive → stop daemons → reset singletons → optional disk wipe |
| `wiring.py` | **single source of truth** for port→adapter assembly (wire_defaults / wire_from_config) |

```
boot: install? → constitution → kernel services → Cell+3 agents
      → scheduler/IPC/ACB/identity registration → heartbeat → L3 coordinator
shutdown: stop intake → persist → archive → stop daemons → reset → (wipe?)
```

## Engineering debug control plane (3.5)

`l3.tool_system.engineering_debug` resolves the requested `auto|on|off` mode
against a regular marker file (default `.praxis/debug_mode.flag`). The marker
is rooted at the deployment directory and is a hard gate: `on` is rejected
without it, while `off` always returns to production. A missing marker or a
marker removal therefore fails closed. The manager rechecks the marker on a
bounded interval and emits `engineering_debug_mode_changed` on each effective
transition through EventBus, ReferenceChannel, and StatsCenter.

The transition coordinator links three observability paths:

```
marker + requested mode
          │
          ▼
EngineeringDebugManager
    ├── configured logging level (engineering only)
    ├── prompt monitor + versioned prompt overlay (engineering only)
    └── InputActivityController (engineering + explicit input opt-in)
          │
          └── aggregate transition event → EventBus / ReferenceChannel / StatsCenter
```

Prompt overlays live in the runtime settings namespace
`engineering_debug.prompt_overrides.*`. They are versioned and rollbackable
through the L1 prompt registry, require a developer identity or ring-3
clearance, and are removed from the effective prompt source when engineering
mode ends. Overlay text is bounded by `ENGINEERING_DEBUG_PROMPT_MAX_CHARS`.
The side channel never mutates the normal card or agent flow on monitor,
logging, or persistence failure.

Input activity is deliberately privacy-preserving. `InputActivityController`
uses the L1 `InputActivityPort` and returns only keyboard/pointer aggregate
state, idle duration, provider source, and permission status. It never stores
key values, pointer coordinates, or raw event payloads. Praxis ships a no-op
provider for unsupported platforms and a deterministic fake provider for
tests; a hardware provider can be added behind the same port.

The controls are available over `GET/PUT /api/v2/engineering-debug`, the
prompt and rollback subroutes, and the `/input` subroutes. L2 exposes the
equivalent `/debug-mode` and `/debug-input` commands. Mutating calls require
an explicit developer role or ring >= 3, independently of the marker gate.

### Lifecycle and performance

Engineering-debug and input controllers are reset with the L3 lifecycle, so
shutdown cannot leave verbose logging, monitor hooks, or a provider running.
Marker checks are cached, and side effects are applied only on state/config
transitions; this keeps the production hot path at a status read plus a
bounded cache check. Input snapshots and prompt versions use fixed, primitive
data contracts, leaving a clean seam for a Rust adapter without moving L3
policy or API handling into the native layer.

## Scheduler (5D) — see `l3-scheduler.md`

Time/rate/scope/router/pool scheduling over the ACB — the CPU scheduler of
the Cell SoC. `loop_detectors`, `sequence_monitor`, `think_registry`
provide the safety and quota layers around it.

## Relation

- Card execution (see `l3-card-lifecycle.md`) runs **on** this SoC: MMU
  checks the step's territory, PMU counts it, watchdog guards the agent,
  interrupt delivers events.
- Boot wiring is the shared-file register for port adapters (see
  `cross-cutting.md`).
