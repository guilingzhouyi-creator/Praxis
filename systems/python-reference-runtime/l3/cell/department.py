"""Department division — cell-count-triggered role specialization.

Phase 3 of the organizational-evolution design (see ``docs/design/
related-work.md``): when the runtime switch is on and the Cell count
reaches ``CELL_DEPARTMENT_MIN``, the organization splits into egalitarian
departments — e.g. a professional testing department bound to the
``tester`` role. The manager decides directed transport for content types
so specialized work (test matrices, verification) is handed to the owning
department instead of staying in the generic pool.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from l1.kernel.params.agent import (
    CELL_DEPARTMENT_MIN,
    CELL_IDENTITY_DEFAULT,
    CELL_IDENTITY_VALID,
    DEPARTMENT_DEFINITION_MAX_CHARS,
    DEPARTMENT_ENABLED_DEFAULT,
    DEPARTMENT_TYPE_DEFAULT,
    DEPARTMENT_TYPES,
    TEST_DEPARTMENT_ID,
    TEST_DEPARTMENT_ROLES,
)

logger = logging.getLogger(__name__)


@dataclass
class Department:
    """Department — a role specialization group (e.g. testing)."""

    id: str
    roles: list[str]
    description: str = ""
    auto_enabled: bool = True
    dept_type: str = DEPARTMENT_TYPE_DEFAULT
    cell_identity: str = CELL_IDENTITY_DEFAULT
    # Phase C: detailed definition (capped by DEPARTMENT_DEFINITION_MAX_CHARS)
    # and permission scope — content types this department may handle.
    # Routing a content type outside the scope is refused (not just unmapped).
    definition: str = ""
    permission_scope: list[str] = field(default_factory=list)
    # Phase C (model_role_for de-hardcoding): optional executor override;
    # when empty, the built-in dept_type -> executor fallback applies.
    executor: str = ""


class DepartmentManager:
    """Department registry with cell-count-triggered activation and routing."""

    def __init__(self) -> None:
        self._departments: dict[str, Department] = {}
        self._lock = threading.RLock()
        # Lookup indexes (role -> dept_id, dept_type -> dept_id) rebuilt on
        # load/register so department_for_role / route_content hot paths
        # avoid an O(N) scan per query.
        self._role_index: dict[str, str] = {}
        self._type_index: dict[str, str] = {}
        self._load_defaults()

    def _rebuild_indexes(self) -> None:
        """Rebuild the role/type lookup indexes from the registry.

        Only auto-enabled departments are indexed — a disabled department
        (``auto_enabled: false`` in departments.yaml) must not be resolved by
        the fast paths, keeping them consistent with the fallback scans that
        skip disabled departments.
        """
        with self._lock:
            self._role_index = {}
            self._type_index = {}
            for dept in self._departments.values():
                if not dept.auto_enabled:
                    continue
                for role in dept.roles:
                    self._role_index.setdefault(role, dept.id)
                self._type_index.setdefault(dept.dept_type, dept.id)

    def _load_defaults(self) -> None:
        """Load departments from config/discovery/departments.yaml.

        Falls back to the built-in testing department when the YAML is
        absent. Department types and Cell identities are validated against
        DEPARTMENT_TYPES / CELL_IDENTITY_VALID — unknown values are skipped
        with a warning (config-driven, never hardcoded).
        """
        try:
            from pathlib import Path

            import yaml

            p = (
                Path(__file__).resolve().parent.parent.parent.parent.parent
                / "config"
                / "discovery"
                / "departments.yaml"
            )
            if not p.exists():
                self._departments[TEST_DEPARTMENT_ID] = Department(
                    id=TEST_DEPARTMENT_ID,
                    roles=list(TEST_DEPARTMENT_ROLES),
                    description="Professional testing department (test matrices, verification).",
                    dept_type="test",
                    cell_identity="test",
                )
                return
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for dept_id, spec in (data.get("departments") or {}).items():
                if not isinstance(spec, dict):
                    continue
                dept_type = str(spec.get("type", DEPARTMENT_TYPE_DEFAULT))
                if dept_type not in DEPARTMENT_TYPES:
                    logger.warning("department: skip '%s' — unknown type '%s'", dept_id, dept_type)
                    continue
                cell_identity = str(spec.get("cell_identity", CELL_IDENTITY_DEFAULT))
                if cell_identity not in CELL_IDENTITY_VALID:
                    cell_identity = CELL_IDENTITY_DEFAULT
                self._departments[str(dept_id)] = Department(
                    id=str(dept_id),
                    roles=[str(r) for r in (spec.get("roles") or [])],
                    description=str(spec.get("description", "")),
                    auto_enabled=bool(spec.get("auto_enabled", True)),
                    dept_type=dept_type,
                    cell_identity=cell_identity,
                    # Phase C: definition (capped), permission scope, executor
                    # override — all config-driven, never hardcoded here.
                    definition=str(spec.get("definition", "") or "")[:DEPARTMENT_DEFINITION_MAX_CHARS],
                    permission_scope=[str(s) for s in (spec.get("permission_scope") or [])],
                    executor=str(spec.get("executor", "") or ""),
                )
        except Exception as e:
            logger.warning("department: config load failed, using built-in test dept: %s", e)
            self._departments[TEST_DEPARTMENT_ID] = Department(
                id=TEST_DEPARTMENT_ID,
                roles=list(TEST_DEPARTMENT_ROLES),
                description="Professional testing department (test matrices, verification).",
                dept_type="test",
                cell_identity="test",
            )
        self._rebuild_indexes()

    # ── Activation ──

    def enabled(self) -> bool:
        """Return the runtime enable switch (settings-driven, default off)."""
        try:
            from l1.kernel.settings import get_settings

            return bool(get_settings().get("departments.enabled", DEPARTMENT_ENABLED_DEFAULT))
        except Exception as e:
            logger.warning("department: settings lookup failed, defaulting to off: %s", e)
            return DEPARTMENT_ENABLED_DEFAULT

    def cell_count(self) -> int:
        """Return the current Cell count from the cell registry."""
        try:
            from l3.cell import get_cells

            return len(get_cells())
        except Exception as e:
            logger.warning("department: cell count lookup failed: %s", e)
            return 0

    def active(self, cell_count: int | None = None) -> bool:
        """Return whether department division is active (switch AND threshold)."""
        if not self.enabled():
            return False
        if cell_count is None:
            cell_count = self.cell_count()
        return cell_count >= CELL_DEPARTMENT_MIN

    # ── Registry ──

    def register(self, dept_id: str, roles: list[str], description: str = "", auto_enabled: bool = True) -> dict:
        """Register an additional department (extensible; config/API later)."""
        with self._lock:
            self._departments[dept_id] = Department(dept_id, list(roles), description, auto_enabled)
        self._rebuild_indexes()
        return {"success": True, "department": dept_id, "roles": list(roles)}

    def department_for_role(self, role: str, cell_count: int | None = None) -> str | None:
        """Return the department id owning *role* when division is active."""
        if not self.active(cell_count):
            return None
        # Indexed lookup first (O(1)); fall back to a scan when the index
        # misses (roles changed at runtime via a later mutation).
        with self._lock:
            dept_id = self._role_index.get(role)
            if dept_id is not None:
                return dept_id
            for dept in self._departments.values():
                if dept.auto_enabled and role in dept.roles:
                    self._role_index.setdefault(role, dept.id)
                    return dept.id
        return None

    # ── Directed transport ──

    def route_content(self, content_type: str, cell_count: int | None = None) -> dict:
        """Directed transport: decide which department handles *content_type*.

        When division is inactive, content stays in the generic pool (no
        department split). Routing matches content_type against each
        department's dept_type (or its roles) — a testing department is one
        configurable case, not a hardcoded one.
        """
        if not self.active(cell_count):
            return {"success": True, "routed": False, "department": "", "content_type": content_type}
        with self._lock:
            dept = None
            # Fast path: exact dept_type match via the type index (O(1)).
            dept_id = self._type_index.get(content_type)
            if dept_id is not None:
                dept = self._departments.get(dept_id)
            # Fallback: scan for a role/scope match (dept_type not indexed
            # because it is not any department's type).
            if dept is None or not dept.auto_enabled:
                dept = None
                for d in self._departments.values():
                    if not d.auto_enabled:
                        continue
                    # Phase C: permission_scope participates in matching — a
                    # content type listed in a department's scope belongs to it
                    # even when it is not the dept_type nor a role.
                    if content_type == d.dept_type or content_type in d.roles or content_type in d.permission_scope:
                        dept = d
                        break
        if dept is None:
            return {"success": True, "routed": False, "department": "", "content_type": content_type}
        # Phase C permission boundary: a department with an explicit
        # permission_scope refuses content types outside it (not just
        # unmapped — an active scope is a hard boundary).
        if dept.permission_scope and content_type not in dept.permission_scope:
            return {
                "success": True,
                "routed": False,
                "department": dept.id,
                "content_type": content_type,
                "refused": True,
                "reason": f"{content_type!r} outside {dept.id} permission scope {dept.permission_scope}",
            }
        return {
            "success": True,
            "routed": True,
            "department": dept.id,
            "roles": list(dept.roles),
            "dept_type": dept.dept_type,
            "cell_identity": dept.cell_identity,
            "content_type": content_type,
        }

    def status(self, cell_count: int | None = None) -> dict:
        """Return department division status."""
        with self._lock:
            dept_ids = sorted(self._departments.keys())
        return {
            "enabled": self.enabled(),
            "active": self.active(cell_count),
            "cell_count": cell_count if cell_count is not None else self.cell_count(),
            "threshold": CELL_DEPARTMENT_MIN,
            "departments": dept_ids,
            "types": list(DEPARTMENT_TYPES),
        }


def suggest_department(intent: str, domain: str = "") -> str:
    """L3A-assisted department designation from a user intent.

    Reuses the generic three-identity matching (build/test/review) to
    suggest which department type a card's intent belongs to. This is a
    *suggestion* — the user (or L3A after interpreting the intent) may
    override it; the final department type is config-driven.

    Args:
        intent: User intent / card title text.
        domain: Optional card domain hint.

    Returns:
        One of DEPARTMENT_TYPES ("general" when nothing matches).
    """
    try:
        from l3.bus.htn_planner import match_identity

        identity = match_identity(intent, domain)
        if identity in DEPARTMENT_TYPES:
            return identity
    except Exception as e:
        logger.debug("department: suggest failed: %s", e)
    return DEPARTMENT_TYPE_DEFAULT


def model_role_for(dept_type: str) -> str:
    """Resolve the model_spec executor name for a department type (D4).

    Phase C de-hardcoding: a registered department may override its executor
    via ``departments.yaml`` ``executor:``; otherwise the built-in fallback
    applies (review -> review, build/test -> build, unknown -> default). The
    model names themselves stay config data (``model_spec.*``) — never
    hardcoded here.

    Args:
        dept_type: One of DEPARTMENT_TYPES (build/test/review/...).

    Returns:
        The model_spec executor name to resolve ("build"/"review"/...).
    """
    # Config-driven override first: any registered department whose id or
    # dept_type matches and declares an executor wins.
    try:
        mgr = get_department_manager()
        with mgr._lock:
            for dept in mgr._departments.values():
                if dept.executor and (dept.id == dept_type or dept.dept_type == dept_type):
                    return dept.executor
    except Exception as e:
        logger.debug("department: executor override lookup skipped: %s", e)
    if dept_type == "review":
        return "review"
    if dept_type in ("build", "test"):
        return "build"
    return "default"


_manager: DepartmentManager | None = None


def get_department_manager() -> DepartmentManager:
    """Get the global DepartmentManager singleton."""
    global _manager
    if _manager is None:
        _manager = DepartmentManager()
    return _manager


def reset_department_manager() -> None:
    """Reset the singleton (used by tests)."""
    global _manager
    _manager = None
