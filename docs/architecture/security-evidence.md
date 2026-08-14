# L3 — Security Evidence Chain (attack-posture bypass audit)

`l3/tool_system/security_evidence.py` records every attack-posture event as
deterministic, tamper-evident evidence chains and analyzes them into
verdicts. It answers "was this offensive use *warranted*?" with a
queryable, verifiable record — not a log line that can be argued away.

## Why

Three posture levers can each weaken gate enforcement:

| Lever | Trigger | Risk |
|-------|---------|------|
| Attack posture | `security-test` mode | G4 full-power grants for high-danger tools |
| Soft bypass | `set_offensive_policy(False)` | offensive skills authorized without confirmation |
| Downgraded harness | minimal harness mode | G4 auto-approves instead of blocking |

The chain correlates each lever flip (a `CHANGE`/`BYPASS` record) with the
gate decisions that follow it, so an audit answers two questions: did the
posture change happen, and were the decisions that rode on it justified?

## Chain model

- **Kinds**: chains are keyed by why they opened — `attack`
  (`security-test` mode), `policy-bypass` (offensive policy disabled),
  `downgrade` (minimal harness), plus the implicit **`ambient`** chain.
- **Follow-open semantics**: a recorded decision attaches to the newest
  open chain in posture order (`attack` → `policy-bypass` → `downgrade`);
  with none open, it lands on the *ambient* chain. Gate noise in productive
  posture never pollutes an attack chain.
- **Lifecycle**: `begin_chain(kind)` opens a chain (reusing an open one of
  the same kind); `close_open(kind)` / `close_chain(id)` seal it — restoring
  productive posture closes the open attack chain. Sealed chains stay
  queryable; new records go elsewhere.
- **Idempotence + cleanup**: closing an already-closed chain is harmless;
  the in-memory index evicts the oldest chains/evidence beyond the caps.

## Evidence point

One append-only JSONL row per decision:

| Field | Meaning |
|-------|---------|
| `chain_id` | owning chain (`ch_` + 12-hex suffix) |
| `evidence_id` | `ev_` + 12-hex suffix |
| `ts` | epoch seconds |
| `phase` | where it happened (`g4`, `constitution`, `policy`, `harness`, `injection`, `use_skill`) |
| `gate` | the gate that decided (`g4`, `posture_gate`, `posture_use`, `posture_injection`, `harness_mode`, `offensive_policy`) |
| `decision` | vocabulary below (stable strings `DECISION_*`) |
| `target` | tool / skill / mode the decision is about |
| `source` | origin (`api`, `shell`, `use_skill`, `metric`, `policy`, …) |
| `tags` | details (`nature: offensive`, `enabled: false`, …) |
| `raw` | bounded JSON snapshot (truncated to `EVIDENCE_CHAIN_RAW_MAX`) |

Decision vocabulary: `CHANGE` (posture/harness/policy switched),
`ALLOW` / `BLOCK` / `WARN`, `FULL_POWER` (G4 escalation),
`AUTO_APPROVED` (harness auto-approval), `BYPASS` (soft bypass won).

**Best-effort guarantee**: every public entry is wrapped — a failing
recorder logs and returns, it never breaks the protected path (mode
switch, gate decision, tool execution).

## Fixity

Each row stores the previous row's sha256 (`prev_hash`) plus its own
canonical hash (`raw_hash`, `hash_prefix`). `verify_chain(chain_id)`
replays the chain over restart-reload and reports `checked/ok/bad` — a
tampered field in *any* row (even an early one, because the hash chain
propagates) is detected. Truncation length: `EVIDENCE_CHAIN_HASH_TRUNC`
(16 hex). Evidence ids use `HASH_TRUNC_MEDIUM`.

## Verdicts

`analyze(chain_id)` projects a chain onto one of three verdicts; every
finding references the exact `evidence_id` of the causing row:

| Verdict | Derivation |
|---------|------------|
| `clean` | no escalation / bypass / offense use; block-only |
| `warranted` | `FULL_POWER` under attack posture, or `ALLOW` on an offense-posture skill (nature-authorized) |
| `bypassed` | a `BYPASS` decision or harness `AUTO_APPROVED` present |

A bypassed chain carries `bypass`-kind findings anchoring each `BYPASS`
decision.

## Metric bridge (L1 → L3)

L1 cannot import L3; boot injects `constitution.set_metric_sink()`, which
now feeds *both* StatsCenter `security.*` counters and the evidence chain
via `record_from_metric()`:

| Metric | Evidence point |
|--------|----------------|
| `security.gate.g4.full_power` | `phase=g4` `FULL_POWER` |
| `security.gate.g4.auto_approved` | `phase=g4` `AUTO_APPROVED` |
| `security.gate.g4.blocked` | `phase=g4` `BLOCK` |
| `security.gate.skill_use.blocked` | `phase=constitution` `BLOCK` |

Unknown `security.*` metrics are ignored; bridge failures never raise.

Additionally, the L1 event-bus `security_policy_change` signal (emitted by
`SkillManager.set_offensive_policy`) is observed through an idempotent
listener (`ensure_listener`, attached at boot) which records a
`policy-bypass` chain + `BYPASS`/`CHANGE` evidence — soft-bypass switches
are visible even though the policy module is L1-side.

## Persistence

`data_dir/security_evidence.jsonl` (`SECURITY_EVIDENCE_FILE`; overridable
via `PRAXIS_SECURITY_EVIDENCE_PATH` for tests). Append-only writes;
reload tails the file (`EVIDENCE_CHAIN_RELOAD_LINES`); in-memory index caps
(`EVIDENCE_CHAIN_MAX_CHAINS` 64, `EVIDENCE_CHAIN_MAX_EVIDENCE` 512) ejects
the oldest. Deterministic, no LLM involved.

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v2/security/evidence/chains` | chain index with verdicts + open/closed state |
| `GET` | `/api/v2/security/evidence` | query evidence points (`chain_id`, `skill`, `phase`, `decision`) |
| `GET` | `/api/v2/security/evidence/report` | markdown report (timeline + findings + verdict + fixity) |

Callers inside the loop use the module surface instead: `begin_chain`,
`record`, `record_evidence` (best-effort), `record_from_metric`,
`query_evidence`, `search`, `report`, `verify_chain`, `analyze`.

## Relation to other systems

- **Security mode / harness / policy** write the `CHANGE`/`BYPASS` evidence
  via `record_evidence` (`security_mode.py`, `harness.py`, `_skills.py`).
- **G4/constitution** reach the chain through the L1 metric sink (above) —
  one-way, best-effort.
- **Bus**: the same `security.*` counters already flow to StatsCenter;
  evidence is a second, append-only consumer (see `l3-bus.md`).
