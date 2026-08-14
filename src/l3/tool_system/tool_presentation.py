"""Tool presentation mode — how the tool registry presents tools to the model.

The presentation mode selects the model-facing shape of the tool registry:
``native`` contributes OpenAI-style function-calling schemas (the default),
``code`` exposes only the reserved ``run_code`` transport plus a generated
SDK so the model writes a program to compose multi-step tool calls (Code
Mode / PTC), and ``both`` presents native schemas and the transport
together. The mode resolves from a runtime override (API / L2 Shell) first,
then ``config/discovery/*.yaml``, then the params default. Switching mode
records evidence on the ambient chain (it is a capability change, not a
security downgrade, so no risk confirmation is required).

The ``CodeRenderer`` seam is language-agnostic: each registered renderer
generates the SDK declarations and usage instructions for its language.
Python ships as the first renderer; TypeScript / Rust slots are left open
for the multi-language roadmap (``docs/design/praxis-frontend-kernel-roadmap.md``).
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.tool import (
    CODE_RUN_DEFAULT_LANGUAGE,
    TOOL_PRESENTATION_CONFIG_KEY,
    TOOL_PRESENTATION_DEFAULT,
    TOOL_PRESENTATION_MODES,
)
from l1.kernel.paths import get_paths as _gp
from l1.kernel.platform import get_temp_dir as _get_temp_dir

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"mode": None}
_lock = threading.RLock()

# Language → CodeRenderer instance registry (first-party + user plugins).
_renderers: dict[str, CodeRenderer] = {}
_renderers_lock = threading.RLock()


class CodeRenderer(ABC):
    """Language-specific SDK renderer for the ``run_code`` transport.

    A renderer owns how the tool registry's visible capabilities are
    declared and explained in one programming language. The registry calls
    ``render_sdk`` to obtain the SDK declarations and ``render_usage`` for
    the fixed usage instructions; both join the system-prompt assembly.
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Language name this renderer targets (e.g. "python", "typescript")."""

    @abstractmethod
    def render_sdk(self, tools: list[dict]) -> str:
        """Render SDK declarations for the visible tools.

        Args:
            tools: list of tool descriptors (name, description, parameters).

        Returns:
            SDK declaration text (deterministic, byte-stable for caching).
        """

    @abstractmethod
    def render_usage(self) -> str:
        """Render the fixed usage instructions for writing run_code programs."""


class PythonCodeRenderer(CodeRenderer):
    """Python SDK renderer — the first language on the multi-language roadmap."""

    @property
    def language(self) -> str:
        return "python"

    def render_sdk(self, tools: list[dict]) -> str:
        """Render a Python SDK: one typed callable per visible tool."""
        lines = ["# Generated tool SDK — call these bindings from your program.", "from typing import Any"]
        for tool in sorted(tools, key=lambda t: t.get("name", "")):
            name = tool.get("name", "")
            desc = tool.get("description", "")
            params = tool.get("parameters") or []
            args = ", ".join(f"{p.get('name', 'arg')}: Any" for p in params)
            lines.append(f"def {name}({args}) -> Any:")
            lines.append(f'    """{desc}"""')
            lines.append("    ...")
        return "\n".join(lines)

    def render_usage(self) -> str:
        """Render the fixed run_code usage instructions for Python."""
        return (
            "Write a Python program that calls the SDK bindings above to "
            "compose multi-step tool calls (loops, conditionals, fan-out are "
            "allowed). Only the program's print() output and return value are "
            "returned to the conversation; every binding call is recorded on "
            "the tool audit chain automatically."
        )


def register_renderer(renderer: CodeRenderer) -> bool:
    """Register a code renderer for its language (first registration wins).

    Args:
        renderer: CodeRenderer instance with a unique language name.

    Returns:
        True when registered, False when the language is already taken.
    """
    with _renderers_lock:
        lang = renderer.language
        if lang in _renderers:
            return False
        _renderers[lang] = renderer
        return True


def get_renderer(language: str = "") -> CodeRenderer | None:
    """Return the renderer for a language, falling back to the default.

    Args:
        language: target language; empty means the configured default.

    Returns:
        The registered renderer, or None when none is registered.
    """
    with _renderers_lock:
        if not language:
            language = CODE_RUN_DEFAULT_LANGUAGE
        return _renderers.get(language)


def get_presentation_mode() -> str:
    """Return the effective presentation mode (override → config → default)."""
    with _lock:
        override = _state["mode"]
    if override in TOOL_PRESENTATION_MODES:
        return override
    static = str(get_tool_config(TOOL_PRESENTATION_CONFIG_KEY, TOOL_PRESENTATION_DEFAULT)).lower()
    return static if static in TOOL_PRESENTATION_MODES else TOOL_PRESENTATION_DEFAULT


def set_presentation_mode(mode: str, source: str = "api") -> dict:
    """Switch the tool presentation mode at runtime.

    Args:
        mode: one of TOOL_PRESENTATION_MODES (native / code / both).
        source: caller identity ("api" / "shell" / ...) for the audit trail.

    Returns:
        dict with success flag and effective mode.
    """
    mode = str(mode or "").lower()
    if mode not in TOOL_PRESENTATION_MODES:
        return {
            "success": False,
            "error": f"invalid presentation mode: {mode}",
            "modes": list(TOOL_PRESENTATION_MODES),
        }
    with _lock:
        _state["mode"] = mode
        _state["source"] = source
    try:
        from l3.tool_system.security_evidence import DECISION_CHANGE, record_evidence

        record_evidence(
            phase="presentation",
            gate="tool_presentation_mode",
            decision=DECISION_CHANGE,
            target=f"mode:{mode}",
            source=source,
            tags={},
            chain_kind="ambient",
        )
    except Exception:
        logger.debug("tool_presentation: evidence recording skipped", exc_info=True)
    return {"success": True, "mode": mode, "source": source}


def reset_presentation_mode() -> dict:
    """Clear the runtime override; effective mode returns to static config."""
    with _lock:
        _state["mode"] = None
        _state["source"] = "config"
    return {"success": True, "mode": get_presentation_mode(), "source": "config"}


def presentation_status() -> dict:
    """Return the current mode plus the switchable matrix and renderers."""
    with _lock:
        source = _state.get("source", "config")
    with _renderers_lock:
        languages = sorted(_renderers.keys())
    return {
        "mode": get_presentation_mode(),
        "source": source,
        "modes": list(TOOL_PRESENTATION_MODES),
        "renderers": languages,
    }


def cell_program_dir(cell_id: str) -> Path:
    """Return the per-Cell run_code program cache directory (created lazily).

    The directory lives under the platform temp root, namespaced by cell id,
    mirroring the sandbox layout so every Cell domain owns its program area
    and the area is reclaimed with the Cell lifecycle.

    Args:
        cell_id: Cell identifier owning this program cache area.

    Returns:
        Path to the per-Cell run_code program cache directory.
    """
    root = Path(_get_temp_dir()) / "praxis-toolpres"
    return root / (cell_id or _gp().layout_dirs[0] if _gp().layout_dirs else "default")


# Register the first-party Python renderer at import time so get_renderer()
# always has a default for the shipped language.
register_renderer(PythonCodeRenderer())
