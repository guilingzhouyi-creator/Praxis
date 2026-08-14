# Related Work — Praxis as an Agent Mini-Nation

Status: baseline research for the organizational-evolution phases (identity
binding, HTN-B decomposition, department division, L3A-C secretary).

This document fixes the design rationale and prior-art mapping for the
"agent mini-nation" architecture: a persistent, constitution-bound
multi-agent organization that serves a single sovereign (the user), whose
natural-language intent is the "national will" propagated through a
hierarchical task network (HTN-A/B/C) with structured communication at
every hop. It records the evidence gathered on 2026-08-10 so later design
reviews can cite it instead of re-searching.

## 1. Architecture thesis

```
user natural-language intent  ←  sovereign will (supreme, traceable via trace_id)
  └─ NOMOS Constitution (.praxis-rules, highest authority, self-binding)
  └─ CentralController.process_intent   ←  decision hub
  └─ HTN-A (cross-Cell intent decomposition) → HTN-B (chain routing) → HTN-C (intra-Cell)
  └─ Cell departments (reader/writer/reviewer/.../tester) + secretary (L3A-C, planned)
  └─ structured communication (ToolSpec params, structured dicts, message pool, L2 cache)
  └─ execution (tools/sandbox) → result back to the user (feedback loop)
```

The analogy is organizational cybernetics, not governance of humans: states
are the largest organizational designs humans have built, so their control
structure (constitution, ministries, secretariat, promotion-by-merit,
audit) is the best-practice library for durable agent organizations.

## 2. Organizational cybernetics — the theoretical foundation

- **Viable System Model (VSM)** — S. Beer. Any viable organization needs:
  System 1 (operational units), System 2 (coordination), System 3
  (operational control) + System 3* (audit), System 4 (intelligence),
  System 5 (policy). Praxis maps: Cell departments = S1, L3B bus/message
  pool = S2, CentralController = S3, cell_cross_review = S3*, R4/R5 memory
  evolution = S4, NOMOS Constitution = S5.
- **Project Cybersyn** (Chile 1971–1973, Stafford Beer). The only full-scale
  national real-time control implementation: Cybernet telex network,
  Cyberstride Bayesian monitoring, CHECO economic simulator, Opsroom.
  Key mechanisms that prefigure Praxis:
  - **Algedonic escalation**: unresolved issues rise one level at a time
    until resolved → the L3A-C secretary / decision-hub reporting ladder.
  - **Horizontal coordination**: factories coordinate peer-to-peer, state
    intervenes only when they cannot resolve → single-Cell egalitarian
    operation vs. department division.
  Terminated by the 1973 coup; control-theoretic, not LLM-agent.

## 3. State-scale AI implementations (operating, not simulation)

- **City Brain** (Alibaba, Hangzhou 2016–). Urban operating system:
  cognition → optimization → decision → intervention; global cognition /
  machine learning / global-optimal coordination metrics. Production at
  city scale (traffic, policing, fire control), adopted in multiple Chinese
  cities and Kuala Lumpur. City-level (polity) operation, but no department
  division or will-propagation organization model.
- **Liberland** (2024–2026). AI-native micro-nation: blockchain governance
  + AI agents (Claude/Codex/Hermes) assisting officials, Ayooni
  (governance-support AI), λLex (computable governance language), ministry
  structure. Closest "nation-shaped AI governance" but AI is advisory, not
  the operating subject.

## 4. Multi-agent organization prior art

- **MetaGPT** (SIGIR 2023). Virtual software company: SOP assembly line,
  roles (PM/Architect/Engineer/QA), publish-subscribe message pool,
  role-specific interest filtering. Structured artifacts (PRD/interfaces/
  data structures) instead of free dialogue. Closest to "software entity +
  QA department" but static, project-based.
- **ChatDev** (ACL 2024). Role-playing software company; communicative
  dehallucination to reduce cross-role misunderstanding.
- **FIRM Protocol** (GitHub, 2025–2026, ~15k lines, 12 layers).
  Self-evolving autonomous organization runtime: Hebbian authority (earned,
  not assigned), role fluidity, **threshold tiers (≥0.80 propose / ≥0.60
  vote / ≤0.30 probation / ≤0.05 termination)**, hash-chained responsibility
  ledger, constitutional governance with two invariants (human kill switch;
  cannot erase own evolution), federation between organizations. The
  threshold-promotion mechanism is the direct precedent for the planned
  L3A-C capability-upgrade gate. Governs WHO may act; does not route HOW
  tasks flow (complementary to Praxis).
