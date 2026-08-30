#!/usr/bin/env python3
"""Fail-closed approval gate for AnalyticsEngineering.com MCP calls."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Hooks are invoked by absolute path from an arbitrary working directory, so the
# sibling module is not importable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import host_contract  # noqa: E402


SERVER_NAME = "analytics-engineering"
SERVER_HOST = "mcp.analyticsengineering.com"
SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:api_?key|access_?token|refresh_?token|client_?secret|password|"
    r"passwd|private_?key|authorization|cookie)(?:$|_)",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b|"
    r"\bAIza[0-9A-Za-z_-]{30,}\b|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
CONTENT_KEY = re.compile(
    r"(sql|code|content|query|data|dataset|schema|submission|answer|diff|"
    r"requirement|profile|manifest|model|file|path|repo|company)",
    re.IGNORECASE,
)


def response(
    permission: str,
    user_message: str,
    agent_message: str,
    reason_code: str,
) -> dict[str, str]:
    return {
        "permission": permission,
        "user_message": user_message,
        "agent_message": agent_message,
        "reason_code": reason_code,
    }


def parse_tool_input(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def find_secret(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if SENSITIVE_KEY.search(key_text) and child not in ("", None, [], {}):
                return child_path
            found = find_secret(child, child_path)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = find_secret(child, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str) and SECRET_VALUE.search(value):
        return path
    return None


def content_fields(value: Any, path: str = "$") -> list[str]:
    fields: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if CONTENT_KEY.search(key_text):
                fields.append(child_path)
            fields.extend(content_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:20]):
            fields.extend(content_fields(child, f"{path}[{index}]"))
    return fields


def main(argv: list[str] | None = None) -> int:
    try:
        agent_host = host_contract.host_from_argv(argv if argv is not None else sys.argv[1:])
    except ValueError as exc:
        print(f"cloud data gate misconfigured: {exc}", file=sys.stderr)
        return 2

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            host_contract.render(
                response(
                    "deny",
                    "Cloud transmission was blocked because the approval gate could not inspect the request.",
                    f"Invalid hook input: {exc}",
                    "invalid-hook-input",
                ),
                agent_host,
            )
        )
        return 0

    if not isinstance(payload, dict):
        print(
            host_contract.render(
                response(
                    "deny",
                    "Cloud transmission was blocked because the MCP request was malformed.",
                    "Expected an object from the MCP hook event.",
                    "malformed-mcp-request",
                ),
                agent_host,
            )
        )
        return 0

    # On hosts that route every tool through one event, stand aside for the
    # calls this gate does not govern. Shell commands are the other gate's work.
    if not host_contract.is_mcp_tool(payload, agent_host):
        print(host_contract.allow_silently(agent_host))
        return 0

    server_name = host_contract.extract_mcp_server(payload)
    server_url = payload.get("mcp_server_url") or payload.get("url") or ""
    server_host = urlparse(server_url).hostname if isinstance(server_url, str) else None
    targets_ae = server_name == SERVER_NAME or server_host == SERVER_HOST

    if not server_name:
        print(
            host_contract.render(
                response(
                    "deny",
                    "The MCP call was blocked because its server identity could not be verified.",
                    "No MCP server name was present; fail closed.",
                    "missing-server-identity",
                ),
                agent_host,
            )
        )
        return 0

    if not targets_ae:
        print(
            host_contract.render(
                response(
                    "allow",
                    "This MCP call does not target AnalyticsEngineering.com.",
                    "The plugin cloud gate does not govern other identified MCP servers.",
                    "unrelated-mcp-server",
                ),
                agent_host,
            )
        )
        return 0

    if server_name == SERVER_NAME and server_host not in (None, SERVER_HOST):
        print(
            host_contract.render(
                response(
                    "deny",
                    "Cloud transmission was blocked because the Analytics Engineering MCP URL did not match the expected host.",
                    "Verify the MCP server configuration before retrying.",
                    "server-url-mismatch",
                ),
                agent_host,
            )
        )
        return 0

    tool_input = parse_tool_input(host_contract.extract_tool_input(payload))
    secret_path = find_secret(tool_input)
    if secret_path:
        print(
            host_contract.render(
                response(
                    "deny",
                    "Potential secret material was detected in the selected content. Redact it before using connected analysis.",
                    f"Best-effort secret detection flagged {secret_path}; do not transmit this request.",
                    "potential-secret",
                ),
                agent_host,
            )
        )
        return 0

    serialized = json.dumps(tool_input, ensure_ascii=False, default=str)
    fields = sorted(set(content_fields(tool_input)))
    field_summary = ", ".join(fields[:12]) if fields else "request parameters"
    if len(fields) > 12:
        field_summary += f", and {len(fields) - 12} more fields"

    message = (
        "This analysis will send the following selected content to "
        f"AnalyticsEngineering.com: {field_summary} "
        f"(approximately {len(serialized.encode('utf-8'))} bytes). "
        "No content is sent until you approve."
    )
    print(
        host_contract.render(
            response(
                "ask",
                message,
                "Proceed only after explicit approval. Send the minimum selected content required for this connected workflow.",
                "connected-analysis-approval",
            ),
            agent_host,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
