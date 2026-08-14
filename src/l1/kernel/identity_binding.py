"""Identity binding — per-Cell role-to-prompt-fragment binding registry.

Phase 1 of the organizational-evolution design (see
``docs/design/related-work.md``): each Cell records which roles are bound to
strict-role prompt fragments / domain tags, and AgentLoop injects the
fragment into the system prompt (bounded by ``IDENTITY_BINDING_MAX_CHARS``).
Bindings are config-driven (``praxis.yaml identity_binding:``) and
API-configurable; prompt content lives in the prompt registry, never in
params. The only built-in behavior is a minimal generalized fragment from
the registry so a single Cell works out of the box (egalitarian baseline).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field

from .params.agent import (
    AGENT_CLEARANCE,
    IDENTITY_BINDING_MAX_CHARS,
    IDENTITY_BINDING_MAX_PER_CELL,
    IDENTITY_BINDING_WRITE_MIN_RING,
    IDENTITY_BINDING_WRITE_ROLES,
    IDENTITY_DEFAULT_SET,
    IDENTITY_FIELDS,
)
from .prompts import get_prompt

logger = logging.getLogger(__name__)

_EVENT_TYPE = "identity_binding_mutated"


def _default_state_path() -> str:
    """Resolve the identity-binding persistence file under the data dir."""
    try:
        from .paths import get_paths as _gp

        return os.path.join(_gp().data_dir, "identity_bindings.json")
    except Exception:
        return os.path.join(os.getcwd(), "identity_bindings.json")


@dataclass
class IdentityBinding:
    """IdentityBinding — a role binding record for one Cell."""

    cell_id: str
    role: str
    prompt_fragment: str
    domain_tags: list[str] = field(default_factory=list)
    max_chars: int = 0
    updated_by: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialize the binding (fragment excluded from external views)."""
        return {
            "cell_id": self.cell_id,
            "role": self.role,
            "domain_tags": list(self.domain_tags),
            "max_chars": self.max_chars or IDENTITY_BINDING_MAX_CHARS,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }


