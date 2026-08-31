#!/usr/bin/env python3
"""Deterministic shell safety gate for Analytics Engineering Toolkit."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# Hooks are invoked by absolute path from an arbitrary working directory, so the
# sibling module is not importable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import host_contract  # noqa: E402


DB_CLIENT = re.compile(
    r"\b(?:psql|bq|duckdb|sqlite3|snowsql|sqlcmd|mysql|sqlplus)\b",
    re.IGNORECASE,
)
DBT_EXECUTION = re.compile(
    r"\bdbt\b[^;&|]*?\b(?:run|build|test|snapshot|seed|run-operation|compile|show|debug)\b"
    r"|\bdbt\b[^;&|]*?\bdocs\s+generate\b",
    re.IGNORECASE,
)
DBT_DEPENDENCIES = re.compile(r"\bdbt\b[^;&|]*?\bdeps\b", re.IGNORECASE)
DBT_FULL_REFRESH = re.compile(
    r"\bdbt\b[^;&|]*?\b(?:run|build)\b[^;&|]*--full-refresh\b",
    re.IGNORECASE,
)
DB_READ = re.compile(r"\b(?:select|explain)\b", re.IGNORECASE)
DB_WRITE = re.compile(
    r"\b(?:insert\s+into|update\s+\S+|delete\s+from|merge\s+into|alter\s+"
    r"(?:table|view|schema|database))\b",
    re.IGNORECASE,
)
DB_DESTRUCTIVE = re.compile(
    r"\b(?:drop\s+(?:table|view|schema|database)|truncate\s+(?:table\s+)?)\b",
    re.IGNORECASE,
)


def decision(
    permission: str,
    user_message: str = "",
    agent_message: str = "",
    reason_code: str = "",
) -> dict[str, str]:
    result = {"permission": permission}
    if user_message:
        result["user_message"] = user_message
    if agent_message:
        result["agent_message"] = agent_message
    if reason_code:
        result["reason_code"] = reason_code
    return result


def classify(command: str) -> dict[str, str]:
    """Classify a shell command without executing it."""
    normalized = " ".join(command.split())
    lower = normalized.lower()

    if re.search(r"(?:^|[;&|]\s*)rm\s+(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\b", lower):
        return decision(
            "deny",
            "Blocked destructive recursive deletion. Review and remove files through a scoped, reversible workflow.",
            "The Analytics Engineering Toolkit safety gate blocks rm -rf style commands.",
            "destructive-filesystem",
        )

    if re.search(r"\bgit\s+reset\s+--hard\b", lower):
        return decision(
            "deny",
            "Blocked git reset --hard because it can discard uncommitted work.",
            "Use a non-destructive Git workflow and ask the user before discarding changes.",
            "destructive-git-reset",
        )

    if re.search(r"\bgit\s+clean\b[^;&|]*(?:\s|^)-[a-z]*f", lower):
        return decision(
            "deny",
            "Blocked git clean with force because it can permanently remove untracked files.",
            "Inspect untracked files and use a scoped, user-approved cleanup.",
            "destructive-git-clean",
        )

    database_context = bool(DB_CLIENT.search(normalized)) or bool(
        re.match(r"^\s*(?:select|explain|insert|update|delete|merge|alter|drop|truncate)\b", normalized, re.IGNORECASE)
    )

    if database_context and DB_DESTRUCTIVE.search(normalized):
        return decision(
            "deny",
            "Blocked destructive database DDL. V1 does not execute DROP or TRUNCATE statements.",
            "Provide analysis or a reviewed migration plan; do not execute destructive database writes.",
            "destructive-database-ddl",
        )

    if database_context and DB_WRITE.search(normalized):
        return decision(
            "deny",
            "Blocked database mutation. V1 does not execute INSERT, UPDATE, DELETE, MERGE, or ALTER statements.",
            "Keep the workflow analysis-first and provide a proposed statement for human review only.",
            "database-mutation",
        )

    if DBT_FULL_REFRESH.search(normalized):
        return decision(
            "deny",
            "Blocked dbt --full-refresh because it can replace an unbounded set of warehouse objects.",
            "Use a scoped migration or reviewed manual procedure; automated validation never full-refreshes.",
            "dbt-full-refresh",
        )

    if DBT_DEPENDENCIES.search(normalized):
        return decision(
            "ask",
            "This command installs or updates dbt packages in the workspace.",
            "Run dbt deps only after reviewing package and lock-file changes.",
            "dbt-dependency-install",
        )

    if DBT_EXECUTION.search(normalized):
        return decision(
            "ask",
            "This dbt command may connect to or change a warehouse. Confirm the exact scope and a named local or development target.",
            "Run dbt only after explicit approval; verify target, selector, credentials, and expected models first.",
            "dbt-execution",
        )

    if database_context and DB_READ.search(normalized):
        return decision(
            "ask",
            "This command may query a database. Confirm it targets an approved local or development connection.",
            "Only SELECT or EXPLAIN is permitted after explicit approval in V1.",
            "database-read",
        )

    return decision("allow", reason_code="no-risk-pattern")


def main(argv: list[str] | None = None) -> int:
    try:
        host = host_contract.host_from_argv(argv if argv is not None else sys.argv[1:])
    except ValueError as exc:
        # Without a known host there is no way to phrase a refusal the caller
        # will understand, so report the misconfiguration on stderr and exit
        # non-zero rather than emitting a reply that may be read as approval.
        print(f"safety gate misconfigured: {exc}", file=sys.stderr)
        return 2

    try:
        payload: Any = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            host_contract.render(
                decision(
                    "deny",
                    "The safety gate could not validate this command.",
                    f"Invalid hook input: {exc}",
                    "invalid-hook-input",
                ),
                host,
            )
        )
        return 0

    if not isinstance(payload, dict):
        print(
            host_contract.render(
                decision(
                    "deny",
                    "The safety gate could not validate this command.",
                    "Hook input was not an object.",
                    "invalid-hook-input",
                ),
                host,
            )
        )
        return 0

    # Cursor gives shell execution its own event. The other hosts route every
    # tool through one event, so stand aside for calls that are not shell.
    if not host_contract.is_shell_tool(payload, host):
        print(host_contract.allow_silently(host))
        return 0

    command = host_contract.extract_command(payload)
    if not isinstance(command, str) or not command.strip():
        print(
            host_contract.render(
                decision(
                    "deny",
                    "The safety gate received no command to inspect.",
                    "Refuse malformed shell requests.",
                    "missing-command",
                ),
                host,
            )
        )
        return 0

    print(host_contract.render(classify(command), host))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
