"""Tool system — tool pipeline, registry, policy, and configuration."""


def _lazy_import(name: str):
    import importlib

    return importlib.import_module(f"l3.tool_system.{name}")


def get_tool_spec():
    """Lazily return the ToolSpec class."""
    return _lazy_import("tool_spec").ToolSpec


def get_tool_ring():
    """Lazily return the ToolRing class."""
    return _lazy_import("tool_spec").ToolRing


def get_tool_registry():
    """Lazily return the module-level TOOL_REGISTRY."""
    return _lazy_import("tool_registry").TOOL_REGISTRY


def get_register():
    """Lazily return the tool registration function."""
    return _lazy_import("tool_registry").register


def get_tool_pipeline():
    """Lazily return the ToolPipeline class."""
    return _lazy_import("tool_pipeline").ToolPipeline


def get_pipeline():
    """Lazily return the pipeline accessor function."""
    return _lazy_import("tool_pipeline").get_pipeline


def get_tool_config():
    """Lazily return the ToolConfig class."""
    return _lazy_import("tool_config").ToolConfig
