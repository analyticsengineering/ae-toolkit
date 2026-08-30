#!/usr/bin/env python3
"""Translate gate decisions between the hook contracts of different agent hosts.

The gates decide the same thing everywhere; only the wire format differs. Cursor
fires `beforeShellExecution` and `beforeMCPExecution` and reads a flat decision
object. VS Code and Antigravity both fire a single `PreToolUse` event carrying a
tool name, and each expects its own reply shape. Keeping that translation here
means `classify()` stays the one place a safety judgement is made, and a new host
costs a table entry rather than a second copy of the rules.

Extraction is deliberately tolerant. These hook APIs are young and have already
changed field names between releases, and a gate that fails to find the command
would otherwise wave it through. Every lookup therefore ends in a bounded search,
and callers treat "not found" as deny rather than allow.
"""

from __future__ import annotations

import json
from typing import Any

HOSTS = ("cursor", "vscode", "antigravity")

# Where each host puts the shell command. Tried in order, first hit wins.
#
# Copilot is two shapes rather than one: VS Code documents snake_case fields with
# an object argument, while Copilot CLI documents camelCase with the arguments
# encoded as a JSON string. Both reach this gate, which is why the list is not a
# single lookup per host.
COMMAND_PATHS: tuple[tuple[str, ...], ...] = (
    ("command",),                    # Cursor
    ("tool_input", "command"),       # VS Code and Antigravity
    ("toolInput", "command"),        # Copilot, camelCase variant
    ("toolArgs", "command"),         # Copilot CLI, once the JSON string is parsed
    ("arguments", "command"),
    ("input", "command"),
)

# Keys that hold a shell command under any host, used only by the fallback scan.
COMMAND_KEYS = frozenset({"command", "cmd", "commandline", "command_line"})

# Tool names that mean "this is a shell execution" rather than some other tool.
SHELL_TOOLS = frozenset(
    {"runterminalcommand", "run_command", "bash", "shell", "terminal", "run_terminal_cmd"}
)

MAX_SCAN_DEPTH = 6


def _coerce_mapping(value: Any) -> dict[str, Any] | None:
    """Return a mapping, parsing it from JSON when a host passes it as a string.

    Copilot CLI sends `toolArgs` as an encoded JSON string while VS Code sends the
    equivalent field as an object, so the same logical path arrives in two shapes.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        mapping = _coerce_mapping(current)
        if mapping is None or key not in mapping:
            return None
        current = mapping[key]
    return current


def _scan_for_command(value: Any, depth: int = 0) -> str | None:
    """Find a command string anywhere in the payload, as a last resort.

    Reached only when no known path matched, which means the host has changed its
    schema. Finding the command lets the gate keep judging it; finding nothing
    leaves the caller to fail closed.
    """
    if depth > MAX_SCAN_DEPTH:
        return None
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower().replace("-", "_") in COMMAND_KEYS and isinstance(nested, str) and nested.strip():
                return nested
        for nested in value.values():
            found = _scan_for_command(nested, depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _scan_for_command(nested, depth + 1)
            if found:
                return found
    return None


def tool_name(payload: dict[str, Any]) -> str:
    for key in ("toolName", "tool_name", "tool", "name"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def is_shell_tool(payload: dict[str, Any], host: str) -> bool:
    """Report whether this event concerns a shell execution.

    Cursor routes shell and MCP to separate events, so anything reaching the shell
    gate is by definition a shell call. VS Code and Antigravity multiplex every
    tool through `PreToolUse`, so the gate has to recognise its own traffic. An
    unrecognised name is treated as shell, because inspecting a command that turns
    out to be something else is harmless while skipping a real one is not.
    """
    if host == "cursor":
        return True
    name = tool_name(payload).lower().replace("-", "_")
    if not name:
        return True
    if name in SHELL_TOOLS:
        return True
    # An MCP tool call is the one case we can positively rule out.
    return not name.startswith("mcp")


def extract_command(payload: dict[str, Any]) -> str | None:
    for path in COMMAND_PATHS:
        value = _dig(payload, path)
        if isinstance(value, str) and value.strip():
            return value
    return _scan_for_command(payload)


def is_mcp_tool(payload: dict[str, Any], host: str) -> bool:
    """Report whether this event concerns an MCP tool call.

    Cursor gives MCP its own event. Elsewhere an MCP call is identifiable only by
    its tool name, which hosts encode as `mcp__<server>__<tool>`.
    """
    if host == "cursor":
        return True
    if payload.get("mcp_server_name"):
        return True
    return tool_name(payload).lower().startswith("mcp")


def extract_mcp_server(payload: dict[str, Any]) -> str | None:
    """Recover the MCP server name from whichever field the host populated.

    Returning None matters: the gate fails closed on an unidentified server, so a
    wrong guess here would be worse than no answer.
    """
    for key in ("mcp_server_name", "mcpServerName", "server_name", "serverName", "server"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

    # `mcp__<server>__<tool>`, the encoding used when MCP shares the tool event.
    name = tool_name(payload)
    if name.lower().startswith("mcp"):
        parts = name.split("__")
        if len(parts) >= 3 and parts[1].strip():
            return parts[1]
    return None


def extract_tool_input(payload: dict[str, Any]) -> Any:
    for key in ("tool_input", "toolInput", "toolArgs", "arguments", "input", "params"):
        if key in payload:
            return payload[key]
    return {}


def render(decision: dict[str, str], host: str) -> str:
    """Serialise a gate decision into the reply shape the host expects."""
    permission = decision.get("permission", "deny")
    user_message = decision.get("user_message", "")
    agent_message = decision.get("agent_message", "")
    reason_code = decision.get("reason_code", "")

    if host == "cursor":
        return json.dumps(decision)

    # Both remaining hosts carry a single reason string, so combine the two
    # audiences rather than dropping the operator-facing half.
    reason = " ".join(part for part in (user_message, agent_message) if part).strip()

    if host == "vscode":
        body: dict[str, Any] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission,
        }
        if reason:
            body["permissionDecisionReason"] = reason
        return json.dumps({"hookSpecificOutput": body})

    if host == "antigravity":
        payload: dict[str, Any] = {"decision": permission}
        if reason:
            payload["reason"] = reason
        if reason_code:
            payload["metadata"] = {"reason_code": reason_code}
        return json.dumps(payload)

    raise ValueError(f"unknown host: {host}")


def allow_silently(host: str) -> str:
    """Reply that leaves a tool call untouched.

    Used when the event is not this gate's business, which happens on the hosts
    that route every tool through one event.
    """
    return render({"permission": "allow", "reason_code": "not-applicable"}, host)


def host_from_argv(argv: list[str], default: str = "cursor") -> str:
    """Read `--host <name>` from the command line.

    The generated hook configuration for each target passes this flag, so one
    script serves every host and the targets cannot drift apart in their rules.
    """
    for index, item in enumerate(argv):
        if item == "--host" and index + 1 < len(argv):
            candidate = argv[index + 1].lower()
            if candidate not in HOSTS:
                raise ValueError(f"unknown host: {candidate}")
            return candidate
        if item.startswith("--host="):
            candidate = item.split("=", 1)[1].lower()
            if candidate not in HOSTS:
                raise ValueError(f"unknown host: {candidate}")
            return candidate
    return default
