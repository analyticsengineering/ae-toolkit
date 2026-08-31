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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import host_contract  # noqa: E402
import redact_secrets  # noqa: E402


SERVER_NAME = "analytics-engineering"
SERVER_HOST = "mcp.analyticsengineering.com"
CONTENT_KEY = re.compile(
    r"(sql|code|content|query|data|dataset|schema|submission|answer|diff|"
    r"requirement|profile|manifest|model|file|path|repo|company)",
    re.IGNORECASE,
)
# How many field paths a preview names before it stops. Whatever is omitted is
# still being sent, so the count and the payload size are always reported.
PREVIEW_FIELD_LIMIT = 12
# How deep into a list the preview looks for content fields.
PREVIEW_LIST_LIMIT = 20


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
    """The first credential location in a payload, using the canonical scanner."""
    findings = redact_secrets.scan_structure(value, path)
    return findings[0]["path"] if findings else None


def content_fields(value: Any, path: str = "$") -> tuple[list[str], bool]:
    """Content field paths, and whether the walk stopped short of the payload.

    A preview that quietly stops at the twentieth list element describes less
    than it is about to send, and the reader approves the description.
    """
    fields: list[str] = []
    truncated = False
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if CONTENT_KEY.search(key_text):
                fields.append(child_path)
            child_fields, child_truncated = content_fields(child, child_path)
            fields.extend(child_fields)
            truncated = truncated or child_truncated
    elif isinstance(value, list):
        if len(value) > PREVIEW_LIST_LIMIT:
            truncated = True
        for index, child in enumerate(value[:PREVIEW_LIST_LIMIT]):
            child_fields, child_truncated = content_fields(child, f"{path}[{index}]")
            fields.extend(child_fields)
            truncated = truncated or child_truncated
    return fields, truncated


def payload_shape(value: Any) -> str:
    """A one-line description of what is being sent, independent of the preview."""
    if isinstance(value, dict):
        return f"object with {len(value)} top-level fields"
    if isinstance(value, list):
        return f"array of {len(value)} items"
    return type(value).__name__


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
    discovered, walk_truncated = content_fields(tool_input)
    fields = sorted(set(discovered))
    shown = fields[:PREVIEW_FIELD_LIMIT]
    field_summary = ", ".join(shown) if shown else "request parameters"

    omissions: list[str] = []
    if len(fields) > PREVIEW_FIELD_LIMIT:
        omissions.append(f"{len(fields) - PREVIEW_FIELD_LIMIT} further named fields")
    if walk_truncated:
        omissions.append(
            f"list entries beyond the first {PREVIEW_LIST_LIMIT}, which are still sent"
        )

    message = (
        "This analysis will send the following selected content to "
        f"AnalyticsEngineering.com: {field_summary}. "
        f"The full payload is {payload_shape(tool_input)}, approximately "
        f"{len(serialized.encode('utf-8'))} bytes."
    )
    if omissions:
        message += " This preview omits " + " and ".join(omissions) + "."
    message += " No content is sent until you approve."
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
