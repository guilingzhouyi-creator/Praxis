"""Security evidence chain — chain_id-threaded bypass/attack-posture audit.

Collects evidence for attack-posture switching and the skill/tool gate
decisions that follow (harness mode, security mode, offensive-policy soft
bypass, skill injection, use_skill, GateChain G4, constitution section 9.2),
links every point into an *evidence chain* (reverse-skill Evidence->Finding
model), persists append-only JSONL with per-point fixity hashes (VulnClaw
AgentState style), and analyzes chains into verdicts + findings.

Module layout:
  models.py — decision vocabulary, ChainRecord / EvidencePoint, hashing
  facade.py — module-level singleton + never-raising entry bridges
  core.py   — SecurityEvidence collector (record / query / analyze / report)

Bypass semantics (reference-channel principle): recording is strictly
side-channel — every public entry is wrapped so a failing recorder never
breaks the protected path (mode switch, gate decision, tool execution).

Chain semantics:
  - A chain opens when the operator switches posture: security-test (attack),
    harness minimal (downgrade) or disabling the offensive policy
    (policy-bypass).
  - The ambient chain absorbs any gate evidence recorded while no explicit
    attack chain is open (e.g. G4 blocks in productive posture).
  - Verdicts: ``clean`` (no escalation), ``warranted`` (full_power or
    offense-posture skills used under an authorized nature), ``bypassed``
    (a soft bypass / harness auto-approval won).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections import Counter, deque
from typing import Any

from l1.kernel.params.system import (
    EVIDENCE_CHAIN_ID_PREFIX,
    EVIDENCE_CHAIN_MAX_CHAINS,
    EVIDENCE_CHAIN_MAX_EVIDENCE,
    EVIDENCE_CHAIN_RELOAD_LINES,
    EVIDENCE_CHAIN_REPORT_FINDINGS_MAX,
    EVIDENCE_CHAIN_SEARCH_LIMIT,
    EVIDENCE_ID_PREFIX,
    HASH_TRUNC_MEDIUM,
    SECURITY_EVIDENCE_FILE,
)
from l1.kernel.paths import get_paths

from .facade import (  # noqa: F401 — re-export
    ensure_listener,
    get_evidence,
    record_evidence,
    record_from_metric,
    reset_evidence,
)
from .models import (  # noqa: F401 — re-export
    _METRIC_TO_EVIDENCE,
    DECISION_ALLOW,
    DECISION_AUTO_APPROVED,
    DECISION_BLOCK,
    DECISION_BYPASS,
    DECISION_CHANGE,
    DECISION_FULL_POWER,
    DECISION_WARN,
    DEFAULT_CHAIN_KIND,
    VERDICT_BYPASSED,
    VERDICT_CLEAN,
    VERDICT_WARRANTED,
    ChainRecord,
    EvidencePoint,
    _bounded_raw,
    _ev_from_dict,
    _hash_row,
)

logger = logging.getLogger(__name__)


class SecurityEvidence:
    """Evidence-chain collector: record / query / analyze / report.

    Thread-safe (RLock). Persists append-only JSONL; the on-disk file is the
    durable record, the in-memory rings are the hot query window. A failing
    append never breaks the caller — it degrades to memory-only recording.
    """

    def __init__(self, path: str = ""):
        self._path = path or os.environ.get(
            "PRAXIS_SECURITY_EVIDENCE_PATH", os.path.join(get_paths().data_dir, SECURITY_EVIDENCE_FILE)
        )
        self._lock = threading.RLock()
        self._chains: dict[str, ChainRecord] = {}
        self._chain_order: deque[str] = deque()
        self._window: deque[EvidencePoint] = deque(maxlen=EVIDENCE_CHAIN_MAX_EVIDENCE)
        self._evidence_by_id: dict[str, EvidencePoint] = {}
        self._open_kinds: dict[str, str] = {}  # kind -> chain_id of open chains
        self._load()

    # ── orchestration ──

    def begin_chain(self, kind: str, source: str = "", meta: dict | None = None) -> str:
        """Open (or reuse an already-open) chain of ``kind``; returns the chain_id.

        A repeat call for a kind whose chain is still open is a no-op — one
        open chain per kind.
        """
        kind = str(kind or DEFAULT_CHAIN_KIND)
        with self._lock:
            existing = self._open_kinds.get(kind)
            if existing and existing in self._chains:
                return existing
            chain_id = f"{EVIDENCE_CHAIN_ID_PREFIX}{uuid.uuid4().hex[:HASH_TRUNC_MEDIUM]}"
            self._chains[chain_id] = ChainRecord(chain_id=chain_id, kind=kind, source=source)
            self._chain_order.append(chain_id)
            self._open_kinds[kind] = chain_id
            if meta:
                self.record(
                    phase="chain",
                    gate="",
                    decision=DECISION_CHANGE,
                    target=f"chain:{kind}",
                    source=source,
                    tags={"chain_kind": kind, **(meta or {})},
                    chain_kind=kind,
                )
            self._prune_chains()
            return chain_id

    def record(
        self,
        phase: str,
        gate: str = "",
        decision: str = DECISION_ALLOW,
        target: str = "",
        source: str = "",
        tags: dict[str, str] | None = None,
        raw: dict[str, Any] | None = None,
        chain_kind: str = "",
    ) -> str:
        """Record one evidence point into the chain of ``chain_kind`` and return its chain_id.

        Posture-relevant call sites pass ``chain_kind="attack"`` /
        ``"downgrade"`` / ``"policy-bypass"`` so the point lands in the right
        chain; everything else lands on the ambient chain but stays linked
        through the single append-only file.
        """
        snapshot, raw_size = _bounded_raw(raw)
        fields: dict[str, Any] = {
            "ts": time.time(),
            "phase": phase,
            "gate": gate or phase,
            "decision": decision,
            "target": target,
            "source": source,
            "tags": dict(tags or {}),
            "raw": snapshot,
        }
        full_hash, prefix = _hash_row(fields)
        with self._lock:
            chain_id = self._ensure_chain(chain_kind or "", source)
            ev = EvidencePoint(
                evidence_id=f"{EVIDENCE_ID_PREFIX}{uuid.uuid4().hex[:HASH_TRUNC_MEDIUM]}",
                chain_id=chain_id,
                ts=fields["ts"],
                phase=fields["phase"],
                gate=fields["gate"],
                decision=fields["decision"],
                target=fields["target"],
                source=fields["source"],
                tags=fields["tags"],
                raw=snapshot,
                raw_size=raw_size,
                raw_hash=full_hash,
                hash_prefix=prefix,
            )
            self._append(ev)
            if ev.evidence_id not in self._evidence_by_id:
                self._evidence_by_id[ev.evidence_id] = ev
                self._window.append(ev)
            self._chains[chain_id].evidence_ids.append(ev.evidence_id)
            return chain_id

    def record_from_metric(self, name: str, value: float, tags: dict | None = None) -> str:
        """Translate a security.* metric into evidence (L1 sink choke point)."""
        mapping = _METRIC_TO_EVIDENCE.get(name)
        if mapping is None:
            return ""
        phase, gate, decision = mapping
        t = {str(k): str(v) for k, v in (tags or {}).items()}
        return self.record(
            phase=phase,
            gate=gate,
            decision=decision,
            target=t.get("tool", "") or t.get("target", ""),
            source="sink",
            tags=t,
        )

    def close_chain(self, chain_id: str, reason: str = "") -> dict:
        """Close an open chain (idempotent; returns the chain snapshot)."""
        with self._lock:
            chain = self._chains.get(chain_id)
            if chain is None:
                return {"success": False, "error": f"unknown chain: {chain_id}"}
            if chain.closed == 0:
                chain.closed = time.time()
                chain.reason = reason
                if self._open_kinds.get(chain.kind) == chain_id:
                    self._open_kinds.pop(chain.kind, None)
            snapshot = chain.to_dict()
        # B6: evidence→R5 linkage — record the closed chain as an evidence
        # edge in the memory graph (non-blocking, never raises).
        try:
            from l3.memory.memory_graph import MemoryGraph

            _mg = MemoryGraph()
            if _mg._enabled and chain_id:
                _mg.add_evidence_edge(
                    from_id=chain_id,
                    to_id=snapshot.get("source") or chain_id,
                    weight=float(len(snapshot.get("points", [])) or 1),
                    created_by="security_evidence",
                )
        except Exception:
            pass
        return {"success": True, **snapshot}

    def close_open(self, kind: str = "") -> dict:
        """Close all open chains (optionally filtered by kind) — e.g. a
        control-restoring switch (productive / governed) ends an attack chain."""
        closed: list[str] = []
        with self._lock:
            for chain_id in list(self._open_kinds.values()):
                chain = self._chains.get(chain_id)
                if chain and (not kind or chain.kind == kind):
                    chain.closed = time.time()
                    closed.append(chain.chain_id)
            if kind:
                self._open_kinds.pop(kind, None)
            else:
                self._open_kinds.clear()
        return {"success": True, "closed": closed}

    # ── queries ──

    def chains(self, limit: int = 0) -> list[dict]:
        """Chain index, newest first; each row carries verdict + evidence count."""
        with self._lock:
            rows = [self._chains[cid].to_dict() for cid in self._chain_order]
            limit = limit or EVIDENCE_CHAIN_MAX_CHAINS
            return rows[::-1][:limit]

    def query_evidence(
        self,
        chain_id: str = "",
        skill: str = "",
        phase: str = "",
        decision: str = "",
        limit: int = 0,
    ) -> list[dict]:
        """Query evidence points with optional filters (chain / skill / phase / decision)."""
        limit = limit or EVIDENCE_CHAIN_MAX_EVIDENCE
        out: list[dict] = []
        with self._lock:
            for ev in self._window:
                if chain_id and ev.chain_id != chain_id:
                    continue
                if skill and ev.target != skill:
                    continue
                if phase and ev.phase != phase:
                    continue
                if decision and ev.decision != decision:
                    continue
                out.append(ev.to_dict())
                if len(out) >= limit:
                    break
        return out

    def search(self, term: str, limit: int = 0) -> list[dict]:
        """Substring search over targets / tags / raw of the hot window."""
        term = term.lower()
        with self._lock:
            items = list(self._window)
        limit = limit or EVIDENCE_CHAIN_SEARCH_LIMIT
        out: list[dict] = []
        for ev in items:
            haystack = f"{ev.target} {json.dumps(ev.tags, default=str)} {json.dumps(ev.raw, default=str)}".lower()
            if term in haystack:
                out.append(ev.to_dict())
                if len(out) >= limit:
                    break
        return out

    def chain_evidence(self, chain_id: str) -> list[dict]:
        """All evidence of one chain, in recorded order."""
        with self._lock:
            chain = self._chains.get(chain_id or "")
            if chain is None:
                return []
            ids = list(chain.evidence_ids)
            return [self._evidence_by_id[eid].to_dict() for eid in ids if eid in self._evidence_by_id]

    # ── analysis / report (reverse-skill Evidence -> Finding) ──

    def analyze(self, chain_id: str = "") -> dict:
        """Derive the chain verdict and ordered findings.

        Verdict rules:
          - ``bypassed`` when a soft bypass (offensive policy disabled) or a
            harness auto-approval appears in the chain;
          - ``warranted`` when full_power escalation or an offense-posture
            ALLOW (authorized nature) appears;
          - ``clean`` otherwise.

        Each finding anchors to the evidence_id that supports it —
        VulnClaw-style anti-hallucination: a conclusion must resolve back to a
        real recorded point.
        """
        points = self.chain_evidence(chain_id)
        if not points:
            return {"chain_id": chain_id, "verdict": "empty", "findings": [], "evidence": 0}
        counter: Counter[str] = Counter(e["decision"] for e in points)
        bypass_hits = [
            e
            for e in points
            if e["decision"] in (DECISION_BYPASS, DECISION_AUTO_APPROVED) or e.get("tags", {}).get("soft_bypass") == "1"
        ]
        power_hits = [e for e in points if e["decision"] == DECISION_FULL_POWER and e["phase"] in ("g4", "chain")]
        offense_allowed = [
            e for e in points if e["decision"] == DECISION_ALLOW and e["phase"] in ("injection", "use_skill")
        ]
        if bypass_hits:
            verdict = VERDICT_BYPASSED
        elif power_hits or offense_allowed:
            verdict = VERDICT_WARRANTED
        else:
            verdict = VERDICT_CLEAN

        findings: list[dict] = []
        for i, e in enumerate(points, start=1):
            decision = e["decision"]
            tags = e.get("tags") or {}
            skill = e["target"]
            if decision in (DECISION_BYPASS, DECISION_AUTO_APPROVED) or tags.get("soft_bypass") == "1":
                findings.append(
                    {
                        "id": f"F{i}",
                        "severity": "risk",
                        "kind": "bypass",
                        "evidence_id": e["evidence_id"],
                        "message": f"gate '{e['gate']}' soft-bypassed in phase '{e['phase']}' for '{skill}'",
                    }
                )
            elif decision == DECISION_FULL_POWER and e["phase"] in ("g4", "chain"):
                findings.append(
                    {
                        "id": f"F{i}",
                        "severity": "high",
                        "kind": "escalation",
                        "evidence_id": e["evidence_id"],
                        "message": f"full_power posture escalated '{skill}'",
                    }
                )
            elif decision == DECISION_ALLOW and e["phase"] in ("injection", "use_skill"):
                findings.append(
                    {
                        "id": f"F{i}",
                        "severity": "medium",
                        "kind": "offense_use",
                        "evidence_id": e["evidence_id"],
                        "message": f"offense-posture skill '{skill}' granted ({tags.get('nature', '?')})",
                    }
                )
            elif decision == DECISION_BLOCK:
                findings.append(
                    {
                        "id": f"F{i}",
                        "severity": "info",
                        "kind": "block",
                        "evidence_id": e["evidence_id"],
                        "message": f"gate '{e['gate']}' blocked '{skill}' (defense held)",
                    }
                )
            elif decision == DECISION_CHANGE and e["phase"] in ("posture", "harness", "policy", "chain"):
                findings.append(
                    {
                        "id": f"F{i}",
                        "severity": "info",
                        "kind": "switch",
                        "evidence_id": e["evidence_id"],
                        "message": f"posture switch: {e['phase']} -> {skill}",
                    }
                )
        return {
            "chain_id": self._resolved_chain_id(chain_id),
            "verdict": verdict,
            "decisions": dict(counter),
            "evidence": len(points),
            "findings": findings[:EVIDENCE_CHAIN_REPORT_FINDINGS_MAX],
        }

    def cross_chain_analyze(self, kind: str = "") -> dict:
        """Aggregate statistics across chains, optionally filtered by kind.

        Groups chain verdicts and decision counts over the chain index so an
        operator (or the L3A decision layer) can see posture/attack patterns
        at a glance — how many chains bypassed, how many held, which skills
        were granted offense posture. Reads are lock-protected snapshots.

        Returns:
            ``{"success": True, "kind": ..., "chains": N, "verdicts": {...},
              "decisions": {...}, "skills": {...}}``.
        """
        with self._lock:
            rows = [self._chains[cid].to_dict() for cid in self._chain_order]
        verdicts: Counter[str] = Counter()
        decisions: Counter[str] = Counter()
        skills: Counter[str] = Counter()
        analyzed = 0
        for row in rows:
            if kind and row.get("kind") != kind:
                continue
            cid = row.get("chain_id", "")
            analysis = self.analyze(cid)
            verdicts[analysis.get("verdict", "clean")] += 1
            for decision, count in (analysis.get("decisions") or {}).items():
                decisions[decision] += count
            for point in self.chain_evidence(cid):
                target = point.get("target") or ""
                if target:
                    skills[target] += 1
            analyzed += 1
        return {
            "success": True,
            "kind": kind,
            "chains": analyzed,
            "verdicts": dict(verdicts),
            "decisions": dict(decisions),
            "skills": dict(skills.most_common(10)),
        }

    def report(self, chain_id: str = "") -> dict:
        """Build the chain report: verdict + timeline + findings + fixity.

        The markdown body follows the field-journal layout; the fixity pass
        re-hashes every on-disk line of the chain (tamper detection).
        """
        chain = self._find_chain(chain_id)
        if chain is None:
            return {"success": False, "error": f"unknown chain: {chain_id}"}
        analysis = self.analyze(chain.chain_id)
        points = self.chain_evidence(chain.chain_id)
        fixity = self.verify_chain(chain.chain_id)
        lines = [
            "# Evidence Chain",
            "",
            f"- chain: `{chain.chain_id}` (kind=`{chain.kind}`, source=`{chain.source}`)",
            f"- window: `{chain.opened:.1f}` -> `{chain.closed or 'open'}`",
            f"- verdict: `{analysis['verdict']}`",
            "",
            "## Timeline",
            "",
            "| # | ts | phase | gate | decision | target | source |",
            "|---|----|-------+------+----------+--------+--------|",
        ]
        for i, e in enumerate(points, start=1):
            lines.append(
                f"| {i} | {e['ts']:.1f} | {e['phase']} | {e['gate']} | {e['decision']} | {e['target']} | {e['source']} |"
            )
        lines += ["", "## Findings", ""]
        for f in analysis["findings"]:
            lines.append(f"- [{f['severity']}] {f['message']} (evidence_id={f['evidence_id']})")
        lines += ["", "## Fixity", ""]
        note = "OK" if fixity["ok"] else f"FAILED ({fixity['bad']} mismatched)"
        lines.append(f"- {fixity['checked']} evidence points verified — {note}")
        return {
            "success": True,
            "chain_id": chain.chain_id,
            "verdict": analysis["verdict"],
            "findings": analysis["findings"],
            "timeline": points,
            "fixity": fixity,
            "markdown": "\n".join(lines),
        }

    def verify_chain(self, chain_id: str = "") -> dict:
        """Recompute fixity hashes of the chain's on-disk rows (tamper check)."""
        chain = self._find_chain(chain_id)
        if chain is None:
            return {"checked": 0, "ok": True, "bad": 0}
        ids = set(chain.evidence_ids)
        checked = 0
        bad = 0
        try:
            if not os.path.exists(self._path):
                return {"checked": 0, "ok": True, "bad": 0}
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    if data.get("evidence_id") not in ids:
                        continue
                    checked += 1
                    payload = json.dumps(
                        {
                            "ts": data.get("ts"),
                            "phase": data.get("phase"),
                            "gate": data.get("gate"),
                            "decision": data.get("decision"),
                            "target": data.get("target"),
                            "source": data.get("source"),
                            "tags": data.get("tags") or {},
                            "raw": data.get("raw") or {},
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                        default=str,
                    ).encode("utf-8")
                    if hashlib.sha256(payload).hexdigest() != data.get("raw_hash"):
                        bad += 1
        except Exception as e:
            logger.warning("security_evidence: fixity check failed: %s", e)
            return {"checked": checked, "ok": False, "bad": bad + 1, "error": str(e)}
        return {"checked": checked, "ok": bad == 0, "bad": bad}

    # ── persistence ──

    def _append(self, ev: EvidencePoint) -> None:
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
                f.flush()
        except Exception as e:
            logger.debug("security_evidence: append failed (memory-only): %s", e)

    def _load(self) -> None:
        """Tail-load the persisted JSONL into the hot window (rebuild)."""
        if not os.path.exists(self._path):
            return
        try:
            tail: deque[str] = deque(maxlen=EVIDENCE_CHAIN_RELOAD_LINES)
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        tail.append(line)
            for line in tail:
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                ev = _ev_from_dict(data)
                if ev is None:
                    continue
                with self._lock:
                    if ev.evidence_id in self._evidence_by_id:
                        continue
                    self._evidence_by_id[ev.evidence_id] = ev
                    self._window.append(ev)
                    chain = self._chains.get(ev.chain_id)
                    if chain is None:
                        chain = ChainRecord(chain_id=ev.chain_id, kind=DEFAULT_CHAIN_KIND)
                        self._chains[ev.chain_id] = chain
                        self._chain_order.append(ev.chain_id)
                    chain.evidence_ids.append(ev.evidence_id)
        except Exception as e:
            logger.warning("security_evidence: load failed: %s", e)

    def _ensure_chain(self, kind: str, source: str) -> str:
        """Return the chain_id for ``kind``.

        An explicit kind (attack / downgrade / policy-bypass / ambient) is
        reused or opened; the empty kind follows the newest open posture
        chain (so gate evidence lands in the chain that belongs to the event),
        falling back to the ambient chain.
        """
        with self._lock:
            kind = str(kind or "")
            if kind:
                chain_id = self._open_kinds.get(kind)
                if chain_id and chain_id in self._chains:
                    return chain_id
                return self.begin_chain(kind, source)
            for k in ("attack", "policy-bypass", "downgrade"):
                chain_id = self._open_kinds.get(k)
                if chain_id and chain_id in self._chains:
                    return chain_id
            ambient = self._open_kinds.get(DEFAULT_CHAIN_KIND)
            if ambient and ambient in self._chains:
                return ambient
            return self.begin_chain(DEFAULT_CHAIN_KIND, source)

    def _prune_chains(self) -> None:
        while len(self._chains) > EVIDENCE_CHAIN_MAX_CHAINS:
            oldest = self._chain_order.popleft()
            self._chains.pop(oldest, None)
            self._open_kinds.pop(next((k for k, v in self._open_kinds.items() if v == oldest), ""), None)

    def _find_chain(self, chain_id: str) -> ChainRecord | None:
        with self._lock:
            chain = self._chains.get(chain_id or "")
            if chain is None and not chain_id:
                ordered = list(self._chain_order)
                chain = self._chains.get(ordered[-1]) if ordered else None
            return chain

    def _resolved_chain_id(self, chain_id: str) -> str:
        chain = self._find_chain(chain_id)
        return chain.chain_id if chain else (chain_id or "")
