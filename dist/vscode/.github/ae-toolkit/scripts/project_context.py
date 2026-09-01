#!/usr/bin/env python3
"""Resolve one deterministic view of a repository's dbt project layout.

Every dbt-facing script used to answer "where do models live" on its own, using
literal `models/`, `tests/`, and `macros/` segments. That is wrong in three ways
a real repository hits routinely: `dbt_project.yml` can configure every one of
those paths, a dbt project can sit below the Git root, and a monorepo can hold
several projects whose files must never be attributed to each other.

Resolving it once, here, is what lets the planner, the inspectors, and the
inference agree about the same repository.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspect_dbt  # noqa: E402  (local sibling script, not an installed package)


PROJECT_FILENAMES = ("dbt_project.yml", "dbt_project.yaml")

# dbt's own defaults. A project that configures none of these still has them.
DEFAULT_PATHS: dict[str, tuple[str, ...]] = {
    "model-paths": ("models",),
    "test-paths": ("tests",),
    "macro-paths": ("macros",),
    "snapshot-paths": ("snapshots",),
    "seed-paths": ("seeds",),
    "analysis-paths": ("analyses",),
}
DEFAULT_TARGET_PATH = "target"
DEFAULT_PACKAGES_PATH = "dbt_packages"

# Historic and build directories that hold somebody else's code. The configured
# packages path is added to this at runtime, because a project may rename it.
BASE_VENDORED_DIRECTORIES = frozenset({"dbt_packages", "dbt_modules", "target", "logs"})

# How deep to look for a nested project before giving up. Deep enough for
# `services/analytics/warehouse/dbt`, shallow enough not to walk a monorepo.
MAX_DISCOVERY_DEPTH = 6


class ProjectContextError(ValueError):
    """Raised when a repository cannot be resolved to one dbt project."""


# --- Unsupported YAML ---------------------------------------------------------
#
# The toolkit ships standard-library Python only, so its YAML reader covers the
# subset dbt files actually use. The danger is not the missing features; it is
# reading a file that uses them and returning a confidently wrong answer. An
# anchor that silently parses as a string can drop a source's freshness or
# invent a column. These patterns let a caller say "unknown" instead.

UNSUPPORTED_YAML = (
    ("anchor", re.compile(r"(?m)^[^#\n]*?:\s*&[A-Za-z0-9_-]+\s*$")),
    ("alias", re.compile(r"(?m)^[^#\n]*?:\s*\*[A-Za-z0-9_-]+\s*$")),
    ("merge_key", re.compile(r"(?m)^\s*<<\s*:")),
    ("multi_document", re.compile(r"(?m)^---\s*$[\s\S]*?^---\s*$")),
    ("flow_mapping", re.compile(r"(?m)^[^#\n]*?:\s*\{.+\}\s*$")),
)


def unsupported_yaml_constructs(text: str) -> list[str]:
    """Name the YAML features this reader cannot interpret faithfully."""
    return sorted({name for name, pattern in UNSUPPORTED_YAML if pattern.search(text)})


def parse_yaml_checked(text: str) -> tuple[Any, list[str]]:
    """Parse a dbt YAML document alongside anything that makes it unreliable.

    Returns the parsed document and the unsupported constructs found. A caller
    that receives a non-empty list must degrade to "unknown" for whatever the
    document was meant to establish rather than trusting the parse.
    """
    import infer_conventions  # local import avoids a circular module load

    constructs = unsupported_yaml_constructs(text)
    try:
        document = infer_conventions.parse_yaml(text)
    except (ValueError, RecursionError) as exc:  # pragma: no cover - defensive
        return None, sorted({*constructs, f"unparseable: {exc}"})
    return document, constructs


# --- Layout -------------------------------------------------------------------


def normalize_relative(value: str) -> str:
    """Canonicalize a configured path so comparisons can be exact.

    `./models`, `models/`, and `models//./staging` all name real directories,
    and a prefix comparison against the raw string matches none of them. A path
    that climbs above the project root is dropped: it cannot describe a
    directory this project owns.
    """
    text = str(value).strip()
    if not text:
        return ""
    parts = [part for part in PurePosixPath(text).parts if part not in ("", ".", "/")]
    if any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def _configured_paths(project: dict[str, Any], key: str) -> tuple[str, ...]:
    value = project.get(key)
    if isinstance(value, list):
        entries = tuple(
            normalized
            for item in value
            if isinstance(item, str) and (normalized := normalize_relative(item))
        )
        if entries:
            return entries
    if isinstance(value, str) and normalize_relative(value):
        return (normalize_relative(value),)
    return DEFAULT_PATHS.get(key, ())


def _configured_single(project: dict[str, Any], key: str, default: str) -> str:
    value = project.get(key)
    if isinstance(value, str) and normalize_relative(value):
        return normalize_relative(value)
    if isinstance(value, list) and value and isinstance(value[0], str):
        return normalize_relative(value[0]) or default
    return default


class DbtProjectLayout:
    """Where this project keeps each kind of resource, as configured."""

    def __init__(self, root: Path, project: dict[str, Any] | None) -> None:
        config = project if isinstance(project, dict) else {}
        self.root = root
        self.name = str(config.get("name") or "") or None
        self.version = config.get("version")
        self.model_paths = _configured_paths(config, "model-paths")
        self.test_paths = _configured_paths(config, "test-paths")
        self.macro_paths = _configured_paths(config, "macro-paths")
        self.snapshot_paths = _configured_paths(config, "snapshot-paths")
        self.seed_paths = _configured_paths(config, "seed-paths")
        self.analysis_paths = _configured_paths(config, "analysis-paths")
        self.target_path = _configured_single(config, "target-path", DEFAULT_TARGET_PATH)
        self.packages_install_path = _configured_single(
            config, "packages-install-path", DEFAULT_PACKAGES_PATH
        )
        # Project-root-relative prefixes, not bare directory names. A team that
        # sets `packages-install-path: vendor` has not disowned a legitimate
        # `transform/vendor/` model directory, and a nested
        # `packages-install-path: tooling/vendor` is one prefix rather than two
        # names to look for anywhere in a path.
        self.vendored_prefixes = frozenset(
            prefix
            for prefix in {
                *BASE_VENDORED_DIRECTORIES,
                self.packages_install_path,
                self.target_path,
            }
            if prefix
        )
        flags = config.get("flags")
        self.flags = flags if isinstance(flags, dict) else {}
        self.latest_version_pointer_default = bool(
            self.flags.get("latest_version_pointer_enabled_by_default")
        )

    def paths_for(self, kind: str) -> tuple[str, ...]:
        return {
            "model": self.model_paths,
            "test": self.test_paths,
            "macro": self.macro_paths,
            "snapshot": self.snapshot_paths,
            "seed": self.seed_paths,
            "analysis": self.analysis_paths,
        }.get(kind, ())

    def kind_of(self, relative: str) -> str | None:
        """Classify a project-relative path by the configured directory holding it.

        Longest match wins, because `models` and `models/staging` can both be
        configured and the more specific one is the real owner.
        """
        candidate = normalize_relative(relative)
        best: tuple[int, str] | None = None
        for kind in ("model", "test", "macro", "snapshot", "seed", "analysis"):
            for configured in self.paths_for(kind):
                prefix = configured
                if candidate == prefix or candidate.startswith(f"{prefix}/"):
                    if best is None or len(prefix) > best[0]:
                        best = (len(prefix), kind)
        return best[1] if best else None

    def is_own_code(self, relative: str) -> bool:
        """False for installed packages and build output, which are not this team's."""
        candidate = normalize_relative(relative)
        if not candidate:
            return False
        return not any(
            candidate == prefix or candidate.startswith(f"{prefix}/")
            for prefix in self.vendored_prefixes
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "root": str(self.root),
            "model_paths": list(self.model_paths),
            "test_paths": list(self.test_paths),
            "macro_paths": list(self.macro_paths),
            "snapshot_paths": list(self.snapshot_paths),
            "seed_paths": list(self.seed_paths),
            "analysis_paths": list(self.analysis_paths),
            "target_path": self.target_path,
            "packages_install_path": self.packages_install_path,
            "vendored_prefixes": sorted(self.vendored_prefixes),
        }


