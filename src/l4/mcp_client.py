"""MCP client — minimal MCP protocol client over HTTP.

Extracted from ``mcp_bridge.py``: the protocol-speaking client
(``McpClient`` + its ``McpTool`` record / ``McpClientError``), reused by
the import bridge and by callers that need a raw client.
"""

from __future__ import annotations

import json
import urllib.request as req
from dataclasses import dataclass

from l1.kernel.params.api import LLM_HTTP_TIMEOUT, MCP_TIMEOUT
from l1.kernel.params.system import MCP_STATUS_OK


@dataclass
class McpTool:
    """McpTool — mcp tool record (name, description, input_schema)."""

    name: str
    description: str
    input_schema: dict  # JSON Schema


class McpClientError(Exception):
    """McpClientError — mcp client error."""

    pass


class McpClient:
    """Minimal MCP protocol client over HTTP.

    Implements:
      GET  /mcp/v1/tools/list  → tools/list response
      POST /mcp/v1/tools/call  → tools/call request
    """

    def __init__(self, endpoint: str, api_key: str = "", timeout: float = LLM_HTTP_TIMEOUT):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._opener = req.build_opener()

    def list_tools(self) -> list[McpTool]:
        """Fetch and return the remote server's tool list."""
        url = f"{self.endpoint}/tools/list"
        try:
            r = self._opener.open(req.Request(url, headers=self._headers, method="GET"), timeout=self.timeout)
            data = json.loads(r.read())
        except Exception as e:
            raise McpClientError(f"list_tools failed: {e}") from e
        return [
            McpTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", t.get("parameters", {"type": "object"})),
            )
            for t in data.get("tools", [])
        ]

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke a remote MCP tool with the given name and arguments."""
        url = f"{self.endpoint}/tools/call"
        body = json.dumps({"name": name, "arguments": arguments}).encode()
        try:
            r = self._opener.open(
                req.Request(url, data=body, headers=self._headers, method="POST"), timeout=self.timeout
            )
            return json.loads(r.read())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ping(self) -> bool:
        """Return True when the remote server responds OK to a ping."""
        try:
            r = self._opener.open(req.Request(f"{self.endpoint}/ping", headers=self._headers), timeout=MCP_TIMEOUT)
            return r.status == MCP_STATUS_OK
        except Exception:
            return False
