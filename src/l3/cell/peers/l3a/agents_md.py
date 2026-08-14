"""L3A agents-md pipeline — generate a project handbook (AGENTS.md) for any project.

Decision layer entry point: an L3A session (or L2 ``/agents-md``) triggers
collection of structural facts about the current project (layers, commands,
params constants, key paths), assembles them into an agent-facing handbook,
writes it through the Cell sandbox, and optionally distills reusable rules
back into the skill system (global scope) via the R4Agent.

The collector below is pure filesystem scanning — no LLM, no sandbox, no L4
imports — so it stays safe under the layer-import constraint and can run in
any process (L3A session, L2 command handler, unit test).
"""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path

from l1.kernel.params.system import HASH_TRUNC_MEDIUM, LOG_TRUNC_80

logger = logging.getLogger(__name__)

# Layer table: relative src/ dir -> display name. Mirrors scripts/py/gen-doc-stats.py.
_LAYER_DIRS: dict[str, str] = {
    "l1/kernel": "L1 Kernel",
    "l2": "L2 Shell",
    "l3": "L3 Cell",
    "l4": "L4 Bridge",
    "l5": "L5 User",
}

# Sub-layer table for the hotspot stats (mirrors gen-doc-stats.py).
_SUBLAYER_DIRS: dict[str, str] = {
    "l3/cell/peers/l3a": "L3A (peers)",
    "l3/memory": "L3 Memory",
    "l3/card": "L3 Card",
    "l3/services": "L3 Services",
    "l3/bus": "L3 Bus",
    "l3/agent": "L3 Agent",
    "l4/api_handlers": "L4 Handlers",
}

# Project-structure paths probed for the handbook's key-files section.
_KEY_PATHS: list[str] = [
    "config/praxis.yaml",
    "config/commands.yaml",
    "config/tools.yaml",
    ".praxis-rules.md",
    "locales/",
    "memories/",
    "config/skills/",
    ".praxis/skills/",
]


