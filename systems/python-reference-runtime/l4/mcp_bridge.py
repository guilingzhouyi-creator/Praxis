"""MCP bridge — bidirectional adapter between MCP protocol and ToolSpec.

Two modes:
  Import (MCP Server → Praxis Tool):
    mcp_client = McpClient(MCP_DEFAULT_URL)
    bridge = McpBridge()
    bridge.import_server("my-server", mcp_client)
    # Tools registered as "mcp:my-server:tool_name" in TOOL_REGISTRY

  Export (Praxis Tool → MCP Server):
    bridge = McpBridge()
    bridge.export_tools(categories=["network", "os"])
    # Registers selected Praxis tools as MCP tools on a local server.

GateChain applies to MCP tools just like native tools:
  is_muted("mcp:my-server:write_file") → respects mute/plugin/ring rules

Module layout (split for readability):
  mcp_client.py — McpClient / McpTool / McpClientError (protocol client)
  mcp_state.py  — per-server status vocabulary + mcp_state.json persistence
  mcp_bridge.py — MCPBridge (import/export/oauth/status) + singleton
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from l1.kernel.params.api import MCP_BRIDGE_TIMEOUT, MCP_OAUTH_REDIRECT_PORT, MCP_TOKEN_EXPIRY, MCP_TOKEN_REFRESH_RATIO
from l3.tool_system.tool_spec import ToolRing, ToolSpec, list_tools, register
from l4.llm.http_pool import http_get, http_post

from .mcp_client import McpClient, McpClientError, McpTool  # noqa: F401 — re-export
from .mcp_state import (  # noqa: F401 — re-export
    MCP_STATE_PATH,
    MCP_STATUS_CONNECTED,
    MCP_STATUS_DISABLED,
    MCP_STATUS_FAILED,
    MCP_STATUS_NEEDS_AUTH,
    MCP_STATUS_NEEDS_REGISTRATION,
    _load_mcp_state,
    _mcp_state_path,
    _save_mcp_state,
)

logger = logging.getLogger(__name__)

MCP_TOOL_CATEGORY = "mcp"
MCP_PLUGIN_PREFIX = "mcp"
MCP_NAME_SEP = ":"


# ── MCP Server adapter (exposes Praxis tools as MCP) ──

_default_mcp_tools: dict[str, ToolSpec] = {}  # registered export tools


# ── MCPBridge ──


class MCPBridge:
    """Bidirectional MCP ↔ ToolSpec bridge with 5-state connection management.

    States per server:
      connected              — tools registered, ping OK
      disabled               — user disabled via CLI
      failed                 — connection error, retry available
      needs_auth             — OAuth required before connect
      needs_client_registration — client must register first

    State is persisted to disk (mcp_state.json) for recovery across restarts.
    """

    SERVER_STATUSES = {
        MCP_STATUS_CONNECTED,
        MCP_STATUS_DISABLED,
        MCP_STATUS_FAILED,
        MCP_STATUS_NEEDS_AUTH,
        MCP_STATUS_NEEDS_REGISTRATION,
    }

    def __init__(self):
        self._imported_servers: dict[str, McpClient] = {}
        self._server_status: dict[str, str] = {}  # name → status
        self._server_error: dict[str, str] = {}  # name → last error
        self._server_auth: dict[str, dict] = {}  # name → auth data
        self._lock = threading.Lock()
        self._restore_state()

    def _restore_state(self) -> None:
        """Load persisted server state at startup."""
        saved = _load_mcp_state()
        with self._lock:
            for name, info in saved.items():
                status = info.get("status", MCP_STATUS_FAILED)
                if status in self.SERVER_STATUSES:
                    self._server_status[name] = status
                    self._server_error[name] = info.get("error", "")
                    if info.get("auth"):
                        self._server_auth[name] = info["auth"]

    def _persist(self) -> None:
        """Save current state to disk."""
        with self._lock:
            servers = {}
            for name in set(self._server_status.keys()) | set(self._imported_servers.keys()):
                servers[name] = {
                    "status": self._server_status.get(name, MCP_STATUS_FAILED),
                    "error": self._server_error.get(name, ""),
                    "endpoint": self._imported_servers[name].endpoint if name in self._imported_servers else "",
                    "auth": self._server_auth.get(name, {}),
                }
        _save_mcp_state(servers)

    def get_status(self, server_name: str = "") -> dict:
        """Get connection status for one or all servers."""
        with self._lock:
            if server_name:
                return {
                    "name": server_name,
                    "status": self._server_status.get(server_name, "unknown"),
                    "error": self._server_error.get(server_name, ""),
                    "has_auth": server_name in self._server_auth,
                }
            results = {}
            names = set(self._server_status.keys()) | set(self._imported_servers.keys())
            for name in sorted(names):
                results[name] = {
                    "status": self._server_status.get(name, "unknown"),
                    "error": self._server_error.get(name, ""),
                    "has_auth": name in self._server_auth,
                }
            return results

    def set_disabled(self, server_name: str) -> dict:
        """Manually disable a server."""
        with self._lock:
            self._server_status[server_name] = MCP_STATUS_DISABLED
        self._persist()
        return {"success": True, "server": server_name, "status": MCP_STATUS_DISABLED}

    def set_enabled(self, server_name: str) -> dict:
        """Re-enable a disabled server for retry."""
        with self._lock:
            if server_name in self._server_status:
                del self._server_status[server_name]
            if server_name in self._server_error:
                del self._server_error[server_name]
        self._persist()
        return {"success": True, "server": server_name}

    # ── Import: MCP Server → Praxis Tool ──

    def _json_schema_to_params(self, schema: dict) -> list[Any]:
        """Convert JSON Schema to list of ParamSpec."""
        from l3.tool_system.tool_spec import ParamSpec as ParamSpecCls

        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        type_map = {
            "string": "string",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "array": "list",
            "object": "dict",
        }
        params = []
        for name, prop in props.items():
            js_type = prop.get("type", "string")
            pt = type_map.get(js_type, "string")
            params.append(
                ParamSpecCls(
                    name=name,
                    type=pt,
                    required=name in required,
                    description=prop.get("description", ""),
                )
            )
        return params

    def import_server(self, server_name: str, client: McpClient) -> dict:
        """Register all tools from an MCP server into TOOL_REGISTRY.

        Sets status to 'connected' on success, 'failed' on error.
        """
        # Check disabled
        with self._lock:
            if self._server_status.get(server_name) == MCP_STATUS_DISABLED:
                return {"success": False, "error": f"server '{server_name}' is disabled", "status": MCP_STATUS_DISABLED}

        try:
            mcp_tools = client.list_tools()
        except McpClientError as e:
            with self._lock:
                self._server_status[server_name] = MCP_STATUS_FAILED
                self._server_error[server_name] = str(e)
            self._persist()
            return {"success": False, "error": str(e), "server": server_name, "status": MCP_STATUS_FAILED}

        registered = []
        for mt in mcp_tools:
            praxis_name = f"mcp{MCP_NAME_SEP}{server_name}{MCP_NAME_SEP}{mt.name}"
            spec = ToolSpec(
                name=praxis_name,
                description=f"[MCP {server_name}] {mt.description}",
                category=MCP_TOOL_CATEGORY,
                ring=ToolRing.RING_2_5,
                danger=2,
                parameters=self._json_schema_to_params(mt.input_schema),
                handler=lambda args, agent, _mt=mt, _client=client: self._call_imported(_client, _mt, args),
                metadata={"mcp_server": server_name, "mcp_tool": mt.name},
            )
            register(spec, plugin=f"{MCP_PLUGIN_PREFIX}{MCP_NAME_SEP}{server_name}")
            registered.append(praxis_name)

        with self._lock:
            self._imported_servers[server_name] = client
            self._server_status[server_name] = MCP_STATUS_CONNECTED
            self._server_error.pop(server_name, None)
        self._persist()

        logger.info("mcp import %s: %d tools registered", server_name, len(registered))
        return {
            "success": True,
            "server": server_name,
            "tools": registered,
            "count": len(registered),
            "status": MCP_STATUS_CONNECTED,
        }

    def remove_server(self, server_name: str) -> dict:
        """Unregister all tools from an MCP server and remove."""
        from l3.tool_system.tool_spec import unregister, unregister_plugin

        with self._lock:
            self._imported_servers.pop(server_name, None)
            self._server_status.pop(server_name, None)
            self._server_error.pop(server_name, None)
            self._server_auth.pop(server_name, None)
        plugin_key = f"{MCP_PLUGIN_PREFIX}{MCP_NAME_SEP}{server_name}"
        removed_count = 0
        for spec in list_tools():
            if spec.name.startswith(f"mcp:{server_name}:"):
                unregister(spec.name)
                removed_count += 1
        unregister_plugin(plugin_key)
        self._persist()
        logger.info("mcp remove %s: %d tools unregistered", server_name, removed_count)
        return {"success": True, "server": server_name, "removed": removed_count}

    def _call_imported(self, client: McpClient, tool: McpTool, args: dict) -> dict:
        """Execute an MCP tool call through the client."""
        try:
            result = client.call_tool(tool.name, args)
            return {"success": True, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def import_discover(self, registry_url: str = "") -> dict:
        """Scan a config section or registry for MCP servers and import all."""
        try:
            imported = []
            config = _load_mcp_state()
            for name, info in config.items():
                ep = info.get("endpoint", "")
                if not ep or info.get("status") == MCP_STATUS_DISABLED:
                    continue
                client = McpClient(ep)
                r = self.import_server(name, client)
                if r.get("success"):
                    imported.append(name)
            return {"success": True, "imported": imported, "count": len(imported)}
        except Exception as e:
            logger.warning("mcp: import_discover failed: %s", e)
            return {"success": False, "error": str(e), "imported": []}

    # ── OAuth Authentication ──

    def start_oauth(self, server_name: str, auth_url: str = "", client_id: str = "", redirect_port: int = 0) -> dict:
        """Initiate OAuth flow for an MCP server.

        Returns the authorization URL the user must visit in their browser.
        After authorization, the provider redirects to localhost:redirect_port
        with a code parameter — call finish_oauth() with that code.
        """
        if not redirect_port:
            redirect_port = MCP_OAUTH_REDIRECT_PORT
        import urllib.parse as _parse

        with self._lock:
            self._server_status[server_name] = MCP_STATUS_NEEDS_AUTH
            auth_data = self._server_auth.get(server_name, {})
            auth_data.update(
                {
                    "client_id": client_id,
                    "redirect_port": redirect_port,
                    "state": __import__("secrets").token_hex(16),
                }
            )
            self._server_auth[server_name] = auth_data
        self._persist()

        if not auth_url:
            return {
                "success": False,
                "error": "auth_url required",
                "server": server_name,
                "status": MCP_STATUS_NEEDS_AUTH,
            }

        redirect_uri = f"http://localhost:{redirect_port}/mcp/oauth/callback"
        params = _parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": auth_data["state"],
            }
        )
        authorization_url = f"{auth_url}?{params}"
        return {
            "success": True,
            "authorization_url": authorization_url,
            "state": auth_data["state"],
            "server": server_name,
        }

    def finish_oauth(self, server_name: str, authorization_code: str) -> dict:
        """Complete OAuth flow by exchanging authorization code for tokens."""
        auth_data = self._server_auth.get(server_name)
        if not auth_data:
            return {"success": False, "error": f"no OAuth session for '{server_name}'"}

        token_url = auth_data.get("token_url", "")
        if not token_url:
            # Try to discover token URL from well-known endpoint
            client = self._imported_servers.get(server_name)
            if client:
                try:
                    wk_status, wk_bytes, _ = http_get(
                        f"{client.endpoint}/.well-known/oauth-authorization-server",
                        {},
                        MCP_BRIDGE_TIMEOUT,
                    )
                    if wk_status >= 400:
                        raise OSError(f"well-known endpoint returned HTTP {wk_status}")
                    wk_data = json.loads(wk_bytes)
                    token_url = wk_data.get("token_endpoint", "")
                except Exception:
                    logger.debug("mcp_bridge: token endpoint parse failed")

        if not token_url:
            return {"success": False, "error": "token_url not found. Set via set_oauth_token_url()"}

        try:
            body = json.dumps(
                {
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"http://localhost:{auth_data.get('redirect_port', MCP_OAUTH_REDIRECT_PORT)}/mcp/oauth/callback",
                    "client_id": auth_data.get("client_id", ""),
                }
            ).encode()
            token_status, token_bytes, _ = http_post(
                token_url,
                body,
                {"Content-Type": "application/json"},
                MCP_BRIDGE_TIMEOUT,
            )
            if token_status >= 400:
                raise OSError(f"token endpoint returned HTTP {token_status}")
            token_data = json.loads(token_bytes)
        except Exception as e:
            return {"success": False, "error": f"token exchange failed: {e}"}

        with self._lock:
            auth_data["access_token"] = token_data.get("access_token", "")
            auth_data["refresh_token"] = token_data.get("refresh_token", "")
            auth_data["expires_in"] = token_data.get("expires_in", MCP_TOKEN_EXPIRY)
            auth_data["token_type"] = token_data.get("token_type", "Bearer")
            auth_data["acquired_at"] = __import__("time").time()
            self._server_auth[server_name] = auth_data
            self._server_status.pop(server_name, None)  # clear needs_auth
        self._persist()

        return {
            "success": True,
            "server": server_name,
            "token_type": auth_data["token_type"],
            "expires_in": auth_data["expires_in"],
        }

    def get_auth_token(self, server_name: str) -> str:
        """Get the access token for a server (for use in McpClient)."""
        auth = self._server_auth.get(server_name, {})
        token = auth.get("access_token", "")
        # Check expiry and attempt refresh if needed
        acquired = auth.get("acquired_at", 0)
        expires = auth.get("expires_in", MCP_TOKEN_EXPIRY)
        if token and acquired and (__import__("time").time() - acquired) > expires * MCP_TOKEN_REFRESH_RATIO:
            logger.info("mcp: token for %s is near expiry, consider refreshing", server_name)
        return token

    def remove_auth(self, server_name: str) -> dict:
        """Remove stored OAuth tokens for a server."""
        with self._lock:
            self._server_auth.pop(server_name, None)
        self._persist()
        return {"success": True, "server": server_name}

    def set_oauth_token_url(self, server_name: str, token_url: str) -> dict:
        """Manually set the OAuth token endpoint for a server."""
        with self._lock:
            auth = self._server_auth.setdefault(server_name, {})
            auth["token_url"] = token_url
        self._persist()
        return {"success": True, "server": server_name}

    def export_tools(self, categories: list[str] | None = None, include_muted: bool = False) -> dict:
        """Register selected Praxis tools as MCP-exportable."""
        tools = list_tools(include_muted=include_muted)
        if categories:
            tools = [t for t in tools if t.category in categories]

        registered = []
        for spec in tools:
            _default_mcp_tools[spec.name] = spec
            registered.append(spec.name)

        logger.info("mcp export: %d tools available for MCP", len(registered))
        return {"success": True, "tools": registered, "count": len(registered)}

    def list_exported_tools(self) -> dict[str, ToolSpec]:
        """Return exported tool specs (base tools available for MCP server mode)."""
        return dict(_default_mcp_tools)

    def clear_exported_tools(self) -> None:
        """Clear the exported tool registry."""
        _default_mcp_tools.clear()

    # ── Prompts ──

    def list_prompts(self, server_name: str) -> dict:
        """List prompts from an MCP server (MCP protocol)."""
        client = self._imported_servers.get(server_name)
        if not client:
            return {"success": False, "error": f"server '{server_name}' not imported"}
        try:
            url = f"{client.endpoint}/prompts/list"
            status, resp_bytes, _ = http_get(url, client._headers, client.timeout)
            if status >= 400:
                raise OSError(f"prompts/list returned HTTP {status}")
            data = json.loads(resp_bytes)
            return {"success": True, "prompts": data.get("prompts", []), "server": server_name}
        except Exception as e:
            return {"success": False, "error": str(e), "server": server_name}

    # ── Resources ──

    def list_resources(self, server_name: str) -> dict:
        """List resources from an MCP server (MCP protocol)."""
        client = self._imported_servers.get(server_name)
        if not client:
            return {"success": False, "error": f"server '{server_name}' not imported"}
        try:
            url = f"{client.endpoint}/resources/list"
            status, resp_bytes, _ = http_get(url, client._headers, client.timeout)
            if status >= 400:
                raise OSError(f"resources/list returned HTTP {status}")
            data = json.loads(resp_bytes)
            return {"success": True, "resources": data.get("resources", []), "server": server_name}
        except Exception as e:
            return {"success": False, "error": str(e), "server": server_name}

    # ── Status ──

    def status(self) -> dict:
        """Return comprehensive status for all servers."""
        with self._lock:
            servers = {}
            all_names = set(self._server_status.keys()) | set(self._imported_servers.keys())
            for name in sorted(all_names):
                client = self._imported_servers.get(name)
                status = self._server_status.get(name, "unknown")
                alive = client.ping() if client else False
                servers[name] = {
                    "status": status,
                    "alive": alive,
                    "error": self._server_error.get(name, ""),
                    "has_auth": name in self._server_auth,
                    "endpoint": client.endpoint if client else "",
                    "tool_count": len(
                        [
                            k
                            for k in list(
                                __import__("sys")
                                .modules.get("l3.tool_spec", __import__("types").SimpleNamespace())
                                .__dict__.get("TOOL_REGISTRY", {})
                            )
                            if k.startswith(f"mcp:{name}:")
                        ]
                    )
                    if client
                    else 0,
                }
        return {
            "servers": servers,
            "count": len(servers),
            "exported_count": len(_default_mcp_tools),
        }


# ── Singleton ──

_bridge: MCPBridge | None = None
_bridge_lock = threading.Lock()


def get_bridge() -> MCPBridge:
    """Get the singleton MCPBridge instance."""
    global _bridge
    if _bridge is None:
        with _bridge_lock:
            if _bridge is None:
                _bridge = MCPBridge()
    return _bridge


def reset_bridge() -> None:
    """Reset the singleton MCPBridge (for testing)."""
    global _bridge
    _bridge = None
