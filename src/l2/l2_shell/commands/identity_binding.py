"""L2 shell command — per-Cell identity binding management.

Subcommands: list [cell] | set <cell> <role> <fragment> [--tags a,b] [--max N]
[--as writer] | clear <cell> [--as writer].

Writes pass the IdentityBindingManager write gate — the ``--as`` writer role
must be declared explicitly (no privileged default; see the P1 review fix).
"""

from __future__ import annotations

from l2.i18n import t as _t


def _cmd_identity_binding(args: list[str], session=None) -> dict:
    """Manage per-Cell identity bindings: list | set | clear | define."""
    sub = args[0] if args else "list"
    if sub == "list":
        return _ib_list(args)
    if sub == "set":
        return _ib_set(args)
    if sub == "clear":
        return _ib_clear(args)
    if sub == "define":
        return _ib_define(args)
    return {"success": False, "error": f"unknown subcommand: {sub} (list|set|clear|define)"}


def _ib_define(args: list[str]) -> dict:
    """Set (or resolve) a registered identity's detailed definition.

    Usage: identity-binding define <cell_id> <role> [--text "definition"]
    Without --text, resolves the effective definition (custom or built-in).
    """
    from l1.kernel.identity_binding import get_identity_binding_manager

    if len(args) < 3:
        return {"success": False, "error": _t("shell.app_error.usage_identity_binding_define")}
    cell_id, role = args[1], args[2]
    mgr = get_identity_binding_manager()
    text = ""
    rest = args[3:]
    if "--text" in rest:
        idx = rest.index("--text")
        if idx + 1 < len(rest):
            text = rest[idx + 1]
    if not text:
        return {"success": True, "cell_id": cell_id, "role": role, "definition": mgr.resolve_definition(cell_id, role)}
    writer_role = ""
    if "--writer" in rest:
        widx = rest.index("--writer")
        if widx + 1 < len(rest):
            writer_role = rest[widx + 1]
    if not writer_role:
        return {"success": False, "error": _t("shell.app_error.identity_binding_writer_required")}
    existing = mgr.get_binding(cell_id, role)
    if existing is None:
        return {"success": False, "error": f"no binding for {cell_id}/{role} — bind first"}
    return mgr.bind(
        cell_id,
        role,
        existing.prompt_fragment,
        domain_tags=existing.domain_tags,
        max_chars=existing.max_chars,
        writer_role=writer_role,
        definition=text,
    )


def _ib_list(args: list[str]) -> dict:
    """List bindings for one Cell (or all Cells)."""
    from l1.kernel.identity_binding import get_identity_binding_manager

    mgr = get_identity_binding_manager()
    cell_id = args[1] if len(args) > 1 else ""
    if cell_id:
        return {"success": True, "cell_id": cell_id, "bindings": mgr.bindings_for_cell(cell_id)}
    return {"success": True, "cells": {c: mgr.bindings_for_cell(c) for c in sorted(mgr.cell_ids())}}


def _ib_set(args: list[str]) -> dict:
    """Bind a role in a Cell to a strict-role prompt fragment."""
    from l1.kernel.identity_binding import get_identity_binding_manager

    if len(args) < 4:
        return {
            "success": False,
            "error": _t("shell.app_error.usage_identity_binding_set"),
        }
    cell_id, role, fragment = args[1], args[2], args[3]
    tags, max_chars, writer_role, opt_err = _ib_options(args[4:])
    if opt_err:
        return {"success": False, "error": opt_err}
    if not writer_role:
        return {"success": False, "error": _t("shell.app_error.identity_binding_writer_required")}
    return get_identity_binding_manager().bind(
        cell_id, role, fragment, domain_tags=tags, max_chars=max_chars, writer_role=writer_role
    )


def _ib_clear(args: list[str]) -> dict:
    """Drop all role bindings for a Cell."""
    from l1.kernel.identity_binding import get_identity_binding_manager

    if len(args) < 2:
        return {"success": False, "error": _t("shell.app_error.usage_identity_binding_clear")}
    writer_role = args[3] if len(args) > 3 and args[2] == "--as" else ""
    if not writer_role:
        return {"success": False, "error": _t("shell.app_error.identity_binding_writer_required")}
    return get_identity_binding_manager().clear_cell(args[1], writer_role=writer_role)


def _ib_options(rest: list[str]) -> tuple[list[str], int, str, str]:
    """Parse --tags/--max/--as options; returns (tags, max_chars, writer_role, error)."""
    tags: list[str] = []
    max_chars = 0
    writer_role = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--tags" and i + 1 < len(rest):
            tags = [t for t in rest[i + 1].split(",") if t]
            i += 2
        elif rest[i] == "--max" and i + 1 < len(rest):
            try:
                max_chars = int(rest[i + 1])
            except ValueError:
                return tags, 0, "", "--max must be an integer"
            i += 2
        elif rest[i] == "--as" and i + 1 < len(rest):
            writer_role = rest[i + 1]
            i += 2
        else:
            return tags, 0, "", f"unknown option: {rest[i]}"
    return tags, max_chars, writer_role, ""
