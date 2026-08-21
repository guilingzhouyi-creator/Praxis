"""TerminalShell — interactive terminal dialect over the L2 command engine.

TS rewrite reference: the terminal dialect is the TUI frontend shape —
the TS side renders a session through SessionView's tui projection and
forwards every command via the bridge.

Migrated from ``l2/shell.py`` into the shell family: the per-line dialect
lives on ``TerminalShell.run`` (dict results, renderable by any frontend)
and the classic REPL loop on ``TerminalShell.loop``.  The module-level
``direct_session`` / ``start_repl`` entry points are kept as legacy
wrappers.
"""

from __future__ import annotations

import logging
from collections import deque

from l1.kernel.params.agent import DEFAULT_CELL_ID, SIGNAL_TARGET_L3
from l1.kernel.params.api import SHELL_CMD_TIMEOUT
from l1.kernel.params.kernel import PROCESS_ERROR_NOT_FOUND
from l1.kernel.params.system import (
    LOG_TRUNC_50,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    SHELL_AUTOCOMPLETE_DISPLAY_LIMIT,
    TERMINAL_OUTPUT_MAX_LINES,
    TOOL_RESULT_DISPLAY_LIMIT,
)
from l1.kernel.ports import get_process_port
from l2.bridge import scout_findings_display_limit
from l2.i18n import t

from ..shell_completer import TerminalCompleter, get_aliases, get_command_help, get_command_names
from .base import Shell
from .session import ShellSession

logger = logging.getLogger(__name__)


def intent_direct(intent: str, agent_id: str) -> dict:
    """Parse an intent via the intent_parse capability; return card details.

    Shared by the canonical `/intent` command.
    """
    try:
        from l1.kernel.capability import invoke_capability

        r = invoke_capability(agent_id, "intent_parse", {"text": intent}, interactive=True)
        if r.get("success"):
            handler_r = r.get("result", {})
            card = handler_r.get("data", {}) if isinstance(handler_r, dict) else {}
            return {
                "success": True,
                "type": "intent",
                "intent": intent,
                "card_id": card.get("card_id", "?"),
                "domain": card.get("domain", "?"),
                "agent": card.get("agent_id", "?"),
                "card_type": card.get("card_type", "?"),
            }
        return {"success": False, "type": "intent", "intent": intent, "error": r.get("error", "parse failed")}
    except Exception as e:
        return {"success": False, "type": "intent", "intent": intent, "error": str(e)}


def scout_commission(task: str, agent_id: str, cell_id: str) -> dict:
    """Commission a Scout for investigation; return status and findings.

    Shared by the canonical `/scout` command.
    """
    if not task:
        return {"success": False, "type": "scout", "error": "scout usage"}
    try:
        from l2.bridge import cell as _get_cell
        from l2.bridge import scout_pool as _get_scout_pool

        cell = _get_cell(cell_id)
        if hasattr(cell, "permission") and cell.permission and not cell.permission.is_visible("scout", agent_id):
            return {"success": False, "type": "scout", "error": "scout disabled"}
        pool = _get_scout_pool()
        r = pool.commission(agent_id, task)
        findings = [str(f)[:LOG_TRUNC_200] for f in r.get("findings", [])[: scout_findings_display_limit()]]
        return {
            "success": True,
            "type": "scout",
            "task": task,
            "status": r.get("status", "?"),
            "findings": findings,
            "error": r.get("error"),
        }
    except Exception as e:
        return {"success": False, "type": "scout", "task": task, "error": str(e)}


