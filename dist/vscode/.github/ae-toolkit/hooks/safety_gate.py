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


# Matched against the executable's basename, so an unlisted client is simply not
# recognized as a database command. Coverage here is what makes the read-only
# allowlist meaningful: the clients an analytics engineer actually reaches for.
DB_CLIENT = re.compile(
    r"(?:psql|pgcli|bq|duckdb|sqlite3|litecli|snowsql|sqlcmd|mysql|mysqlsh|mycli|"
    r"sqlplus|clickhouse|clickhouse-client|trino|presto|spark-sql|beeline|"
    r"hive|impala-shell|usql|dbsqlcli)",
    re.IGNORECASE,
)
# `clone` writes nodes into a target schema and `retry` re-executes the previous
# invocation, so both reach a warehouse exactly as `run` does. dbt v2's
# `freshness` queries every source and model with a freshness config.
DBT_EXECUTION = re.compile(
    r"\bdbt\b[^;&|]*?\b(?:run|build|test|snapshot|seed|run-operation|compile|show|debug|"
    r"clone|retry|freshness)\b"
    r"|\bdbt\b[^;&|]*?\b(?:docs\s+generate|source\s+freshness)\b",
    re.IGNORECASE,
)
DBT_LOGIN = re.compile(r"\bdbt\b[^;&|]*?\blogin\b", re.IGNORECASE)
# dbt v2 installs as `dbt` and also answers to `dbtf` where v1 shares the PATH.
DBT_PROGRAMS = {"dbt", "dbtf"}
DBT_DEPENDENCIES = re.compile(r"\bdbt\b[^;&|]*?\bdeps\b", re.IGNORECASE)
DBT_FULL_REFRESH = re.compile(
    r"\bdbt\b[^;&|]*?\b(?:run|build|clone)\b[^;&|]*--full-refresh\b",
    re.IGNORECASE,
)
DB_WRITE = re.compile(
    r"\b(?:insert\s+into|update\s+\S+|delete\s+from|merge\s+into|alter\s+"
    r"(?:table|view|schema|database))\b",
    re.IGNORECASE,
)
DB_DESTRUCTIVE = re.compile(
    r"\b(?:drop\s+(?:table|view|schema|database)|truncate\s+(?:table\s+)?)\b",
    re.IGNORECASE,
)
SHELL_WRAPPERS = {"bash", "dash", "sh", "zsh", "ksh", "fish"}
COMMAND_PREFIXES = {"command", "sudo", "doas", "nice", "nohup", "time", "xargs"}
# `FOO=1 rm -rf x` runs `rm`; the assignment only sets its environment. Read as
# the executable, it hid every command behind it from every check.
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Tools that run a program named somewhere among their own arguments. Their
# options differ too much to model one by one, so the launched program is found
# by recognizing its name rather than by skipping a known number of tokens.
LAUNCHERS = {
    "uv", "uvx", "poetry", "pipx", "pdm", "hatch", "rye", "pixi", "pipenv",
    "conda", "mamba", "micromamba", "npx", "bunx", "pnpm", "yarn",
    "exec", "timeout", "watch", "stdbuf", "ionice", "taskset", "caffeinate", "flock",
}
PYTHON = re.compile(r"python(?:\d+(?:\.\d+)?)?")

