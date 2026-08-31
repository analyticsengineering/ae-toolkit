#!/usr/bin/env python3
"""Deterministic shell safety gate for Analytics Engineering Toolkit."""

from __future__ import annotations

import json
import re
import shlex
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
    r"|\bdbt\b[^;&|]*?\b(?:docs\s+generate|source\s+freshness)\b",
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
SHELL_WRAPPERS = {"bash", "dash", "sh", "zsh"}
COMMAND_PREFIXES = {"command", "sudo"}


def _segments(command: str) -> list[list[str]]:
    """Tokenize executable shell segments without matching quoted prose."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        # Malformed quoting is not safe to reinterpret. Returning no segments
        # leaves the hook's ordinary fail-closed input handling in charge.
        return []
    result: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and set(token) <= {";", "&", "|"}:
            if current:
                result.append(current)
                current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def _command_tokens(tokens: list[str]) -> list[str]:
    """Strip common non-semantic launch prefixes."""
    index = 0
    while index < len(tokens):
        name = Path(tokens[index]).name
        if name in COMMAND_PREFIXES:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            continue
        if name == "env":
            index += 1
            while index < len(tokens) and (
                tokens[index].startswith("-") or "=" in tokens[index]
            ):
                index += 1
            continue
        if name in {"uv", "poetry"} and index + 1 < len(tokens) and tokens[index + 1] == "run":
            index += 2
            continue
        break
    return tokens[index:]


def _short_flags(tokens: list[str]) -> set[str]:
    flags: set[str] = set()
    for token in tokens:
        if token.startswith("--"):
            continue
        if token.startswith("-") and token != "-":
            flags.update(token[1:])
    return flags


def _destructive_command(tokens: list[str]) -> str | None:
    tokens = _command_tokens(tokens)
    if not tokens:
        return None
    executable = Path(tokens[0]).name
    arguments = tokens[1:]

    if executable in SHELL_WRAPPERS and "-c" in arguments:
        index = arguments.index("-c")
        if index + 1 < len(arguments):
            nested = classify(arguments[index + 1])
            return nested.get("reason_code") if nested["permission"] == "deny" else None

    if executable == "rm":
        flags = _short_flags(arguments)
        recursive = "r" in flags or "R" in flags or "--recursive" in arguments
        force = "f" in flags or "--force" in arguments
        if recursive and force:
            return "destructive-filesystem"

    if executable != "git":
        return None

    # Git global options can precede the subcommand. Finding the destructive
    # verb is safer than assuming tokens[1] is always it (`git -C repo clean`).
    subcommand_index = next(
        (
            index
            for index, token in enumerate(arguments)
            if token in {"reset", "clean", "restore", "checkout", "switch"}
        ),
        None,
    )
    if subcommand_index is None:
        return None
    subcommand = arguments[subcommand_index]
    options = arguments[subcommand_index + 1 :]
    flags = _short_flags(options)
    if subcommand == "reset" and "--hard" in options:
        return "destructive-git-reset"
    if subcommand == "clean" and ("f" in flags or "--force" in options):
        return "destructive-git-clean"
    if subcommand == "restore":
        staged_only = "--staged" in options and "--worktree" not in options
        if not staged_only:
            return "destructive-git-restore"
    if subcommand == "checkout" and "--" in options:
        return "destructive-git-checkout"
    if subcommand == "switch" and "--discard-changes" in options:
        return "destructive-git-switch"
    return None


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
    segments = _segments(command)
    if command.strip() and not segments:
        return decision(
            "deny",
            "Blocked a command the safety gate could not parse.",
            "Fix malformed shell quoting before execution.",
            "invalid-shell-syntax",
        )
    for segment in segments:
        tokens = _command_tokens(segment)
        if not tokens or Path(tokens[0]).name not in SHELL_WRAPPERS:
            continue
        arguments = tokens[1:]
        if "-c" not in arguments:
            continue
        index = arguments.index("-c")
        if index + 1 >= len(arguments):
            continue
        nested = classify(arguments[index + 1])
        if nested["permission"] != "allow":
            return nested
    for tokens in segments:
        destructive = _destructive_command(tokens)
        if destructive == "destructive-filesystem":
            return decision(
                "deny",
                "Blocked destructive recursive deletion. Review and remove files through a scoped, reversible workflow.",
                "The Analytics Engineering Toolkit safety gate blocks recursive forced deletion.",
                destructive,
            )
        if destructive:
            return decision(
                "deny",
                "Blocked a destructive Git worktree command because it can discard local work.",
                "Use a non-destructive Git workflow and ask the user before discarding changes.",
                destructive,
            )

    executable_segments = [
        tokens
        for tokens in (_command_tokens(segment) for segment in segments)
        if tokens
    ]
    dbt_segments = [
        shlex.join(tokens)
        for tokens in executable_segments
        if Path(tokens[0]).name == "dbt"
    ]
    database_segments = [
        shlex.join(tokens)
        for tokens in executable_segments
        if DB_CLIENT.fullmatch(Path(tokens[0]).name)
    ]
    direct_sql = bool(
        re.match(
            r"^\s*(?:select|explain|insert|update|delete|merge|alter|drop|truncate)\b",
            normalized,
            re.IGNORECASE,
        )
    )
    governed = " ; ".join([*dbt_segments, *database_segments])
    database_context = bool(database_segments) or direct_sql

    if database_context and DB_DESTRUCTIVE.search(governed or normalized):
        return decision(
            "deny",
            "Blocked destructive database DDL. V1 does not execute DROP or TRUNCATE statements.",
            "Provide analysis or a reviewed migration plan; do not execute destructive database writes.",
            "destructive-database-ddl",
        )

    if database_context and DB_WRITE.search(governed or normalized):
        return decision(
            "deny",
            "Blocked database mutation. V1 does not execute INSERT, UPDATE, DELETE, MERGE, or ALTER statements.",
            "Keep the workflow analysis-first and provide a proposed statement for human review only.",
            "database-mutation",
        )

    if any(DBT_FULL_REFRESH.search(segment) for segment in dbt_segments):
        return decision(
            "deny",
            "Blocked dbt --full-refresh because it can replace an unbounded set of warehouse objects.",
            "Use a scoped migration or reviewed manual procedure; automated validation never full-refreshes.",
            "dbt-full-refresh",
        )

    if any(DBT_DEPENDENCIES.search(segment) for segment in dbt_segments):
        return decision(
            "ask",
            "This command installs or updates dbt packages in the workspace.",
            "Run dbt deps only after reviewing package and lock-file changes.",
            "dbt-dependency-install",
        )

    if any(DBT_EXECUTION.search(segment) for segment in dbt_segments):
        return decision(
            "ask",
            "This dbt command may connect to or change a warehouse. Confirm the exact scope and a named local or development target.",
            "Run dbt only after explicit approval; verify target, selector, credentials, and expected models first.",
            "dbt-execution",
        )

    if database_context and DB_READ.search(governed or normalized):
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