# --- Discovery ----------------------------------------------------------------


def project_file_in(directory: Path) -> Path | None:
    for name in PROJECT_FILENAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def discover_projects(root: Path, *, max_depth: int = MAX_DISCOVERY_DEPTH) -> list[Path]:
    """Find every dbt project at or beneath a directory, outermost first.

    A project found inside another project's packages directory belongs to a
    vendored package, not to this repository, so it is skipped.
    """
    found: list[Path] = []
    root = root.resolve()
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        if depth > max_depth:
            directories[:] = []
            continue
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in BASE_VENDORED_DIRECTORIES
            and directory not in inspect_dbt.SKIP_DIRECTORIES
            and not directory.startswith(".")
        )
        if any(name in files for name in PROJECT_FILENAMES):
            found.append(current_path)
    return found


def git_root_for(path: Path) -> Path | None:
    try:
        import inspect_git

        result = inspect_git._git(path, ["rev-parse", "--show-toplevel"], check=False)
    except Exception:  # noqa: BLE001 - a missing or broken Git is not fatal here
        return None
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


class ProjectContext:
    """One resolved answer about where this repository's dbt work lives."""

    def __init__(
        self,
        requested_path: Path,
        dbt_root: Path | None,
        layout: DbtProjectLayout | None,
        git_root: Path | None,
        sibling_projects: Sequence[Path] = (),
        discovery_note: str | None = None,
    ) -> None:
        self.requested_path = requested_path
        self.dbt_root = dbt_root
        self.layout = layout
        self.git_root = git_root
        self.sibling_projects = tuple(sibling_projects)
        self.discovery_note = discovery_note

    @property
    def is_dbt_project(self) -> bool:
        return self.dbt_root is not None

    @property
    def latest_version_pointer_default(self) -> bool:
        """Whether every versioned model publishes a latest-version pointer view."""
        return bool(self.layout and self.layout.latest_version_pointer_default)

    def relative_to_project(self, git_relative: str) -> str | None:
        """Translate a Git-root-relative path into a project-relative one.

        Returns None when the path belongs to a different project in the same
        repository. Joining a Git path onto a nested project root, which is what
        the planner used to do, produced `analytics/analytics/models/foo.sql`
        and quietly validated nothing.
        """
        if self.dbt_root is None:
            return None
        base = self.git_root or self.dbt_root
        absolute = (base / git_relative).resolve()
        try:
            relative = absolute.relative_to(self.dbt_root).as_posix()
        except ValueError:
            return None
        for sibling in self.sibling_projects:
            if sibling == self.dbt_root:
                continue
            try:
                sibling.relative_to(self.dbt_root)
            except ValueError:
                continue
            sibling_prefix = sibling.relative_to(self.dbt_root).as_posix()
            if relative == sibling_prefix or relative.startswith(f"{sibling_prefix}/"):
                return None
        return relative

    def absolute(self, project_relative: str) -> Path | None:
        if self.dbt_root is None:
            return None
        return self.dbt_root / project_relative

    def target_dir(self) -> Path | None:
        if self.dbt_root is None or self.layout is None:
            return None
        return self.dbt_root / self.layout.target_path

    def iter_files(self, *, suffixes: Iterable[str] | None = None) -> Iterator[Path]:
        if self.dbt_root is None:
            return
        wanted = {suffix.lower() for suffix in suffixes} if suffixes else None
        for path in inspect_dbt._walk_files(self.dbt_root):
            if wanted is not None and path.suffix.lower() not in wanted:
                continue
            yield path

    def iter_resource_files(self, kind: str, *, suffixes: Iterable[str]) -> Iterator[Path]:
        """Yield project-owned files under the configured directories for a kind."""
        if self.dbt_root is None or self.layout is None:
            return
        wanted = {suffix.lower() for suffix in suffixes}
        for path in self.iter_files(suffixes=wanted):
            relative = path.relative_to(self.dbt_root).as_posix()
            if not self.layout.is_own_code(relative):
                continue
            if self.layout.kind_of(relative) == kind:
                yield path

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_path": str(self.requested_path),
            "git_root": str(self.git_root) if self.git_root else None,
            "dbt_root": str(self.dbt_root) if self.dbt_root else None,
            "is_dbt_project": self.is_dbt_project,
            "layout": self.layout.as_dict() if self.layout else None,
            "sibling_projects": [str(path) for path in self.sibling_projects],
            "discovery_note": self.discovery_note,
        }