- **HALO** (arXiv, 2025). Three-layer reasoning stack (planning agent →
  role-design agents that dynamically instantiate role-specific agents with
  role-specific system prompts → inference agents) + MCTS workflow search.
  Prefigures identity-binding + HTN hierarchy inside a single task.
- **Anthropic multi-agent research system / CrewAI hierarchical**.
  Orchestrator/triage/worker patterns — the "secretary/router" role.

## 5. Structured communication evidence (2024–2026)

The thesis that LLM agents should communicate via structured information
rather than free text to reduce ambiguity is confirmed by:

| Source | Finding |
|---|---|
| TalkHier (Sony, arXiv:2502.11098, 2025) | "Talk Structurally, Act Hierarchically": structured protocol (messages + intermediate outputs + background info) beats AgentVerse/o1/ReAct; criticizes "disorganized, lengthy text-based communication" |
| Chain-of-Agents (Google, ICLR 2025, arXiv:2406.02818) | Worker chain passes structured "communication units" to a manager; feeding all/partial units to the manager *hurts* performance — communication must be structurally filtered (supports domain-directed transport) |
| GPTSwarm (ICML 2024) | Agents as optimizable graphs: nodes = LLM calls, edges = structured information flow; recursive composite graphs = inter-agent hierarchy |
| OPTiMACS (2025) | "Natural-language ambiguity is amplified in multi-turn multi-agent scenarios"; message-representation selection as a learnable MDP |
| Why do AI agents communicate in human language? (arXiv:2506.02739, 2025) | NL semantic space is structurally misaligned with LLM vector spaces → information loss / behavioral drift; calls for native structured communication |
| Five Ws of Multi-Agent Communication (TMLR 2026) | Unified survey (WHO/WHOM/WHAT/WHEN/WHY); structured/symbolic protocols as the design mainstream |
| Interoperability protocols (arXiv:2505.02279, 2025; OSSA 2026) | MCP/ACP/A2A/ANP JSON-RPC standards; OSSA identifies the "contract gap": portable identity, declarative capabilities, governance metadata — exactly the Phase-1 identity-binding scope |
| ProtocolBench (OpenReview 2025) | Protocol choice affects task time by up to 36%; hybrid protocol deployments beat homogeneous by ~6.6% (supports Praxis layered transports) |
| Latent communication (2026 survey) | Frontier moving beyond NL: KV-cache / latent-space communication (KVComm, LatentMAS, Q-KVComm, LRAgent, RelayCaching, …) — the limit case of "structured" |

Praxis has always communicated structurally: `ToolSpec` parameter schemas,
uniform `{"success": bool, "error": str}` returns, Card structured fields
(intent/domain/nature), per-hunk structured sandbox diffs, `IPCMessage`,
task tables, the message pool, and `trace_id` context propagation.

## 6. Population-scale simulations (not operating systems)

- Stanford "Generative Agent Simulations of 1,000 People" (2024, 85% survey
  replication), AgentSociety (10k agents / 5M interactions, 2025),
  GenSim (2024). These simulate societies for social science; they do not
  operate as durable organizations.

## 7. Mapping to the existing Praxis skeleton

Already present: identity routing (role/prompt_key/cell_id), unified prompt
registry (prompts.py + praxis.yaml overrides), bounded context injection
(LOOP_*_BUDGET constants), per-Cell skill white-list (cell_skill_map),
territory/domain mapping (TERRITORY_MAP → role_for_domain), HTN-A/B/C
three-tier scaffolding (htn_a.py, l3b.py, AGENT_ROLE_MAP), L3B chain
topology + L2 cache routing matrix (read_prev_cache / cache_search /
dispatch_to_next), message pool (l3b_message_pool), cross-review
(cell_cross_review), decision hub (CentralController coordinator),
constitution engine (.praxis-rules, 64 rules, highest authority),
trace_id observability.

Planned increments (phases): identity binding submodule (Phase 1),
HTN-B route_subtask decomposition (Phase 2, currently TODO in l3b.py),
department division + tester role + cell-count threshold (Phase 3),
L3A-C secretary + capability-threshold peer upgrade (Phase 4).

## 8. Design implications and risks

- Constitution gate precedes will execution (self-binding sovereign).
- Department walls (L3B reads only the preceding Cell's L2 cache) are a
  deliberate anti-information-overload measure (MetaGPT/CoA evidence).
- Threshold promotion must be auditable (FIRM ledger precedent).
- Central-hub single-point risk is bounded by constitution + double-green
  merge gates.
