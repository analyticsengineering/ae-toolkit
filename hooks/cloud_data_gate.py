#!/usr/bin/env python3
"""Fail-closed approval gate for MCP tools that reach a warehouse or the dbt platform.

The toolkit ships no MCP server of its own. Teams commonly add the dbt MCP server,
whose tools can build models, run arbitrary SQL, query metrics, and trigger jobs:
the same warehouse execution the shell gate holds for approval when it arrives as
`dbt run`. This gate holds those tools the same way, and stands aside for every
other server.
"""

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


DBT_SERVER = re.compile(r"(?i)(?:^|[^a-z])dbt(?:[^a-z]|$)")
DBT_HOSTS = ("getdbt.com", "dbt.com")
DBT_LAUNCH = re.compile(r"(?i)\bdbt[-_]mcp\b")
# Tools that execute against the warehouse or change state on the dbt platform.
WAREHOUSE_TOOLS = frozenset(
    {
        "build", "run", "test", "seed", "snapshot", "show", "compile", "clone", "retry",
        "freshness", "run_operation", "docs", "execute_sql", "text_to_sql", "query_metrics",
        "generate_source", "generate_model_yaml", "generate_staging_model",
        "trigger_job_run", "retry_job_run", "cancel_job_run",
    }
)
# Tools that read project metadata or compile against the platform without executing.
METADATA_TOOLS = frozenset({"parse", "list", "ls", "get_metrics_compiled_sql"})
METADATA_PREFIXES = ("get_", "list_", "search_")
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

    if not is_dbt_server(server_name, payload):
        print(
            host_contract.render(
                response(
                    "allow",
                    "This MCP call does not target a dbt server.",
                    "The toolkit's MCP gate governs only dbt servers.",
                    "unrelated-mcp-server",
                ),
                agent_host,
            )
        )
        return 0

    tool = mcp_tool(payload)
    if tool in METADATA_TOOLS or tool.startswith(METADATA_PREFIXES):
        print(
            host_contract.render(
                response("allow", "", "Reading dbt project metadata does not execute against the warehouse.", "dbt-metadata"),
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
                    "Potential secret material was detected in this dbt MCP request. Redact it before retrying.",
                    f"Best-effort secret detection flagged {secret_path}; do not send this request.",
                    "potential-secret",
                ),
                agent_host,
            )
        )
        return 0

    known = tool in WAREHOUSE_TOOLS
    what = (
        f"The dbt MCP tool `{tool or 'unknown'}` "
        + ("executes against your warehouse or the dbt platform" if known else "is not one AE recognises, so it may execute against your warehouse")
        + f". The request is {payload_shape(tool_input)}, approximately "
        f"{len(json.dumps(tool_input, ensure_ascii=False, default=str).encode('utf-8'))} bytes."
    )
    print(
        host_contract.render(
            response(
                "ask",
                what + " Nothing runs until you approve.",
                "Proceed only after explicit approval, as for `dbt run` in the shell. Prefer a static or local check when one answers the question.",
                "dbt-warehouse-approval" if known else "dbt-unknown-tool-approval",
            ),
            agent_host,
        )
    )
    return 0


def is_dbt_server(server_name: str, payload: dict[str, Any]) -> bool:
    server_url = payload.get("mcp_server_url") or payload.get("url") or ""
    host = (urlparse(server_url).hostname or "") if isinstance(server_url, str) else ""
    launch = payload.get("command")
    return (
        bool(DBT_SERVER.search(server_name))
        or any(host == h or host.endswith("." + h) for h in DBT_HOSTS)
        or (isinstance(launch, str) and bool(DBT_LAUNCH.search(launch)))
    )


def mcp_tool(payload: dict[str, Any]) -> str:
    """The tool's own name, without the `mcp__<server>__` prefix some hosts add."""
    name = host_contract.tool_name(payload)
    if name.lower().startswith("mcp") and name.count("__") >= 2:
        name = name.split("__", 2)[2]
    return name.strip().lower().replace("-", "_")


if __name__ == "__main__":
    raise SystemExit(main())