def _py_files(root: Path) -> list[Path]:
    """Return all .py files under root, skipping __pycache__."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in str(p))


def _count_lines(files: list[Path]) -> int:
    """Count total lines across files (best-effort, skips undecodable files)."""
    total = 0
    for p in files:
        try:
            total += sum(1 for _ in p.open(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return total


def _dir_stats(root: Path, rel: str) -> dict:
    """Return {"files": N, "lines": N} for src/<rel>, or zeroed dict when absent."""
    files = _py_files(root / rel)
    return {"files": len(files), "lines": _count_lines(files)}


def _count_params_constants(params_dir: Path) -> int:
    """Count module-level uppercase annotated constants via AST (gen-doc-stats style)."""
    consts = 0
    for p in _py_files(params_dir):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id.isupper():
                consts += 1
    return consts


def _find_project_root(start: str = "") -> str:
    """Locate the project root: the nearest ancestor of start holding src/.

    Falls back to start (or cwd) when no src/ ancestor is found, so the
    collector degrades gracefully outside a source checkout.
    """
    cur = Path(start or os.getcwd()).resolve()
    for _ in range(6):
        if (cur / "src").is_dir():
            return str(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    return str(Path(start or os.getcwd()).resolve())


def collect_project_info(project_root: str = "") -> dict:
    """Collect structural facts about a project for handbook generation.

    Args:
        project_root: Explicit project root; empty means auto-discover by
            walking up from cwd until a ``src/`` directory is found.

    Returns:
        Dict with ``project_root``, ``layers`` / ``sublayers`` (file+line
        stats per dir), ``params`` (module/constant counts), ``commands``
        (command count from commands.yaml), ``tests`` (file/line stats),
        and ``key_paths`` (existence probes). Pure filesystem scan, never
        raises.
    """
    root = Path(project_root or _find_project_root()).resolve()
    info: dict = {
        "project_root": str(root),
        "layers": {},
        "sublayers": {},
        "params": {"modules": 0, "constants": 0},
        "commands": 0,
        "tests": {"files": 0, "lines": 0},
        "key_paths": {},
    }

    src = root / "src"
    for rel, _name in _LAYER_DIRS.items():
        info["layers"][rel] = _dir_stats(src, rel)
    for rel, _name in _SUBLAYER_DIRS.items():
        info["sublayers"][rel] = _dir_stats(src, rel)

    params_dir = src / "l1/kernel/params"
    info["params"]["modules"] = len(_py_files(params_dir))
    info["params"]["constants"] = _count_params_constants(params_dir)

    commands_yaml = root / "config" / "commands.yaml"
    if commands_yaml.is_file():
        try:
            import yaml

            data = yaml.safe_load(commands_yaml.read_text(encoding="utf-8"))
            info["commands"] = len(data) if isinstance(data, dict) else 0
        except Exception:
            logger.debug("agents_md: commands.yaml parse failed", exc_info=True)

    info["tests"] = _dir_stats(root, "tests")

    for rel in _KEY_PATHS:
        info["key_paths"][rel] = (root / rel).exists()

    return info


def _cell_department_brief(cell_id: str) -> str:
    """Assemble the per-Cell department brief (dept declaration).

    Reads the config-driven department registry: which department owns this
    Cell (by its identity / roles), its type and description. Declarative —
    departments.yaml drives the content, never hardcoded. Returns "" when
    department division is inactive or the Cell has no matching department.
    """
    try:
        from l3.cell.department import get_department_manager

        mgr = get_department_manager()
        if not mgr.active():
            return ""
        dept_id = mgr.department_for_role(cell_id, cell_count=mgr.cell_count())
        if not dept_id:
            return ""
        with mgr._lock:
            dept = mgr._departments.get(dept_id)
        if dept is None:
            return ""
        roles = ", ".join(dept.roles or [])
        desc = dept.description or ""
        lines = [
            "## Cell department",
            "",
            f"- Department: `{dept_id}`",
            f"- Type: `{dept.dept_type}`",
            f"- Roles: {roles}" if roles else "- Roles: (none declared)",
            f"- Description: {desc}" if desc else "",
            "",
        ]
        return "\n".join(ln for ln in lines if ln)
    except Exception:
        return ""


def _constitution_brief() -> str:
    """Assemble a constitution digest for the Cell handbook.

    Loads the repo constitution (.praxis-rules.md) and lists its rules as
    constraints the Cell's department must obey — the handbook is
    subordinate to the constitution, never above it. Returns "" on any
    failure (degrade gracefully).
    """
    try:
        from l1.kernel.constitution import get_constitution

        c = get_constitution()
        loaded = c.load()
        if not loaded.get("success"):
            return ""
        rules = getattr(c, "_rules", []) or []
        # Every rule is load-bearing (territory.write, gatechain.all, ...);
        # no custom: prefix filtering — the full rule set is the digest.
        lines = ["## Constitution binding", ""]
        count = 0
        for r in rules:
            text = str(getattr(r, "description", "") or getattr(r, "text", "") or "")
            if text:
                lines.append(f"- {text}")
                count += 1
        if not count:
            return ""
        lines.append("")
        return "\n".join(lines)
    except Exception:
        return ""


def assemble_agents_md(info: dict, cell_id: str = "") -> str:
    """Assemble an AGENTS.md handbook from collected project facts.

    Produces a structural skeleton: title, quick-start placeholders,
    architecture tree with per-layer file/line stats, key numbers
    (params constants, commands, tests), key-path probes, and a
    conventions section left for LLM/human refinement. Every fact comes
    from ``collect_project_info`` — never invented.

    When ``cell_id`` is given, the handbook becomes a **per-Cell
    department brief** (``Cell-{cell_id}-Agents.md``): the Cell's declared
    department (dept type/roles/description) and a constitution digest are
    injected, so the Cell's peer agents carry their department brief and
    the constitutional constraints they must obey.
    """
    name = Path(info["project_root"]).name
    title = f"# {name} — Cell {cell_id} Agents Handbook" if cell_id else f"# {name} — Agent Handbook"
    lines = [
        title,
        "",
        "> Generated by the Praxis L3A agents-md pipeline (agent-facing).",
        "> Regenerate: `/agents-md generate` — facts below are live-scanned.",
        "",
        "## Quick start",
        "",
        "- *TODO: install, build, and run commands (verify against the repo).*",
        "",
        "## Test commands",
        "",
        "- *TODO: exact test/lint/format commands (verify before asserting).*",
        "",
        "## Architecture",
        "",
    ]
    for rel, disp in _LAYER_DIRS.items():
        st = info["layers"].get(rel, {"files": 0, "lines": 0})
        lines.append(f"- {rel}/ — {disp}: {st['files']} files, {st['lines']} lines")
    lines.append("")
    lines.append("### Hotspots")
    lines.append("")
    for rel, disp in _SUBLAYER_DIRS.items():
        st = info["sublayers"].get(rel, {"files": 0, "lines": 0})
        lines.append(f"- {rel}/ — {disp}: {st['files']} files, {st['lines']} lines")
    lines.append("")
    lines.append("## Key numbers (live-scanned)")
    lines.append("")
    lines.append(f"- Params constants: {info['params']['constants']} across {info['params']['modules']} modules")
    lines.append(f"- L2 shell commands: {info['commands']}")
    lines.append(f"- Tests: {info['tests']['files']} files, {info['tests']['lines']} lines")
    lines.append("")
    lines.append("## Key files / paths")
    lines.append("")
    for rel, exists in info["key_paths"].items():
        lines.append(f"- `{rel}` — {'present' if exists else 'absent'}")
    lines.append("")
    lines.append("## Conventions")
    lines.append("")
    lines.append("- *TODO: code style, commit rules, and gotchas (LLM/human pass).*")
    lines.append("")
    if cell_id:
        dept_brief = _cell_department_brief(cell_id)
        if dept_brief:
            lines.append(dept_brief)
        const_brief = _constitution_brief()
        if const_brief:
            lines.append(const_brief)
    return "\n".join(lines)


def write_agents_md(content: str, agent_id: str = "l3a", cell_id: str = "", project_root: str = "") -> dict:
    """Write the assembled handbook via the sandbox (constitution §4.5).

    With a ``cell_id`` the file is named ``Cell-{cell_id}-Agents.md`` — a
    per-Cell department brief bound to that Cell's domain; without one it
    falls back to the project-level ``AGENTS.md``. All modifications go
    through the sandbox: staged with per-hunk attribution, then flushed.

    Returns the flush result dict (``success`` + sandbox details).
    """
    from l4.sandbox import get_manager

    filename = f"Cell-{cell_id}-Agents.md" if cell_id else "AGENTS.md"
    mgr = get_manager()
    cid = cell_id or "agents-md"
    sb = mgr.get_cell(cid)
    if sb is None:
        mgr.create_cell(cid, project_root or _find_project_root())
        sb = mgr.get_cell(cid)
    if sb is None:
        return {"success": False, "error": "sandbox cell unavailable"}
    r = sb.write(filename, content, agent_id, task_id="agents-md", tool_name="agents_md")
    if not r.get("success"):
        return r
    # write() stages a "pending" entry; flush() only copies "staged" ones,
    # so promote the entry before flushing (sandbox write→stage→flush chain).
    st = sb.stage(agent_id)
    if not st.get("success"):
        return st
    flushed = sb.flush(agent_id, [filename])
    # Mirror the handbook into the L3 tiered cache so the L3 agent loop can
    # inject it without crossing into L4 (layer-import constraint).
    try:
        from l3.memory.tiered_cache import get_tiered_cache

        get_tiered_cache().index_archive(f"cell:{cid}:agents_md", {"filename": filename, "content": content})
    except Exception as e:
        logger.debug("agents_md: tiered cache mirror skipped: %s", e)
    return flushed


def _fallback_generic_skill(intent: str, scope: str = "global") -> dict:
    """Register a rule-based template skill when the LLM engine is unavailable.

    Keeps the generic-handbook pipeline functional without an LLM: the skill
    carries the writing-for-agents essence (explore → verify → write in
    place) plus the caller's intent as a versioned prompt, persisted with
    the same round-trip frontmatter as LLM-evolved skills.
    """
    import hashlib
    import time

    from l1.kernel.skill import get_skill_manager
    from l3.memory.r4_agent import get_r4_agent

    fp = hashlib.md5(intent.encode("utf-8")).hexdigest()[:HASH_TRUNC_MEDIUM]
    name = f"agents-md-{int(time.time())}"
    description = f"Generic project-handbook generation ({intent[:LOG_TRUNC_80]}) [{fp}]"
    prompt = (
        "Generate or refresh the project handbook (AGENTS.md). Explore the "
        "codebase first (build/test/lint commands, layout, conventions, "
        "gotchas), verify every count/path/command against the code, then "
        "write in place preserving existing useful content. Intent: "
        f"{intent.strip()}"
    )
    r4 = get_r4_agent()
    sm = get_skill_manager()
    r = sm.create(
        name=name,
        description=description,
        prompt=prompt,
        tags=["agents-md", "evolved"],
        allowed_tools=["read_file", "list_dir", "write_file", "grep_search"],
        internal=True,
    )
    if not r.get("success"):
        return r
    r4._persist_skill_md(
        name=name,
        description=description,
        prompt=prompt,
        tags=["agents-md", "evolved"],
        allowed_tools=["read_file", "list_dir", "write_file", "grep_search"],
        scope=scope,
    )
    return {"success": True, "skill": name, "scope": scope, "fallback": True}


def evolve_generic_skill(intent: str, cell_id: str = "", scope: str = "global") -> dict:
    """Distill a reusable, project-agnostic skill from the handbook pipeline.

    Delegates to ``R4Agent.evolve_skill`` (LLM skill architect) with an
    explicit global scope so the evolved skill travels with the machine and
    applies to any project; when the LLM is unavailable, falls back to a
    rule-based template skill so the generic end of the pipeline still
    completes. Returns the evolution result dict.
    """
    from l3.memory.r4_agent import get_r4_agent

    r4 = get_r4_agent()
    r = r4.evolve_skill(intent, cell_id=cell_id, scope=scope)
    if r.get("success"):
        return r
    logger.info("agents_md: LLM evolve_skill unavailable (%s), using fallback", r.get("error", "?"))
    return _fallback_generic_skill(intent, scope=scope)


def generate_agents_md(agent_id: str = "l3a", cell_id: str = "", project_root: str = "", evolve: bool = True) -> dict:
    """Full pipeline: collect → assemble → sandbox write → (optional) generalize.

    Runs the generic handbook pipeline for any project. When ``evolve`` is
    true, also distills a reusable skill via ``evolve_generic_skill`` so the
    method survives beyond this project. Returns a summary dict.
    """
    info = collect_project_info(project_root)
    md = assemble_agents_md(info, cell_id=cell_id)
    w = write_agents_md(md, agent_id=agent_id, cell_id=cell_id, project_root=info["project_root"])
    result: dict = {"success": bool(w.get("success")), "write": w}
    if not w.get("success"):
        result["error"] = w.get("error", "sandbox write failed")
        return result
    result["stats"] = {
        "project_root": info["project_root"],
        "commands": info["commands"],
        "params_constants": info["params"]["constants"],
        "tests_files": info["tests"]["files"],
        "layers": {k: v["files"] for k, v in info["layers"].items()},
    }
    if evolve:
        intent = (
            "Generate or refresh the project handbook (AGENTS.md) for any "
            "project: explore build/test/lint commands, directory layout, "
            "conventions and gotchas; verify every count/path against the "
            "code; write in place preserving existing useful content."
        )
        result["evolved"] = evolve_generic_skill(intent, cell_id=cell_id)
    return result
