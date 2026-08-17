"""Identity binding API handlers — per-Cell strict-role binding CRUD.

Phase 1 config surface: GET lists bindings, PUT binds a role to a
strict-role prompt fragment, DELETE unbinds. All writes pass the
IdentityBindingManager write gate — external callers must declare an
explicit writer role (default ``l3``).
"""

from __future__ import annotations


def handle_identity_binding_get(body: dict | None = None) -> dict:
    """GET /api/v2/identity-binding — list bindings for a Cell (or all cells).

    Body: ``{"cell_id": "cell-1"}`` (omit for all). Prompt fragments are
    excluded from the response; only structured metadata is exposed.
    """
    from l1.kernel.identity_binding import get_identity_binding_manager

    b = body or {}
    mgr = get_identity_binding_manager()
    cell_id = b.get("cell_id", "")
    if cell_id:
        return {"success": True, "cell_id": cell_id, "bindings": mgr.bindings_for_cell(cell_id)}
    cells = {cid: mgr.bindings_for_cell(cid) for cid in sorted(mgr.cell_ids())}
    return {"success": True, "cells": cells}


def handle_identity_binding_put(body: dict | None = None) -> dict:
    """PUT /api/v2/identity-binding — bind a role in a Cell.

    Body: ``{"cell_id", "role", "fragment", "domain_tags"?, "max_chars"?,
    "writer_role"?}``. The fragment is truncated to the effective character
    limit (IDENTITY_BINDING_MAX_CHARS by default).
    """
    from l1.kernel.identity_binding import get_identity_binding_manager

    b = body or {}
    cell_id = b.get("cell_id", "")
    role = b.get("role", "")
    fragment = b.get("fragment", "")
    if not cell_id or not role:
        return {"success": False, "error": "cell_id and role required"}
    if not fragment:
        return {"success": False, "error": "fragment required"}
    # The caller identity must come from the gateway-injected field
    # (body["_user_id"], set by _route_dispatch), never from client-asserted
    # body keys. writer_role must be declared explicitly — there is no
    # privileged default, so a caller without an accepted role is denied.
    writer_role = b.get("writer_role", "")
    if not writer_role:
        return {"success": False, "error": "writer_role required (l3/deployer or ring>=3)"}
    domain_tags = b.get("domain_tags") or []
    if not isinstance(domain_tags, list):
        domain_tags = [str(domain_tags)]
    raw_max = b.get("max_chars", 0)
    try:
        max_chars = int(raw_max) if raw_max else 0
    except (TypeError, ValueError):
        return {"success": False, "error": "max_chars must be a positive integer"}
    mgr = get_identity_binding_manager()
    return mgr.bind(
        cell_id,
        role,
        str(fragment),
        domain_tags=domain_tags,
        max_chars=max_chars,
        agent_id=b.get("_user_id", ""),
        writer_role=writer_role,
        definition=str(b.get("definition", "") or ""),
    )


def handle_identity_definition_get(body: dict | None = None) -> dict:
    """GET /api/v2/identity-binding/definition — resolve the effective definition.

    Body: ``{"cell_id", "role"}``. Returns the custom definition when the
    binding set one, otherwise the built-in generalized definition from the
    prompt registry (``identity_definition.<role>``).
    """
    from l1.kernel.identity_binding import get_identity_binding_manager

    b = body or {}
    cell_id = b.get("cell_id", "")
    role = b.get("role", "")
    if not cell_id or not role:
        return {"success": False, "error": "cell_id and role required"}
    mgr = get_identity_binding_manager()
    return {"success": True, "cell_id": cell_id, "role": role, "definition": mgr.resolve_definition(cell_id, role)}


def handle_identity_definition_put(body: dict | None = None) -> dict:
    """PUT /api/v2/identity-binding/definition — set a custom identity definition.

    Body: ``{"cell_id", "role", "definition", "writer_role"?}``. The
    definition is capped by ``IDENTITY_DEFINITION_MAX_CHARS`` (default 300);
    a bound role is required (bind first via PUT /identity-binding).
    """
    from l1.kernel.identity_binding import get_identity_binding_manager

    b = body or {}
    cell_id = b.get("cell_id", "")
    role = b.get("role", "")
    definition = b.get("definition", "")
    if not cell_id or not role:
        return {"success": False, "error": "cell_id and role required"}
    if not definition:
        return {"success": False, "error": "definition required"}
    writer_role = b.get("writer_role", "")
    if not writer_role:
        return {"success": False, "error": "writer_role required (l3/deployer or ring>=3)"}
    mgr = get_identity_binding_manager()
    existing = mgr.get_binding(cell_id, role)
    if existing is None:
        return {"success": False, "error": f"no binding for {cell_id}/{role} — bind first"}
    # Rebind with the same fragment but the new definition (write gate applies).
    return mgr.bind(
        cell_id,
        role,
        existing.prompt_fragment,
        domain_tags=existing.domain_tags,
        max_chars=existing.max_chars,
        agent_id=b.get("_user_id", ""),
        writer_role=writer_role,
        definition=definition,
    )


def handle_identity_binding_delete(body: dict | None = None) -> dict:
    """DELETE /api/v2/identity-binding — unbind a role from a Cell."""
    from l1.kernel.identity_binding import get_identity_binding_manager

    b = body or {}
    cell_id = b.get("cell_id", "")
    role = b.get("role", "")
    if not cell_id or not role:
        return {"success": False, "error": "cell_id and role required"}
    writer_role = b.get("writer_role", "")
    if not writer_role:
        return {"success": False, "error": "writer_role required (l3/deployer or ring>=3)"}
    mgr = get_identity_binding_manager()
    return mgr.unbind(
        cell_id,
        role,
        agent_id=b.get("_user_id", ""),
        writer_role=writer_role,
    )


def handle_identity_set_get(body: dict | None = None) -> dict:
    """GET /api/v2/identity/set — resolve an Agent's generic identity set.

    Body: ``{"cell_id": "cell-1", "role": "tester"}``. Returns the subset
    of the three generic identity fields (build/test/review) for the
    Agent entity — narrowed by binding domain_tags, else the full set.
    """
    from l1.kernel.identity_binding import get_identity_binding_manager

    b = body or {}
    cell_id = str(b.get("cell_id", ""))
    role = str(b.get("role", ""))
    if not cell_id or not role:
        return {"success": False, "error": "cell_id and role required"}
    identity_set = get_identity_binding_manager().identity_set_for(cell_id, role)
    return {"success": True, "cell_id": cell_id, "role": role, "identity_set": list(identity_set)}
