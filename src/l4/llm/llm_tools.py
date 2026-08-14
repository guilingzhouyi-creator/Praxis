"""LLMToolsMixin — tool-definition conversion and single-tool execution.

Extracted from ``llm.py`` (LLMEngine).  Owns the ToolSpec → LLM
function-calling format conversion (``_tool_def_to_api``) and one tool
handler invocation (``_execute_one_tool``); the concrete ``LLMEngine``
composes it with the retry mixin and the engine core.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class LLMToolsMixin:
    """LLMToolsMixin — tool format conversion + single-tool execution."""

    @staticmethod
    def _execute_one_tool(tool_def, fn_args, call_id, fn_name, t_start: float = 0.0):
        if tool_def and tool_def.handler:
            result = tool_def.handler(fn_args, "")
            return {
                "name": fn_name,
                "arguments": fn_args,
                "result": result,
                "call_id": call_id,
                "elapsed": round(time.time() - t_start, 3) if t_start else 0.0,
            }
        return {
            "name": fn_name,
            "arguments": fn_args,
            "error": "no handler",
            "call_id": call_id,
            "elapsed": round(time.time() - t_start, 3) if t_start else 0.0,
        }

    @staticmethod
    def _tool_def_to_api(tool: Any) -> dict:
        """Convert a tool definition to the LLM function-calling format.

        ToolSpec (canonical) exposes ``to_api_format``; the deprecated
        ToolDef type does not, so fall back to the plain mapping.
        """
        if hasattr(tool, "to_api_format"):
            return tool.to_api_format()
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