def resolve_project_context(
    path: str | Path,
    *,
    discover: bool = True,
) -> ProjectContext:
    """Resolve the active dbt project for a requested directory.

    The requested directory wins when it is itself a project. Otherwise, and only
    when `discover` is set, a single nested project is adopted; several nested
    projects are reported rather than guessed, because picking one would attribute
    another team's models to this one.
    """
    requested = Path(path).expanduser().resolve()
    if not requested.is_dir():
        raise ProjectContextError(f"Project path is not a directory: {requested}")

    git_root = git_root_for(requested)
    project_file = project_file_in(requested)

    if project_file is not None:
        nested = [item for item in discover_projects(requested) if item != requested]
        layout = _layout_for(requested, project_file)
        return ProjectContext(requested, requested, layout, git_root, nested)

    if not discover:
        return ProjectContext(requested, None, None, git_root)

    candidates = discover_projects(requested)
    if not candidates:
        return ProjectContext(requested, None, None, git_root)
    if len(candidates) > 1:
        outermost = [
            candidate
            for candidate in candidates
            if not any(
                candidate != other and candidate.is_relative_to(other)
                for other in candidates
            )
        ]
        if len(outermost) > 1:
            names = ", ".join(
                sorted(item.relative_to(requested).as_posix() for item in outermost)
            )
            return ProjectContext(
                requested,
                None,
                None,
                git_root,
                outermost,
                f"{len(outermost)} dbt projects found ({names}); name one explicitly.",
            )
        candidates = outermost

    chosen = candidates[0]
    nested = [item for item in discover_projects(chosen) if item != chosen]
    project_file = project_file_in(chosen)
    layout = _layout_for(chosen, project_file)
    return ProjectContext(
        requested,
        chosen,
        layout,
        git_root,
        nested,
        f"Resolved the dbt project at {chosen.relative_to(requested).as_posix()}.",
    )


def _layout_for(root: Path, project_file: Path | None) -> DbtProjectLayout:
    project: dict[str, Any] | None = None
    if project_file is not None and project_file.is_file():
        try:
            text = inspect_dbt._read_text(project_file)
        except OSError:
            return DbtProjectLayout(root, None)
        project = inspect_dbt.parse_dbt_project(text)
        # `parse_dbt_project` reads top-level scalars and lists only, which is
        # all the path configuration needs. Behaviour flags live one level down,
        # so the nested reader supplies them.
        nested, _unsupported = parse_yaml_checked(text)
        if isinstance(nested, dict) and isinstance(nested.get("flags"), dict):
            project["flags"] = nested["flags"]
    return DbtProjectLayout(root, project)


def _parser() -> argparse.ArgumentParser:
    parser = inspect_dbt.JsonArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Repository or dbt project directory")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        context = resolve_project_context(args.path)
    except (ProjectContextError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    payload = {"ok": True, **context.as_dict()}
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