class TerminalShell(Shell):
    """Terminal dialect: ``/`` engine commands (incl. /intent, /scout), ``$`` system commands, tool calls."""

    name = "terminal"

    def __init__(self) -> None:
        self._session: ShellSession = self.create_session()
        self._history: deque[str] = deque(maxlen=TERMINAL_OUTPUT_MAX_LINES)

    def create_session(self, session_id: str = "") -> ShellSession:
        """Create a terminal session pre-bound to the L3 signal target."""
        session = super().create_session(session_id)
        session.agent_id = SIGNAL_TARGET_L3
        return session

    def run(self, text: str, session: ShellSession | None = None) -> dict:
        """Execute one input line through the terminal dialect; return a dict result.

        Dialect:
          ``/intent <text>[@<cell>/<agent>]`` → direct intent (canonical)
          ``/scout <task>``             → commission a Scout (canonical)
          ``$ <command>``              → raw system command (via ProcessPort)
          ``/<engine command>``        → L2 command engine (dispatch)
          ``<tool> <args>``            → direct tool execution (aliases: rf→read_file)
          ``help`` / ``tools`` / ``status`` → shell-level built-ins
        """
        line = text.strip()
        if not line:
            return {"success": True, "type": "empty"}
        self._history.append(line)
        sess = session or self._session
        if line in ("help", "h"):
            result = self._help_result()
        elif line in ("tools", "tl"):
            result = self._tools_result()
        elif line in ("status", "st"):
            result = self._tool_result("agent_status", sess)
        elif line.startswith("$"):
            result = self._system_result(line[1:].strip())
        elif line.startswith("/"):
            from l2.l2_shell import dispatch

            result = dispatch(line, sess)
        else:
            result = self._tool_result(line, sess)
        return result

    def loop(self, prompt: str = "agent> ", session: ShellSession | None = None) -> None:
        """Run the interactive REPL loop, rendering run() results to stdout."""
        sess = session or self._session
        self._render_banner()
        try:
            import readline

            completer = TerminalCompleter()
            completer.refresh()
            readline.set_completer(completer.complete)
            readline.parse_and_bind("tab: complete")
            readline.set_completer_delims(" \t\n")
        except ImportError:
            logger.debug("shells.terminal: readline unavailable, tab completion disabled")

        while True:
            try:
                line = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("exit", "q"):
                break
            if line in ("clear", "clr"):
                print("\033[2J\033[H", end="")  # ANSI clear screen (cross-platform)
                continue
            if line in ("history", "hist"):
                # deque is already capped at TERMINAL_OUTPUT_MAX_LINES.
                for i, h in enumerate(self._history, 1):
                    print(f"  {i:3d}  {h}")
                continue
            self._render(self.run(line, sess))

    # ── Dialect helpers (dict results; REPL rendering lives in _render) ──

    def _help_result(self) -> dict:
        """Return the command list (first SHELL_AUTOCOMPLETE_DISPLAY_LIMIT) with help text."""
        names = get_command_names()[:SHELL_AUTOCOMPLETE_DISPLAY_LIMIT]
        help_map = get_command_help()
        commands = [{"name": c, "help": help_map.get(c, "")} for c in names]
        more = len(get_command_names()) - len(names)
        return {"success": True, "type": "help", "commands": commands, "more": more}

    def _tools_result(self) -> dict:
        """Return all registered tools with descriptions; falls back to command names on error."""
        try:
            from l2.bridge import list_tools

            tools = [{"name": tool.name, "description": tool.description[:LOG_TRUNC_50]} for tool in list_tools()]
            return {"success": True, "type": "tools", "tools": tools, "total": len(tools)}
        except Exception as e:
            logger.warning("shells.terminal: list_tools failed (%s), falling back to command list", e)
            names = [{"name": c, "description": ""} for c in get_command_names()]
            return {"success": True, "type": "tools", "tools": names, "total": len(names)}

    def _system_result(self, cmd: str) -> dict:
        """Execute a raw system command through the one-shot process port."""
        if not cmd:
            return {"success": True, "type": "system", "command": ""}
        try:
            proc = get_process_port().run(cmd, timeout=SHELL_CMD_TIMEOUT)
            if proc.timed_out:
                return {"success": False, "type": "system", "command": cmd, "error": "timeout"}
            if proc.error_kind == PROCESS_ERROR_NOT_FOUND:
                return {"success": False, "type": "system", "command": cmd, "error": "shell not found"}
            if proc.error_kind:
                return {
                    "success": False,
                    "type": "system",
                    "command": cmd,
                    "error": proc.stderr or "shell execution failed",
                }
            return {
                "success": proc.returncode == 0,
                "type": "system",
                "command": cmd,
                "output": proc.stdout or "",
                "stderr": proc.stderr or "",
                "returncode": proc.returncode,
            }
        except Exception as e:
            return {"success": False, "type": "system", "command": cmd, "error": str(e)}

    def _tool_result(self, line: str, session: ShellSession) -> dict:
        """Execute a direct tool call (tool_name arg1 arg2 ...); supports aliases."""
        parts = line.split()
        if not parts:
            return {"success": False, "type": "tool", "error": "empty"}
        raw_name = parts[0]
        # Resolve alias
        tool_name = get_aliases().get(raw_name, raw_name)
        args: dict = {}
        for i in range(1, len(parts)):
            if "=" in parts[i]:
                k, v = parts[i].split("=", 1)
                args[k] = v
            else:
                args[f"arg{i}"] = parts[i]
        try:
            from l1.kernel.capability import invoke_capability
            from l2.bridge import get_tool

            spec = get_tool(tool_name)
            if not spec:
                return {"success": False, "type": "tool", "tool": tool_name, "error": "unknown tool"}
            r = invoke_capability(session.agent_id, tool_name, args, interactive=True)
            handler_r = r.get("result", r) if isinstance(r, dict) else r
            if isinstance(handler_r, dict):
                data = handler_r.get("data", handler_r.get("result", handler_r))
            else:
                data = handler_r
            return {"success": bool(r.get("success")), "type": "tool", "tool": tool_name, "args": args, "data": data}
        except Exception as e:
            return {"success": False, "type": "tool", "tool": tool_name, "error": str(e)}

    # ── REPL rendering ──

    def _render_banner(self) -> None:
        """Print the terminal banner."""
        print(t("terminal.banner.title"))
        print(t("terminal.banner.l3a"))
        print(t("terminal.banner.route"))
        print(t("terminal.banner.scout"))
        print(t("terminal.banner.system"))
        print(t("terminal.banner.tool"))
        print()

    def _render(self, result: dict) -> None:
        """Render a run() result dict to stdout (REPL view)."""
        rtype = result.get("type", "")
        if rtype == "empty":
            return
        if rtype == "help":
            print(t("terminal.help.title"))
            for c in result.get("commands", []):
                print(f"  {c['name']:<20s} {c['help']}")
            print(t("terminal.help.more", count=result.get("more", 0)))
        elif rtype == "tools":
            for tool in result.get("tools", []):
                print(f"  {tool['name']:<25s} {tool['description']}")
            print(t("terminal.tools.total", count=result.get("total", 0)))
        elif rtype == "intent":
            if result.get("success"):
                print(t("terminal.l3a.card", card_id=result.get("card_id", "?")))
                print(t("terminal.l3a.domain", domain=result.get("domain", "?")))
                print(t("terminal.l3a.agent", agent=result.get("agent", "?")))
                print(t("terminal.l3a.type", card_type=result.get("card_type", "?")))
            else:
                print(t("terminal.l3a.error", error=result.get("error", "parse failed")))
        elif rtype == "scout":
            if result.get("success"):
                print(t("terminal.scout.status", status=result.get("status", "?")))
                findings = result.get("findings", [])
                if findings:
                    print(t("terminal.scout.findings", count=len(findings)))
                    for f in findings:
                        print(f"    - {f}")
                if result.get("error"):
                    print(t("terminal.scout.error", error=result["error"]))
            else:
                print(t("terminal.scout.error", error=result.get("error", "?")))
        elif rtype == "system":
            for line in (result.get("output") or "").splitlines():
                print(f"  {line}")
            for line in (result.get("stderr") or "").splitlines():
                print(t("terminal.sys.stderr", line=line))
            print(t("terminal.sys.exit", code=result.get("returncode", "?")))
        elif rtype == "tool":
            if result.get("success"):
                data = result.get("data", {})
                if isinstance(data, dict):
                    for k, v in list(data.items())[:TOOL_RESULT_DISPLAY_LIMIT]:
                        print(f"  {k}: {str(v)[:LOG_TRUNC_100]}")
                else:
                    print(t("terminal.exec.result", result=str(data)[:LOG_TRUNC_200]))
            else:
                print(t("terminal.exec.error", error=result.get("error", "execution failed")))
        else:
            # Engine (dispatch) responses and any future dialect — generic view.
            for k, v in list(result.items())[:TOOL_RESULT_DISPLAY_LIMIT]:
                text = str(v) if not isinstance(v, (dict, list)) else repr(v)[:LOG_TRUNC_200]
                print(f"  {k}: {text[:LOG_TRUNC_100]}")


def direct_session(prompt: str = "agent> ", agent_id: str = SIGNAL_TARGET_L3, cell_id: str = DEFAULT_CELL_ID) -> None:
    """Direct session loop — human input → L3A → execute → output.

    Legacy entry point (moved from l2/shell.py); drives TerminalShell.loop.
    """
    shell = TerminalShell()
    shell._session.agent_id = agent_id
    shell._session.cell_id = cell_id
    shell.loop(prompt)


def start_repl(agent_id: str = SIGNAL_TARGET_L3, prompt: str = "") -> None:
    """Start the Agent OS REPL terminal (legacy entry point)."""
    if not prompt:
        prompt = f"agent@{agent_id}> "
    direct_session(prompt, agent_id)