# Options that consume the next token. Skipping the option but not its value
# left the value looking like the executable, so `sudo -u postgres psql` was
# classified as running a program called `postgres`.
VALUE_OPTIONS = {
    "sudo": {"-u", "-g", "-p", "-C", "-h", "-r", "-t", "-U", "-c", "-D", "-R"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "xargs": {"-n", "-I", "-L", "-P", "-d", "-E", "-s"},
}
# Where each DB client takes an inline statement. Anything else it is handed --
# a file, a script, a here-document -- is content this gate cannot read.
DB_STATEMENT_OPTIONS = {"-c", "--command", "-q", "-e", "--execute", "--query", "-Q"}
DB_FILE_OPTIONS = {"-f", "--file", "-i", "--init", "--input", "--filename"}
SQL_STATEMENT = re.compile(
    r"^\s*(?:select|explain|with|show|describe|desc|insert|update|delete|merge|alter|"
    r"drop|truncate|create|grant|revoke|copy|call|vacuum|analyze|begin|commit)\b",
    re.IGNORECASE,
)

# Command substitution hides a whole command inside a token. Left alone,
# `$(rm -rf /)` reaches the classifier as an executable literally named `$(rm`.
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _split_lines(command: str) -> list[str]:
    """Separate commands that a newline, not a semicolon, put on their own line.

    `shlex` with `whitespace_split` treats a newline as ordinary whitespace, so a
    two-line script arrived as one long argument list and only the first
    executable was ever classified.
    """
    return [line for line in re.split(r"[\r\n]+", command) if line.strip()]


def _segments(command: str) -> list[list[str]]:
    """Tokenize executable shell segments without matching quoted prose."""
    result: list[list[str]] = []
    for line in _split_lines(command):
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lexer.whitespace_split = True
            lexer.commenters = ""
            tokens = list(lexer)
        except ValueError:
            # Malformed quoting is not safe to reinterpret. Returning no segments
            # leaves the hook's ordinary fail-closed input handling in charge.
            return []
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


def _substituted_commands(command: str) -> list[str]:
    """Commands embedded through `$(...)` or backticks."""
    found: list[str] = []
    for outer, inner in SUBSTITUTION.findall(command):
        text = outer or inner
        if text.strip():
            found.append(text)
    return found


def _program(token: str) -> str:
    """The name a shell would resolve, compared the way the filesystem compares it.

    The default macOS and Windows filesystems are case-insensitive, so `DBT run`
    and `RM -rf` launch the same binaries as their lowercase spellings.
    """
    name = re.split(r"[\\/]", token)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_governed_program(token: str) -> bool:
    name = _program(token)
    return (
        name in DBT_PROGRAMS
        or name in SHELL_WRAPPERS
        or name in {"rm", "git"}
        or bool(DB_CLIENT.fullmatch(name))
        or bool(PYTHON.fullmatch(name))
    )


def _python_module(tokens: list[str]) -> list[str] | None:
    """`python -m dbt ...` as the dbt command it runs, or None for anything else."""
    for index, token in enumerate(tokens[1:], start=1):
        if token == "-m" and index + 1 < len(tokens):
            module, rest = tokens[index + 1], tokens[index + 2 :]
        elif token.startswith("-m") and len(token) > 2:
            module, rest = token[2:], tokens[index + 1 :]
        else:
            continue
        if module.split(".")[0].lower() == "dbt":
            return ["dbt", *rest]
        return None
    return None


def _command_tokens(tokens: list[str]) -> list[str]:
    """Strip common non-semantic launch prefixes."""
    index = 0
    while index < len(tokens):
        if ASSIGNMENT.match(tokens[index]):
            index += 1
            continue
        name = _program(tokens[index])
        if name in LAUNCHERS:
            launched = next(
                (
                    position
                    for position in range(index + 1, len(tokens))
                    if not tokens[position].startswith("-")
                    and _is_governed_program(tokens[position])
                ),
                None,
            )
            if launched is None:
                break
            index = launched
            continue
        if PYTHON.fullmatch(name):
            module = _python_module(tokens[index:])
            if module is not None:
                return module
            break
        if name in COMMAND_PREFIXES or name == "env":
            value_options = VALUE_OPTIONS.get(name, set())
            index += 1
            while index < len(tokens):
                token = tokens[index]
                if token in value_options:
                    index += 2
                    continue
                if token.startswith("-") and token != "-":
                    index += 1
                    continue
                if name == "env" and "=" in token and not token.startswith("-"):
                    index += 1
                    continue
                break
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


def _shell_script(arguments: list[str]) -> str | None:
    """The script a shell wrapper was asked to run, however `-c` was spelled.

    `bash -lc` and `sh -ec` cluster `c` with other flags, so looking for a bare
    `-c` token let the most common wrapper spelling through unread.
    """
    for index, token in enumerate(arguments):
        if not token.startswith("-") or token.startswith("--"):
            if token == "-c" and index + 1 < len(arguments):
                return arguments[index + 1]
            continue
        if token == "--command" and index + 1 < len(arguments):
            return arguments[index + 1]
        if not token.startswith("--") and "c" in token[1:] and index + 1 < len(arguments):
            return arguments[index + 1]
    return None


def _destructive_git(arguments: list[str]) -> str | None:
    """Git operations that discard work, matched by token, never by prose.

    The written policy bans history rewrites, force pushes, work-discarding
    resets, and branch deletion. Enumerating a few spellings of each let the
    others through, so every family is covered here.
    """
    subcommands = {
        "reset",
        "clean",
        "restore",
        "checkout",
        "switch",
        "push",
        "branch",
        "stash",
        "filter-branch",
        "filter-repo",
        "update-ref",
    }
    subcommand_index = next(
        (index for index, token in enumerate(arguments) if token in subcommands),
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
    if subcommand == "checkout" and (
        "--" in options or "f" in flags or "--force" in options
    ):
        return "destructive-git-checkout"
    if subcommand == "switch" and (
        "--discard-changes" in options or "f" in flags or "--force" in options
    ):
        return "destructive-git-switch"
    if subcommand == "push":
        if "f" in flags or "--force" in options or any(
            token.startswith("--force-with-lease") or token.startswith("--force-if-includes")
            for token in options
        ):
            return "destructive-git-force-push"
        if "--delete" in options or "d" in flags or any(
            token.startswith(":") and len(token) > 1 for token in options
        ):
            return "destructive-git-branch-delete"
        if "--mirror" in options:
            return "destructive-git-force-push"
    if subcommand == "branch" and (
        "D" in flags or "d" in flags or "--delete" in options
    ):
        return "destructive-git-branch-delete"
    if subcommand == "stash" and any(
        token in {"drop", "clear"} for token in options[:1]
    ):
        return "destructive-git-stash"
    if subcommand in {"filter-branch", "filter-repo"}:
        return "destructive-git-history-rewrite"
    if subcommand == "update-ref" and ("d" in flags or "--delete" in options):
        return "destructive-git-history-rewrite"
    return None


def _destructive_command(tokens: list[str]) -> str | None:
    tokens = _command_tokens(tokens)
    if not tokens:
        return None
    executable = _program(tokens[0])
    arguments = tokens[1:]

    if executable in SHELL_WRAPPERS:
        script = _shell_script(arguments)
        if script is not None:
            nested = classify(script)
            return nested.get("reason_code") if nested["permission"] == "deny" else None

    if executable == "rm":
        flags = _short_flags(arguments)
        recursive = "r" in flags or "R" in flags or "--recursive" in arguments
        force = "f" in flags or "--force" in arguments
        if recursive and force:
            return "destructive-filesystem"

    if executable == "git":
        return _destructive_git(arguments)
    return None


def strip_sql_comments(text: str) -> str:
    """Remove SQL comments without losing anything inside a string literal.

    A comment marker is only a comment outside quotes: `select '-- not a comment'`
    must survive intact, or the statement that reaches the classifier is not the
    statement the database would run.
    """
    out: list[str] = []
    index, length = 0, len(text)
    quote: str | None = None
    while index < length:
        char = text[index]
        if quote:
            out.append(char)
            if char == quote:
                # Doubling is the SQL escape for a quote inside a literal.
                if index + 1 < length and text[index + 1] == quote:
                    out.append(text[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "-" and text.startswith("--", index):
            end = text.find("\n", index)
            index = length if end == -1 else end
            out.append(" ")
            continue
        if char == "/" and text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            out.append(" ")
            continue
        out.append(char)
        index += 1
    return "".join(out)


def split_sql_statements(text: str) -> list[str]:
    """Top-level statements, splitting only on semicolons the database sees.

    Maintaining a denylist of dangerous statements meant every statement nobody
    listed slipped through. Counting statements instead makes the rule testable:
    a client invocation carrying more than one statement is never eligible.
    """
    cleaned = strip_sql_comments(text)
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    depth = 0
    index, length = 0, len(cleaned)
    while index < length:
        char = cleaned[index]
        if quote:
            current.append(char)
            if char == quote:
                if index + 1 < length and cleaned[index + 1] == quote:
                    current.append(cleaned[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            statements.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    statements.append("".join(current))
    return [item.strip() for item in statements if item.strip()]


WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
# The only statement classes a database client may be approved to run. Every
# other class -- including SHOW and DESCRIBE, which the policy text excludes --
# is denied rather than added to a growing list of exceptions.
#
# This is a syntactic test, and the gate claims no more than that. A single
# SELECT is eligible for approval; it is not proof of no side effect, because
# `select drop_everything()` is a syntactically perfect query and only the
# warehouse knows what the function does. The human approving the command is
# the control for semantics.
READ_STATEMENTS = {"select", "explain"}


def _top_level_words(statement: str) -> list[str]:
    """Keywords outside any parenthesis, which is where the statement class lives."""
    words: list[str] = []
    depth = 0
    quote: str | None = None
    index, length = 0, len(statement)
    while index < length:
        char = statement[index]
        if quote:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        match = WORD.match(statement, index)
        if match:
            if depth == 0:
                words.append(match.group(0).lower())
            index = match.end()
            continue
        index += 1
    return words


def sql_statement_class(statement: str) -> str:
    """What the database would actually do, not what the first word suggests.

    `WITH ... DELETE` and `EXPLAIN ANALYZE DELETE` both begin with a word that
    looks harmless and both modify data, so the class is resolved past the
    prefix rather than read off the front of the string.
    """
    words = _top_level_words(statement)
    if not words:
        return "unknown"
    head = words[0]
    if head == "explain":
        # EXPLAIN ANALYZE executes the plan, so what follows decides the class.
        rest = [word for word in words[1:] if word not in {"analyze", "verbose", "format", "json", "text", "yaml", "xml", "costs", "buffers", "on", "off", "true", "false"}]
        if not rest:
            return "explain"
        resolved = "explain" if rest[0] == "select" else rest[0]
    elif head == "with":
        resolved = "unknown"
        for word in words[1:]:
            if word in {"select", "insert", "update", "delete", "merge"}:
                resolved = "select" if word == "select" else word
                break
    else:
        resolved = head
    if resolved in {"select", "explain"} and "into" in words:
        # SELECT ... INTO creates a table on Postgres and T-SQL, and writes a
        # file on MySQL. It reads like a query and behaves like a write.
        return "select-into"
    return resolved


def _db_statements(tokens: list[str]) -> tuple[list[str], bool]:
    """Inline statements handed to a database client, and whether any are opaque.

    A client invoked with a script file, a here-document, or no readable
    statement at all is opaque: nothing in the command line proves it only
    reads. Treating that as safe is how `psql -f migrate.sql` was allowed.
    """
    statements: list[str] = []
    positional: list[str] = []
    opaque = False
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in DB_STATEMENT_OPTIONS and index + 1 < len(tokens):
            statements.append(tokens[index + 1])
            index += 2
            continue
        for option in DB_STATEMENT_OPTIONS:
            if token.startswith(f"{option}=") and len(token) > len(option) + 1:
                statements.append(token[len(option) + 1 :])
                break
        else:
            if token in DB_FILE_OPTIONS or any(
                token.startswith(f"{option}=") for option in DB_FILE_OPTIONS
            ):
                opaque = True
            elif not token.startswith("-") and SQL_STATEMENT.match(token.strip()):
                # `bq query 'select 1'` and `sqlite3 db 'select 1'` take the
                # statement positionally, with no option to key off.
                positional.append(token)
        index += 1
    return [*statements, *positional], opaque


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
    for embedded in _substituted_commands(command):
        nested = classify(embedded)
        if nested["permission"] != "allow":
            return nested

    for segment in segments:
        tokens = _command_tokens(segment)
        if not tokens or _program(tokens[0]) not in SHELL_WRAPPERS:
            continue
        script = _shell_script(tokens[1:])
        if script is None:
            continue
        nested = classify(script)
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
    # Spelled `dbt` so one set of patterns governs every name the binary answers to.
    dbt_segments = [
        shlex.join(["dbt", *tokens[1:]])
        for tokens in executable_segments
        if _program(tokens[0]) in DBT_PROGRAMS
    ]
    database_clients = [
        tokens
        for tokens in executable_segments
        if DB_CLIENT.fullmatch(_program(tokens[0]))
    ]
    # The SQL a client was handed, with comments removed. Searching the raw
    # command line instead denied `select 1 -- ; drop table orders`, which is one
    # harmless read, on the strength of words the database never executes.
    client_sql: list[str] = []
    for tokens in database_clients:
        supplied, _ = _db_statements(tokens)
        client_sql.extend(strip_sql_comments(item) for item in supplied)
    direct_sql = bool(
        re.match(
            r"^\s*(?:select|explain|with|insert|update|delete|merge|alter|drop|truncate|"
            r"create|grant|revoke|copy|call|vacuum)\b",
            normalized,
            re.IGNORECASE,
        )
    )
    governed = " ; ".join([*dbt_segments, *client_sql])
    database_context = bool(database_clients) or direct_sql

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

    # A database client is allowed only what it can be proven to do. Listing the
    # dangerous statements meant every statement nobody thought to list -- CREATE,
    # GRANT, COPY, CALL, a `-f` script -- ran without review.
    for tokens in database_clients:
        statements, opaque = _db_statements(tokens)
        if opaque or not statements:
            return decision(
                "deny",
                "Blocked a database client command whose statements could not be read, "
                "so it cannot be shown to be read-only.",
                "Pass an explicit SELECT or EXPLAIN inline, or produce the statement for "
                "human review instead of executing a script or interactive session.",
                "unverifiable-database-command",
            )
        for supplied in statements:
            parsed = split_sql_statements(supplied)
            if len(parsed) != 1:
                return decision(
                    "deny",
                    "Blocked a database client command that carries more than one SQL "
                    "statement, so the whole invocation cannot be shown to be a read.",
                    "Send exactly one SELECT or EXPLAIN, or provide the sequence as a "
                    "reviewed proposal instead of executing it.",
                    "multi-statement-database-command",
                )
            if sql_statement_class(parsed[0]) not in READ_STATEMENTS:
                return decision(
                    "deny",
                    "Blocked a database statement that is not a read. V1 executes only "
                    "SELECT or EXPLAIN against an approved local or development target.",
                    "Provide the statement as a reviewed proposal instead of executing it.",
                    "non-read-database-statement",
                )

    if direct_sql:
        parsed = split_sql_statements(normalized)
        if len(parsed) != 1 or sql_statement_class(parsed[0]) not in READ_STATEMENTS:
            return decision(
                "deny",
                "Blocked a database statement that is not a single read. V1 executes only "
                "SELECT or EXPLAIN against an approved local or development target.",
                "Provide the statement as a reviewed proposal instead of executing it.",
                "non-read-database-statement",
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

    if any(DBT_LOGIN.search(segment) for segment in dbt_segments):
        return decision(
            "ask",
            "This command signs in to dbt platform through a browser and stores credentials locally.",
            "Run dbt login only when the user asks to authenticate with dbt platform.",
            "dbt-platform-login",
        )

    if any(DBT_EXECUTION.search(segment) for segment in dbt_segments):
        return decision(
            "ask",
            "This dbt command may connect to or change a warehouse. Confirm the exact scope and a named local or development target.",
            "Run dbt only after explicit approval; verify target, selector, credentials, and expected models first.",
            "dbt-execution",
        )

    if database_context:
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