class IdentityBindingManager:
    """Per-Cell identity binding registry with a write gate."""

    def __init__(self, state_path: str = "") -> None:
        self._bindings: dict[str, dict[str, IdentityBinding]] = {}
        self._lock = threading.RLock()
        self._revision = 0
        self._state_path = state_path or os.environ.get("PRAXIS_IDENTITY_STATE") or _default_state_path()
        self._restore()

    # ── Persistence (survives restarts) ──

    def _persist(self) -> None:
        """Snapshot bindings to the state file (atomic tmp+replace).

        Uses the FULL record (including prompt_fragment) — unlike to_dict(),
        which deliberately excludes the fragment from external views.
        """
        try:
            data = {
                cell_id: {
                    role: {
                        "cell_id": b.cell_id,
                        "role": b.role,
                        "prompt_fragment": b.prompt_fragment,
                        "domain_tags": list(b.domain_tags),
                        "max_chars": b.max_chars,
                        "updated_by": b.updated_by,
                        "updated_at": b.updated_at,
                    }
                    for role, b in cell_map.items()
                }
                for cell_id, cell_map in self._bindings.items()
            }
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._state_path)
        except Exception as e:
            logger.warning("identity_binding: persist failed: %s", e)

    def _restore(self) -> None:
        """Reload bindings from the state file (best-effort)."""
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            for cell_id, cell_map in (data or {}).items():
                for role, d in (cell_map or {}).items():
                    self._bindings.setdefault(str(cell_id), {})[str(role)] = IdentityBinding(
                        cell_id=str(cell_id),
                        role=str(role),
                        prompt_fragment=str(d.get("prompt_fragment", "")),
                        domain_tags=[str(t) for t in (d.get("domain_tags") or [])],
                        max_chars=int(d.get("max_chars", 0) or 0),
                        updated_by=str(d.get("updated_by", "")),
                        updated_at=float(d.get("updated_at", 0.0) or 0.0),
                    )
            self._revision += 1
            logger.info("identity_binding: restored %d cell(s) from %s", len(self._bindings), self._state_path)
        except Exception as e:
            logger.warning("identity_binding: restore failed: %s", e)

    # ── Write gate ──

    def authorize_write(self, agent_id: str = "", role: str = "", internal: bool = False) -> tuple[bool, str]:
        """Check whether a caller may mutate identity bindings.

        External callers (L2 shell, L4 API) must pass an explicit role or
        agent id; identity-less writes are allowed only with
        ``internal=True`` from system processes (boot loading). Mirrors the
        skill write gate.
        """
        if internal:
            return True, ""
        if not agent_id and not role:
            return False, "identity required for identity-binding writes"
        if role in IDENTITY_BINDING_WRITE_ROLES:
            return True, ""
        if AGENT_CLEARANCE.get(role, 0) >= IDENTITY_BINDING_WRITE_MIN_RING:
            return True, ""
        return False, f"role '{role}' may not mutate identity bindings"

    # ── Mutations ──

    def bind(
        self,
        cell_id: str,
        role: str,
        prompt_fragment: str,
        domain_tags: list[str] | None = None,
        max_chars: int = 0,
        agent_id: str = "",
        writer_role: str = "",
        internal: bool = False,
    ) -> dict:
        """Bind a role in a Cell to a strict-role prompt fragment.

        The fragment is truncated to the effective character limit instead
        of rejected, so oversized API payloads degrade gracefully.
        """
        ok, err = self.authorize_write(agent_id, writer_role, internal=internal)
        if not ok:
            return {"success": False, "error": err}
        limit = max_chars or IDENTITY_BINDING_MAX_CHARS
        if limit < 1:
            return {"success": False, "error": "max_chars must be a positive integer"}
        # Caller-supplied limits never exceed the registry cap — an oversized
        # value would otherwise inflate the injected system prompt unboundedly.
        limit = min(limit, IDENTITY_BINDING_MAX_CHARS)
        fragment = prompt_fragment[:limit]
        with self._lock:
            cell_map = self._bindings.setdefault(cell_id, {})
            if len(cell_map) >= IDENTITY_BINDING_MAX_PER_CELL and role not in cell_map:
                return {"success": False, "error": f"binding cap reached for cell {cell_id}"}
            cell_map[role] = IdentityBinding(
                cell_id=cell_id,
                role=role,
                prompt_fragment=fragment,
                domain_tags=list(domain_tags or []),
                max_chars=limit,
                updated_by=agent_id or writer_role,
            )
            self._revision += 1
        self._persist()
        self._emit_mutated(cell_id, role, "bound")
        return {"success": True, "cell_id": cell_id, "role": role, "chars": len(fragment)}

    def unbind(
        self, cell_id: str, role: str, agent_id: str = "", writer_role: str = "", internal: bool = False
    ) -> dict:
        """Remove a role binding from a Cell."""
        ok, err = self.authorize_write(agent_id, writer_role, internal=internal)
        if not ok:
            return {"success": False, "error": err}
        with self._lock:
            cell_map = self._bindings.get(cell_id)
            if not cell_map or role not in cell_map:
                return {"success": False, "error": f"no binding for {cell_id}/{role}"}
            del cell_map[role]
            if not cell_map:
                self._bindings.pop(cell_id, None)
            self._revision += 1
        self._persist()
        self._emit_mutated(cell_id, role, "unbound")
        return {"success": True}

    def clear_cell(self, cell_id: str, agent_id: str = "", writer_role: str = "", internal: bool = False) -> dict:
        """Drop all role bindings for a Cell."""
        ok, err = self.authorize_write(agent_id, writer_role, internal=internal)
        if not ok:
            return {"success": False, "error": err}
        with self._lock:
            self._bindings.pop(cell_id, None)
            self._revision += 1
        self._persist()
        self._emit_mutated(cell_id, "*", "cleared")
        return {"success": True, "cell_id": cell_id}

    # ── Reads ──

    def get_binding(self, cell_id: str, role: str) -> IdentityBinding | None:
        """Return the custom binding for (cell_id, role), or None."""
        with self._lock:
            return self._bindings.get(cell_id, {}).get(role)

    def bindings_for_cell(self, cell_id: str) -> dict[str, dict]:
        """Return structured views of all bindings for a Cell (no fragments)."""
        with self._lock:
            cell_map = self._bindings.get(cell_id, {})
            return {r: b.to_dict() for r, b in cell_map.items()}

    def resolve_fragment(self, cell_id: str, role: str) -> str:
        """Return the effective system-prompt fragment for (cell_id, role).

        Custom binding fragment if one exists; otherwise the built-in
        generalized minimal fragment from the prompt registry (single-Cell
        egalitarian baseline). Length is bounded by the binding's limit.
        """
        binding = self.get_binding(cell_id, role)
        if binding and binding.prompt_fragment:
            return binding.prompt_fragment
        return get_prompt("identity_binding.default_fragment", "").format(cell_id=cell_id, role=role)[
            :IDENTITY_BINDING_MAX_CHARS
        ]

    def identity_set_for(self, cell_id: str, role: str) -> tuple[str, ...]:
        """Return the generic three-identity set for an Agent entity.

        Every Agent is a composite of the standard identities (build / test /
        review). A binding's ``domain_tags`` — when they name identity
        fields — narrow the set; otherwise the full default set applies.
        Never returns fields outside IDENTITY_FIELDS.

        Args:
            cell_id: The Cell the agent belongs to.
            role: The agent's role within the cell.

        Returns:
            Tuple of identity field names (subset of IDENTITY_FIELDS).
        """
        binding = self.get_binding(cell_id, role)
        if binding and binding.domain_tags:
            valid = [t for t in binding.domain_tags if t in IDENTITY_FIELDS]
            if valid:
                return tuple(valid)
        return IDENTITY_DEFAULT_SET

    def resolve_domain_fragment(self, cell_id: str, domain: str) -> str:
        """Return the domain-expert fragment matching a card's structured domain.

        Card-domain linkage ([3]): the driving card's ``domain`` column is
        matched against every binding in the Cell whose ``domain_tags``
        contain that domain; the first hit's prompt fragment is returned for
        injection alongside the role fragment. Returns "" when no binding
        names the domain (no expert known — graceful, never raises).

        Args:
            cell_id: The Cell whose bindings are searched.
            domain: The card's structured domain (e.g. "test", "codegen").

        Returns:
            The matched binding's fragment, or "" when unmatched.
        """
        if not domain:
            return ""
        with self._lock:
            cell_map = self._bindings.get(cell_id, {})
            for binding in cell_map.values():
                if domain in binding.domain_tags and binding.prompt_fragment:
                    return binding.prompt_fragment
        return ""

    def cell_ids(self) -> list[str]:
        """Return all Cell ids that have bindings (for API listing)."""
        with self._lock:
            return list(self._bindings.keys())

    def revision(self) -> int:
        """Return the mutation counter (for injection-cache invalidation)."""
        with self._lock:
            return self._revision

    def _emit_mutated(self, cell_id: str, role: str, action: str) -> None:
        data = {"cell_id": cell_id, "role": role, "action": action}
        try:
            from .event import get_bus

            get_bus().emit_event(_EVENT_TYPE, data, source="identity_binding")
        except Exception as e:
            logger.warning("identity_binding: event emit failed: %s", e)


_manager: IdentityBindingManager | None = None


def get_identity_binding_manager() -> IdentityBindingManager:
    """Get the global IdentityBindingManager singleton."""
    global _manager
    if _manager is None:
        _manager = IdentityBindingManager()
    return _manager


def reset_identity_binding_manager() -> None:
    """Reset the singleton (used by tests)."""
    global _manager
    _manager = None
