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
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field

from .params.agent import (
    AGENT_CLEARANCE,
    IDENTITY_BINDING_MAX_CHARS,
    IDENTITY_BINDING_MAX_PER_CELL,
    IDENTITY_BINDING_PERSIST_CLEAR,
    IDENTITY_BINDING_PERSIST_UNBIND,
    IDENTITY_BINDING_PERSIST_UPSERT,
    IDENTITY_BINDING_STATE_LOCK_SUFFIX,
    IDENTITY_BINDING_STATE_TEMP_PREFIX,
    IDENTITY_BINDING_STATE_TEMP_SUFFIX,
    IDENTITY_BINDING_WRITE_MIN_RING,
    IDENTITY_BINDING_WRITE_ROLES,
    IDENTITY_DEFAULT_SET,
    IDENTITY_DEFINITION_MAX_CHARS,
    IDENTITY_FIELDS,
)
from .prompts import get_prompt

logger = logging.getLogger(__name__)

_EVENT_TYPE = "identity_binding_mutated"
_state_locks: dict[str, threading.RLock] = {}
_state_locks_guard = threading.Lock()
# Memoized built-in generalized definitions per role (see
# IdentityBindingManager._default_definition) — prompt templates are
# boot-time constants, so the cache is process-lifetime valid.
_default_def_cache: dict[str, str] = {}


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
    # Phase A: system-issued UID (identity_uid issuer) — the declarative
    # registry key that department registration can reference by id.
    identity_id: str = ""
    # Phase B: detailed definition of the registered identity (default from
    # the prompt registry identity_definition.<role>, user-overridable via
    # API). Bounded by IDENTITY_DEFINITION_MAX_CHARS; excluded from external
    # views (same principle as the prompt fragment).
    definition: str = ""

    def to_dict(self) -> dict:
        """Serialize the binding (fragment/definition excluded from external views)."""
        return {
            "cell_id": self.cell_id,
            "role": self.role,
            "identity_id": self.identity_id,
            "domain_tags": list(self.domain_tags),
            "max_chars": self.max_chars or IDENTITY_BINDING_MAX_CHARS,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class _PersistedBinding:
    """Immutable binding record used by a persistence snapshot."""

    cell_id: str
    role: str
    prompt_fragment: str
    domain_tags: tuple[str, ...]
    max_chars: int
    updated_by: str
    updated_at: float
    identity_id: str = ""
    definition: str = ""

    @classmethod
    def from_binding(cls, binding: IdentityBinding) -> _PersistedBinding:
        """Copy a mutable binding into an immutable persistence record."""
        return cls(
            cell_id=binding.cell_id,
            role=binding.role,
            prompt_fragment=binding.prompt_fragment,
            domain_tags=tuple(binding.domain_tags),
            max_chars=binding.max_chars,
            updated_by=binding.updated_by,
            updated_at=binding.updated_at,
            identity_id=binding.identity_id,
            definition=binding.definition,
        )

    def to_state_dict(self) -> dict:
        """Serialize the full record, including the private prompt fragment."""
        return {
            "cell_id": self.cell_id,
            "role": self.role,
            "prompt_fragment": self.prompt_fragment,
            "domain_tags": list(self.domain_tags),
            "max_chars": self.max_chars,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
            "identity_id": self.identity_id,
            "definition": self.definition,
        }


@dataclass(frozen=True)
class _BindingSnapshot:
    """Immutable in-memory state captured at one manager revision."""

    revision: int
    records: tuple[_PersistedBinding, ...]

    def record_for(self, cell_id: str, role: str) -> _PersistedBinding | None:
        """Return the immutable record for one binding, if present."""
        return next((record for record in self.records if record.cell_id == cell_id and record.role == role), None)


@dataclass(frozen=True)
class _BindingMutation:
    """One durable state change derived from a manager snapshot."""

    revision: int
    action: str
    cell_id: str
    role: str = ""
    record: _PersistedBinding | None = None


class IdentityBindingManager:
    """Per-Cell identity binding registry with a write gate."""

    def __init__(self, state_path: str = "") -> None:
        self._bindings: dict[str, dict[str, IdentityBinding]] = {}
        self._lock = threading.RLock()
        self._persist_lock = threading.RLock()
        self._revision = 0
        self._state_path = state_path or os.environ.get("PRAXIS_IDENTITY_STATE") or _default_state_path()
        self._restore()

    # ── Persistence (survives restarts) ──

    def _snapshot_locked(self) -> _BindingSnapshot:
        """Capture the current bindings while the manager lock is held."""
        return _BindingSnapshot(
            revision=self._revision,
            records=tuple(
                _PersistedBinding.from_binding(binding)
                for cell_map in self._bindings.values()
                for binding in cell_map.values()
            ),
        )

    def _persist(self, snapshot: _BindingSnapshot, mutation: _BindingMutation) -> None:
        """Merge one immutable mutation into the state file atomically.

        A manager serializes its own revisions before entering the shared
        state-path lock. The transaction reloads the durable state, applies
        only this mutation, then replaces the file with a unique temporary
        file. Separate managers therefore keep bindings they do not own.
        """
        if mutation.revision != snapshot.revision:
            raise ValueError("identity-binding persistence revision mismatch")
        try:
            with self._state_path_lock():
                data = self._read_state_data()
                self._apply_mutation(data, mutation)
                self._write_state_data(data)
        except Exception as e:
            logger.warning("identity_binding: persist failed: %s", e)

    @contextmanager
    def _state_path_lock(self) -> Iterator[None]:
        """Hold the in-process and POSIX advisory locks for this state file."""
        canonical_path = os.path.abspath(self._state_path)
        with _state_locks_guard:
            path_lock = _state_locks.setdefault(canonical_path, threading.RLock())

        state_dir = os.path.dirname(canonical_path)
        lock_path = f"{canonical_path}{IDENTITY_BINDING_STATE_LOCK_SUFFIX}"
        with path_lock:
            os.makedirs(state_dir, exist_ok=True)
            with open(lock_path, "a+", encoding="utf-8") as lock_file:
                try:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                except ImportError:
                    pass
                try:
                    yield
                finally:
                    try:
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except ImportError:
                        pass

    def _read_state_data(self) -> dict[str, dict[str, dict]]:
        """Read the durable state under the state-path lock."""
        if not os.path.exists(self._state_path):
            return {}
        with open(self._state_path, encoding="utf-8") as state_file:
            data = json.load(state_file)
        if not isinstance(data, dict):
            raise ValueError("identity-binding state must be a mapping")
        return data

    @staticmethod
    def _apply_mutation(data: dict[str, dict[str, dict]], mutation: _BindingMutation) -> None:
        """Apply one persisted mutation without discarding unrelated cells."""
        if mutation.action == IDENTITY_BINDING_PERSIST_CLEAR:
            data.pop(mutation.cell_id, None)
            return
        if mutation.action == IDENTITY_BINDING_PERSIST_UNBIND:
            cell_map = data.get(mutation.cell_id)
            if isinstance(cell_map, dict):
                cell_map.pop(mutation.role, None)
                if not cell_map:
                    data.pop(mutation.cell_id, None)
            return
        if mutation.action != IDENTITY_BINDING_PERSIST_UPSERT or mutation.record is None:
            raise ValueError("identity-binding persistence mutation is invalid")
        cell_map = data.get(mutation.cell_id)
        if not isinstance(cell_map, dict):
            cell_map = {}
            data[mutation.cell_id] = cell_map
        cell_map[mutation.role] = mutation.record.to_state_dict()

    def _write_state_data(self, data: dict[str, dict[str, dict]]) -> None:
        """Write durable state through a uniquely named sibling temporary file."""
        state_dir = os.path.dirname(os.path.abspath(self._state_path))
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=state_dir,
                prefix=IDENTITY_BINDING_STATE_TEMP_PREFIX,
                suffix=IDENTITY_BINDING_STATE_TEMP_SUFFIX,
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name
                json.dump(data, temp_file, indent=2, ensure_ascii=False)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self._state_path)
        except Exception:
            if temp_path:
                with suppress(FileNotFoundError):
                    os.unlink(temp_path)
            raise

    def _restore(self) -> None:
        """Reload bindings from the state file (best-effort)."""
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            for cell_id, cell_map in (data or {}).items():
                for role, d in (cell_map or {}).items():
                    identity_id = str(d.get("identity_id", "") or "")
                    # Re-register persisted UIDs into the issuer's seen-set so
                    # a rebind keeps its id and no duplicate is issued.
                    if identity_id:
                        try:
                            from .identity_uid import _track_existing

                            _track_existing(identity_id)
                        except Exception as e:
                            logger.debug("identity_binding: uid track skipped: %s", e)
                    self._bindings.setdefault(str(cell_id), {})[str(role)] = IdentityBinding(
                        cell_id=str(cell_id),
                        role=str(role),
                        prompt_fragment=str(d.get("prompt_fragment", "")),
                        domain_tags=[str(t) for t in (d.get("domain_tags") or [])],
                        max_chars=int(d.get("max_chars", 0) or 0),
                        updated_by=str(d.get("updated_by", "")),
                        updated_at=float(d.get("updated_at", 0.0) or 0.0),
                        identity_id=identity_id,
                        definition=str(d.get("definition", "") or ""),
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
        definition: str = "",
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
        # Phase B: detailed definition — caller-supplied wins, otherwise the
        # built-in generalized definition from the prompt registry
        # (identity_definition.<role>); capped by IDENTITY_DEFINITION_MAX_CHARS.
        definition = (definition or self._default_definition(role))[:IDENTITY_DEFINITION_MAX_CHARS]
        # Phase A: system-issued UID — the declarative registry key for
        # department registration. Issued once per binding; a rebind keeps
        # the existing UID so department references stay stable.
        with self._persist_lock:
            with self._lock:
                cell_map = self._bindings.setdefault(cell_id, {})
                if len(cell_map) >= IDENTITY_BINDING_MAX_PER_CELL and role not in cell_map:
                    return {"success": False, "error": f"binding cap reached for cell {cell_id}"}
                existing = cell_map.get(role)
                identity_id = existing.identity_id if existing else self._issue_uid()
                cell_map[role] = IdentityBinding(
                    cell_id=cell_id,
                    role=role,
                    prompt_fragment=fragment,
                    domain_tags=list(domain_tags or []),
                    max_chars=limit,
                    updated_by=agent_id or writer_role,
                    identity_id=identity_id,
                    definition=definition,
                )
                self._revision += 1
                snapshot = self._snapshot_locked()
                record = snapshot.record_for(cell_id, role)
            self._persist(
                snapshot,
                _BindingMutation(
                    revision=snapshot.revision,
                    action=IDENTITY_BINDING_PERSIST_UPSERT,
                    cell_id=cell_id,
                    role=role,
                    record=record,
                ),
            )
        self._emit_mutated(cell_id, role, "bound")
        return {"success": True, "cell_id": cell_id, "role": role, "chars": len(fragment), "identity_id": identity_id}

    def _issue_uid(self) -> str:
        """Issue a fresh identity UID via the L1 issuer ("" on failure)."""
        try:
            from .identity_uid import issue_identity_uid

            return issue_identity_uid()
        except Exception as e:
            logger.warning("identity_binding: uid issuance skipped: %s", e)
            return ""

    @staticmethod
    def _default_definition(role: str) -> str:
        """Return the built-in generalized definition for a role ("" when absent).

        The prompt-registry lookup is memoized per role — the definition
        templates are boot-time constants (config/praxis.yaml prompts:),
        so a cached value stays valid for the process lifetime. This keeps
        the resolve_definition hot path (AgentLoop system-prompt assembly)
        from re-hitting the registry on every unbound role query.
        """
        cached = _default_def_cache.get(role)
        if cached is not None:
            return cached
        try:
            from .prompts import get_prompt

            text = get_prompt(f"identity_definition.{role}", "")
        except Exception as e:
            logger.debug("identity_binding: default definition skipped: %s", e)
            text = ""
        _default_def_cache[role] = text
        return text

    def resolve_definition(self, cell_id: str, role: str) -> str:
        """Return the effective definition for (cell_id, role).

        Custom definition if the binding set one; otherwise the built-in
        generalized definition from the prompt registry. Length is bounded by
        ``IDENTITY_DEFINITION_MAX_CHARS``.
        """
        binding = self.get_binding(cell_id, role)
        if binding and binding.definition:
            return binding.definition[:IDENTITY_DEFINITION_MAX_CHARS]
        return self._default_definition(role)[:IDENTITY_DEFINITION_MAX_CHARS]

    def unbind(
        self, cell_id: str, role: str, agent_id: str = "", writer_role: str = "", internal: bool = False
    ) -> dict:
        """Remove a role binding from a Cell."""
        ok, err = self.authorize_write(agent_id, writer_role, internal=internal)
        if not ok:
            return {"success": False, "error": err}
        with self._persist_lock:
            with self._lock:
                cell_map = self._bindings.get(cell_id)
                if not cell_map or role not in cell_map:
                    return {"success": False, "error": f"no binding for {cell_id}/{role}"}
                del cell_map[role]
                if not cell_map:
                    self._bindings.pop(cell_id, None)
                self._revision += 1
                snapshot = self._snapshot_locked()
            self._persist(
                snapshot,
                _BindingMutation(
                    revision=snapshot.revision,
                    action=IDENTITY_BINDING_PERSIST_UNBIND,
                    cell_id=cell_id,
                    role=role,
                ),
            )
        self._emit_mutated(cell_id, role, "unbound")
        return {"success": True}

    def clear_cell(self, cell_id: str, agent_id: str = "", writer_role: str = "", internal: bool = False) -> dict:
        """Drop all role bindings for a Cell."""
        ok, err = self.authorize_write(agent_id, writer_role, internal=internal)
        if not ok:
            return {"success": False, "error": err}
        with self._persist_lock:
            with self._lock:
                self._bindings.pop(cell_id, None)
                self._revision += 1
                snapshot = self._snapshot_locked()
            self._persist(
                snapshot,
                _BindingMutation(
                    revision=snapshot.revision,
                    action=IDENTITY_BINDING_PERSIST_CLEAR,
                    cell_id=cell_id,
                ),
            )
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
