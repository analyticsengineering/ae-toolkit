#!/usr/bin/env python3
"""Inspect Git branch, status, and diffs using read-only commands."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


class GitInspectionError(RuntimeError):
    """Raised when a Git repository cannot be inspected."""


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit parse failures as JSON for automation-friendly CLIs."""

    def error(self, message: str) -> None:
        print(
            json.dumps({"ok": False, "error": message, "error_type": "ArgumentError"}),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _git(
    path: Path,
    arguments: Sequence[str],
    *,
    check: bool = True,
    timeout: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    command = [
        "git",
        "-c",
        "core.quotepath=false",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(path),
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitInspectionError("git executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitInspectionError(f"git command timed out after {timeout:g} seconds") from exc
    if check and completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
        raise GitInspectionError(message)
    return completed


def _parse_status(output: str) -> list[dict[str, Any]]:
    records = output.split("\0")
    changes: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 3:
            continue
        code = record[:2]
        path = record[3:] if record[2:3] == " " else record[2:].lstrip()
        change: dict[str, Any] = {
            "path": path,
            "index_status": code[0],
            "worktree_status": code[1],
            "staged": code[0] not in {" ", "?", "!"},
            "unstaged": code[1] not in {" ", "!", "?"},
            "untracked": code == "??",
            "ignored": code == "!!",
        }
        if ("R" in code or "C" in code) and index < len(records) and records[index]:
            change["original_path"] = records[index]
            index += 1
        changes.append(change)
    return changes


def _parse_name_status(output: str) -> list[dict[str, Any]]:
    fields = output.split("\0")
    changes: list[dict[str, Any]] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if not status:
            continue
        if index >= len(fields):
            break
        path = fields[index]
        index += 1
        item: dict[str, Any] = {"status": status, "path": path}
        if status.startswith(("R", "C")) and index < len(fields):
            item = {
                "status": status,
                "original_path": path,
                "path": fields[index],
            }
            index += 1
        changes.append(item)
    return changes


def _parse_numstat(output: str) -> dict[str, Any]:
    additions = 0
    deletions = 0
    binary_files = 0
    file_count = 0
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        added, deleted = parts[0], parts[1]
        file_count += 1
        if added == "-" or deleted == "-":
            binary_files += 1
            continue
        try:
            additions += int(added)
            deletions += int(deleted)
        except ValueError:
            continue
    return {
        "file_count": file_count,
        "additions": additions,
        "deletions": deletions,
        "binary_file_count": binary_files,
    }


def _diff(path: Path, arguments: Sequence[str]) -> dict[str, Any]:
    name_status = _git(
        path,
        ["diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", *arguments],
    )
    numstat = _git(
        path, ["diff", "--no-ext-diff", "--no-textconv", "--numstat", *arguments]
    )
    result = _parse_numstat(numstat.stdout)
    result["files"] = _parse_name_status(name_status.stdout)
    return result


def inspect_git(path: str | Path = ".", base: str | None = None) -> dict[str, Any]:
    """Inspect a Git repository without changing its worktree, index, or refs."""
    requested_path = Path(path).expanduser().resolve()
    if not requested_path.is_dir():
        raise GitInspectionError(f"Repository path is not a directory: {requested_path}")

    root_result = _git(requested_path, ["rev-parse", "--show-toplevel"])
    root = Path(root_result.stdout.strip()).resolve()
    inside = _git(root, ["rev-parse", "--is-inside-work-tree"]).stdout.strip() == "true"
    if not inside:
        raise GitInspectionError(f"Not a Git worktree: {requested_path}")

    branch_result = _git(root, ["branch", "--show-current"])
    branch = branch_result.stdout.strip() or None
    head_result = _git(root, ["rev-parse", "HEAD"], check=False)
    head = head_result.stdout.strip() if head_result.returncode == 0 else None

    status_result = _git(
        root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    )
    status = _parse_status(status_result.stdout)

    upstream_result = _git(
        root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], check=False
    )
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else None
    ahead = behind = None
    if upstream:
        counts = _git(
            root, ["rev-list", "--left-right", "--count", f"{upstream}...HEAD"], check=False
        )
        if counts.returncode == 0:
            try:
                behind, ahead = (int(value) for value in counts.stdout.split())
            except (TypeError, ValueError):
                ahead = behind = None

    result: dict[str, Any] = {
        "ok": True,
        "requested_path": str(requested_path),
        "repository_root": str(root),
        "branch": branch,
        "detached_head": branch is None and head is not None,
        "head": head,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "clean": not status,
        "status": status,
        "status_counts": {
            "total": len(status),
            "staged": sum(bool(item["staged"]) for item in status),
            "unstaged": sum(bool(item["unstaged"]) for item in status),
            "untracked": sum(bool(item["untracked"]) for item in status),
            "ignored": sum(bool(item["ignored"]) for item in status),
        },
        "diffs": {
            "working_tree": _diff(root, []),
            "staged": _diff(root, ["--cached"]),
        },
        "read_only": True,
    }

    if base:
        verify = _git(root, ["rev-parse", "--verify", f"{base}^{{commit}}"], check=False)
        if verify.returncode:
            raise GitInspectionError(f"Base revision is not a valid commit: {base}")
        result["base"] = {
            "revision": base,
            "resolved_commit": verify.stdout.strip(),
            "diff": _diff(root, [f"{base}...HEAD"]),
        }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Git repository or subdirectory")
    parser.add_argument("--base", help="Optional base commit/branch for base...HEAD diff")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = inspect_git(args.path, args.base)
    except (GitInspectionError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
