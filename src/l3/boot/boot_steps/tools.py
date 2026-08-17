"""Boot steps — tool registry load and RecordCenter init.

Extracted from ``boot_steps.py``.  ``_load_tools`` loads the tools.yaml
definitions into TOOL_REGISTRY; ``_init_record_center`` warms the
RecordCenter and bridges it to StatsCenter.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _load_tools() -> dict:
    """Load tool definitions from tools.yaml into TOOL_REGISTRY."""
    try:
        from l3.tool_system.tool_config import ToolConfig

        n = ToolConfig.load()
        dynamic = _load_dynamic_tools()
        if not dynamic.get("success", False):
            return {"success": False, "error": dynamic.get("error", "dynamic tool load failed")}
        if not _register_g1_whitelist():
            return {"success": False, "error": "G1 whitelist registration failed"}
        _register_capability_executor()
        return {"success": True, "tools": n + int(dynamic.get("tools", 0) or 0), "dynamic": dynamic}
    except Exception as e:
        logger.warning("tool_config load failed: %s", e)
        return {"success": False, "error": str(e)}


def _register_g1_whitelist() -> bool:
    """Populate the GateChain G1 whitelist from the loaded tool registry.

    W2.3: without this, G1 sees an empty whitelist and (now fail-closed)
    BLOCKs every tool call. Registration must happen once per boot, after
    the registry is populated.
    """
    try:
        from l1.kernel.gatechain import get_gatechain
        from l3.tool_system.tool_registry import TOOL_REGISTRY

        names = list(TOOL_REGISTRY.all_names()) if hasattr(TOOL_REGISTRY, "all_names") else list(TOOL_REGISTRY.keys())
        if not names:
            logger.warning("boot: G1 whitelist empty — tool registry has no tools")
            return False
        gatechain = get_gatechain()
        if hasattr(gatechain, "replace_tools"):
            gatechain.replace_tools(names)
        else:
            gatechain.register_tools(names)
        logger.info("boot: G1 whitelist populated with %d tools", len(names))
        return True
    except Exception as e:
        logger.warning("boot: G1 whitelist registration failed: %s", e)
        return False


def _register_capability_executor() -> None:
    """Wire the kernel invoke-capability syscall to the gated pipeline.

    W6.1: boot is the ONLY place that connects the L1 capability seam to
    the L3 ToolPipeline adapter; boundary callers (L2 shell, API/MCP) go
    through ``l1.kernel.invoke_capability`` so the Rust rewrite can replace
    the adapter without touching any caller.
    """
    try:
        from l1.kernel.capability import register_capability_executor
        from l3.tool_system.invoke import invoke_gated

        def _executor(name, args, agent_id="", domain="", nature="", interactive=False) -> dict:
            return invoke_gated(
                name,
                args,
                agent_id=agent_id,
                domain=domain,
                nature=nature,
                interactive=interactive,
            )

        register_capability_executor(_executor)
        logger.info("boot: capability executor wired to ToolPipeline")
    except Exception as e:
        logger.warning("boot: capability executor wiring failed: %s", e)


def _load_dynamic_tools() -> dict:
    """Load dynamic tool specs from config/discovery/tool_registry.yaml.

    Each top-level key is a tool name; the value carries ``ring`` plus the
    ToolConfig definition fields (description/handler/params/danger/...).
    Registration goes through ToolConfig.register_from_dict so the ring
    whitelist and the dynamic cap are enforced at boot too.
    """
    from pathlib import Path

    import yaml

    from l3.tool_system.tool_config import ToolConfig

    path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "discovery" / "tool_registry.yaml"
    if not path.exists():
        logger.info("dynamic tools: no %s — skipped", path.name)
        return {"success": True, "tools": 0}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("dynamic tools: parse failed: %s", e)
        return {"success": False, "error": str(e)}
    loaded = 0
    failed = []
    for name, defn in data.items():
        if not isinstance(defn, dict):
            continue
        definition = dict(defn)
        ring = definition.pop("ring", "ring_1")
        r = ToolConfig.register_from_dict(name, definition, ring=ring)
        if r.get("success"):
            loaded += 1
        else:
            failed.append(f"{name}: {r.get('error', '?')}")
    if failed:
        logger.warning("dynamic tools: %d failed — %s", len(failed), "; ".join(failed[:5]))
    logger.info("dynamic tools: loaded %d from %s", loaded, path.name)
    return {"success": True, "tools": loaded, "failed": failed}


def _load_dvg() -> dict:
    """Load the DVG (tool dependency graph) from config/discovery/dvg.yaml.

    Populates the DvgGraph singleton with tool → prerequisite edges so
    tool-pipeline preflight and the parallel matrix can order/validate
    dispatch. Cycles are rejected per-tool by DvgGraph.register_tool_deps.
    """
    from pathlib import Path

    import yaml

    from l3.tool_system.dvg import get_dvg

    path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "discovery" / "dvg.yaml"
    dvg = get_dvg()
    dvg.clear()
    if not path.exists():
        logger.info("dvg: no %s — skipped", path.name)
        return {"success": True, "tools": 0}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("dvg: parse failed: %s", e)
        return {"success": False, "error": str(e)}
    loaded = 0
    rejected = []
    for name, deps in data.items():
        if not isinstance(deps, list):
            continue
        if dvg.register_tool_deps(str(name), [str(d) for d in deps]):
            loaded += 1
        else:
            rejected.append(str(name))
    if rejected:
        logger.warning("dvg: %d rejected (cycle?) — %s", len(rejected), ", ".join(rejected[:5]))
    try:
        from l3.tool_system.tool_registry import get_registry

        for spec in get_registry().list_tools(include_muted=True):
            deps = spec.metadata.get("deps", []) if getattr(spec, "metadata", None) else []
            if deps:
                dvg.register_tool_deps(spec.name, [str(dep) for dep in deps])
    except Exception as e:
        logger.debug("dvg: dynamic dependency restore skipped: %s", e)
    logger.info("dvg: loaded %d dependency nodes from %s", loaded, path.name)
    return {"success": True, "tools": loaded, "rejected": rejected}


def _init_record_center() -> dict:
    """Init RecordCenter and bridge to StatsCenter."""
    try:
        from l3.services.record_center import get_record_center

        rc = get_record_center()
        rc.bridge_stats()
        logger.info("record_center: initialized, export_dir=%s", rc._export_dir)
        return {"success": True}
    except Exception as e:
        logger.warning("record_center init: %s", e)
        return {"success": False, "error": str(e)}
