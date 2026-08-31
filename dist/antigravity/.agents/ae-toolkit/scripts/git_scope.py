#!/usr/bin/env python3
"""Normalize Git changes into project-relative, typed change records.

Git reports paths relative to the repository root, in several overlapping views
(index, worktree, untracked), with renames spelled as a status letter and a
second path. Consumers that read those views directly ended up double-counting a
staged-and-then-modified file, missing untracked new models, resolving a nested
project's paths against the wrong root, and treating a rename as an unrelated
add plus delete.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspect_git  # noqa: E402


ADDED = "added"
MODIFIED = "modified"
DELETED = "deleted"
RENAMED = "renamed"


@dataclass(frozen=True)
class ChangedPath:
    """One file change, expressed relative to the active dbt project."""

    path: str
    change_type: str
    git_path: str
    original_path: str | None = None
    original_git_path: str | None = None
    staged: bool = False
    untracked: bool = False

    @property
    def is_removal(self) -> bool:
        return self.change_type in {DELETED, RENAMED}

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "change_type": self.change_type,
            "git_path": self.git_path,
        }
        if self.original_path:
            payload["original_path"] = self.original_path
        if self.untracked:
            payload["untracked"] = True
        return payload


@dataclass
class GitScope:
    """Everything dirty in the repository, split by whether it is ours."""

    repository_root: Path | None
    changes: list[ChangedPath]
    excluded_changes: list[dict[str, Any]]
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.error is None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "repository_root": str(self.repository_root) if self.repository_root else None,
            "changes": [change.as_dict() for change in self.changes],
            "excluded_changes": list(self.excluded_changes),
        }
        if self.error:
            payload["error"] = self.error
        return payload


def _change_type(record: dict[str, Any]) -> str:
    if record.get("untracked"):
        return ADDED
    status = str(record.get("status") or "")
    index_status = str(record.get("index_status") or "")
    worktree_status = str(record.get("worktree_status") or "")
    letters = f"{status[:1]}{index_status}{worktree_status}"
    if "R" in letters or "C" in letters:
        return RENAMED
    if "D" in letters:
        return DELETED
    if "A" in letters:
        return ADDED
    return MODIFIED


def _merge_records(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Collapse the status and diff views into one record per path.

    A file can appear in status, in the staged diff, and in the worktree diff at
    once. The strongest signal wins so a staged rename is not also reported as a
    plain modification.
    """
    merged: dict[str, dict[str, Any]] = {}

    def absorb(record: dict[str, Any]) -> None:
        path = str(record.get("path") or "")
        if not path:
            return
        existing = merged.setdefault(path, {})
        for key, value in record.items():
            if value in (None, "", False) and key in existing:
                continue
            if key in existing and key in {"status", "index_status", "worktree_status"}:
                if "R" in str(existing[key]) or "D" in str(existing[key]):
                    continue
            existing[key] = value

    for item in report.get("status", []) or []:
        if isinstance(item, dict):
            absorb(item)
    for view in ("staged", "working_tree"):
        for item in report.get("diffs", {}).get(view, {}).get("files", []) or []:
            if isinstance(item, dict):
                absorb({**item, "staged": view == "staged"})
    return [merged[path] for path in sorted(merged)]


def collect_scope(
    context: Any,
    *,
    report: dict[str, Any] | None = None,
) -> GitScope:
    """Collect changes and split them into project-relative and excluded."""
    root = getattr(context, "git_root", None) or getattr(context, "dbt_root", None)
    if root is None:
        return GitScope(None, [], [], error="No repository or project root was resolved.")

    if report is None:
        try:
            report = inspect_git.inspect_git(root)
        except inspect_git.GitInspectionError as exc:
            return GitScope(root, [], [], error=str(exc))

    changes: list[ChangedPath] = []
    excluded: list[dict[str, Any]] = []
    for record in _merge_records(report):
        if record.get("ignored"):
            continue
        git_path = str(record["path"])
        relative = context.relative_to_project(git_path)
        if relative is None:
            excluded.append(
                {
                    "path": git_path,
                    "reason": "outside the active dbt project",
                }
            )
            continue
        layout = getattr(context, "layout", None)
        if layout is not None and not layout.is_own_code(relative):
            excluded.append({"path": git_path, "reason": "installed package or build output"})
            continue
        original_git = record.get("original_path")
        original = context.relative_to_project(str(original_git)) if original_git else None
        changes.append(
            ChangedPath(
                path=relative,
                change_type=_change_type(record),
                git_path=git_path,
                original_path=original,
                original_git_path=str(original_git) if original_git else None,
                staged=bool(record.get("staged")),
                untracked=bool(record.get("untracked")),
            )
        )
    return GitScope(root, changes, excluded)


def restrict_to(
    scope: GitScope,
    selected_paths: Iterable[str],
) -> GitScope:
    """Keep only the named paths, reporting the rest as deliberately excluded.

    Explicit user scope wins over what happens to be dirty. Silently validating
    an unrelated dirty file is how a bounded check turns into somebody else's
    half-finished work failing in your run.
    """
    wanted = {Path(item).as_posix() for item in selected_paths}
    if not wanted:
        return scope
    kept: list[ChangedPath] = []
    excluded = list(scope.excluded_changes)
    for change in scope.changes:
        if change.path in wanted or (change.original_path or "") in wanted:
            kept.append(change)
        else:
            excluded.append({"path": change.git_path, "reason": "outside the requested scope"})
    return GitScope(scope.repository_root, kept, excluded, scope.error)


def previous_text(root: Path, git_path: str, *, revision: str = "HEAD") -> str | None:
    """Read a file as it was at a revision, or None when it did not exist."""
    result = inspect_git._git(root, ["show", f"{revision}:{git_path}"], check=False)
    if result.returncode:
        return None
    return result.stdout


def changed_paths_of_type(scope: GitScope, change_types: Sequence[str]) -> list[ChangedPath]:
    wanted = set(change_types)
    return [change for change in scope.changes if change.change_type in wanted]
