#!/usr/bin/env python3
"""Locate and summarize dbt's build artifacts at their configured paths.

Artifacts were previously looked for under a literal `target/`, which misses any
project that configures `target-path`, and prior state was not consulted at all.
Prior state matters: a deleted model's downstream consumers cannot be discovered
from files that no longer exist, and guessing costs either a broken selector or
an unbounded rebuild.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ARTIFACT_FILES = {
    "manifest": "manifest.json",
    "run_results": "run_results.json",
    "sources": "sources.json",
    "catalog": "catalog.json",
    "semantic_manifest": "semantic_manifest.json",
}

# dbt writes deferral state to a separate directory by convention. Neither name
# is guaranteed, so both are checked and reported by the path actually used.
STATE_DIRECTORY_NAMES = ("state", "prod-state", "prod_artifacts")

# Past this age a manifest describes a graph that may no longer exist, so it can
# inform a plan but must not be the sole basis for one.
STALE_AFTER_HOURS = 24.0

# Which artifact proves that a given validation operation actually ran. Reading
# `run_results.json` after a freshness command reports the previous build.
OPERATION_ARTIFACTS = {
    "parse": "manifest",
    "resolve": None,
    "source_freshness": "sources",
    "test": "run_results",
    "model_validation": "run_results",
}


class ArtifactStateError(ValueError):
    """Raised when an explicitly named state directory cannot be used."""


@dataclass
class ArtifactEvidence:
    """One artifact considered as proof that a specific command ran.

    Correlation used to live inside the run-results reader, so a freshness check
    could write a brand-new `sources.json` with the right invocation and still be
    reported as unverified. Every artifact kind now travels the same path.
    """

    kind: str
    path: Path | None
    metadata: dict[str, Any]
    correlated: bool | None
    reason: str

    @property
    def generated_at(self) -> str | None:
        return self.metadata.get("generated_at")

    @property
    def invocation_id(self) -> str | None:
        return self.metadata.get("invocation_id")

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.kind,
            "path": self.path.as_posix() if self.path else None,
            "generated_at": self.generated_at,
            "invocation_id": self.invocation_id,
            "correlated": self.correlated,
            "reason": self.reason,
        }


def correlate(
    metadata: dict[str, Any],
    *,
    since: str | None = None,
    invocation_id: str | None = None,
) -> tuple[bool | None, str]:
    """Whether this artifact was written by the command that just ran.

    An interpreter that says "verified" while reading yesterday's artifact is
    worse than one that says nothing: it retires a real obligation on the
    strength of an unrelated file. The invocation ID is proof; a timestamp is
    only the fallback when no ID was captured.
    """
    if invocation_id:
        recorded = metadata.get("invocation_id")
        if not recorded:
            return False, "The artifact records no invocation ID to compare against."
        matched = recorded == invocation_id
        return matched, (
            "The artifact records the expected invocation."
            if matched
            else "The artifact was written by a different dbt invocation."
        )
    if since:
        boundary = parse_moment(since)
        written = parse_moment(metadata.get("generated_at"))
        if boundary is None or written is None:
            return False, "The artifact carries no comparable generation time."
        matched = written > boundary
        return matched, (
            "The artifact was written after the command started."
            if matched
            else "The artifact predates the command, so it describes an earlier run."
        )
    return None, (
        "No expected invocation or start time was supplied, so the artifact "
        "cannot be tied to a specific command."
    )


def _load_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def artifact_metadata(document: Any) -> dict[str, Any]:
    """The provenance block dbt writes into every artifact."""
    metadata = document.get("metadata") if isinstance(document, dict) else None
    if not isinstance(metadata, dict):
        return {}
    return {
        "generated_at": str(metadata["generated_at"]) if metadata.get("generated_at") else None,
        "invocation_id": str(metadata["invocation_id"])
        if metadata.get("invocation_id")
        else None,
        "invocation_started_at": str(metadata["invocation_started_at"])
        if metadata.get("invocation_started_at")
        else None,
        "schema_version": str(metadata["dbt_schema_version"])
        if metadata.get("dbt_schema_version")
        else None,
        "dbt_version": str(metadata["dbt_version"]) if metadata.get("dbt_version") else None,
    }


def parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _age_hours(generated_at: str | None) -> float | None:
    moment = parse_moment(generated_at)
    if moment is None:
        return None
    delta = datetime.now(timezone.utc) - moment
    return round(delta.total_seconds() / 3600.0, 2)


@dataclass
class Artifact:
    """One dbt artifact file, with enough context to judge whether to trust it."""

    kind: str
    path: Path
    present: bool
    valid: bool = False
    error: str | None = None
    generated_at: str | None = None
    age_hours: float | None = None
    invocation_id: str | None = None
    invocation_started_at: str | None = None
    schema_version: str | None = None
    dbt_version: str | None = None
    document: Any = None

    @property
    def stale(self) -> bool:
        return self.age_hours is not None and self.age_hours > STALE_AFTER_HOURS

    @property
    def trust(self) -> str:
        """A missing artifact and an old one are different problems."""
        if not self.present:
            return "missing"
        if not self.valid:
            return "unreadable"
        return "stale" if self.stale else "current"

    def as_dict(self, root: Path | None = None) -> dict[str, Any]:
        location = self.path
        if root is not None:
            try:
                location = self.path.relative_to(root)
            except ValueError:
                pass
        payload: dict[str, Any] = {
            "kind": self.kind,
            "path": Path(location).as_posix(),
            "present": self.present,
            "trust": self.trust,
        }
        if self.present:
            payload.update(
                {
                    "valid": self.valid,
                    "generated_at": self.generated_at,
                    "age_hours": self.age_hours,
                    "stale": self.stale,
                    "invocation_id": self.invocation_id,
                    "invocation_started_at": self.invocation_started_at,
                    "schema_version": self.schema_version,
                    "dbt_version": self.dbt_version,
                }
            )
        if self.error:
            payload["error"] = self.error
        return payload


def read_artifact(kind: str, path: Path, *, keep_document: bool = False) -> Artifact:
    if not path.is_file():
        return Artifact(kind, path, present=False)
    document, error = _load_json(path)
    if error is not None:
        return Artifact(kind, path, present=True, valid=False, error=error)
    metadata = artifact_metadata(document)
    return Artifact(
        kind,
        path,
        present=True,
        valid=True,
        generated_at=metadata.get("generated_at"),
        age_hours=_age_hours(metadata.get("generated_at")),
        invocation_id=metadata.get("invocation_id"),
        invocation_started_at=metadata.get("invocation_started_at"),
        schema_version=metadata.get("schema_version"),
        dbt_version=metadata.get("dbt_version"),
        document=document if keep_document else None,
    )


@dataclass
class ArtifactInventory:
    """Which artifacts exist for this project, current and prior."""

    target_dir: Path | None
    current: dict[str, Artifact]
    state_dir: Path | None = None
    prior: dict[str, Artifact] | None = None

    @property
    def has_prior_state(self) -> bool:
        prior = self.prior or {}
        manifest = prior.get("manifest")
        return bool(manifest and manifest.valid)

    @property
    def state_is_stale(self) -> bool:
        """Whether prior state is old enough that it may describe a dead graph."""
        prior = self.prior or {}
        manifest = prior.get("manifest")
        return bool(manifest and manifest.valid and manifest.stale)

    def manifest_document(self, *, prior: bool = False) -> Any:
        source = (self.prior or {}) if prior else self.current
        artifact = source.get("manifest")
        if artifact is None or not artifact.present:
            return None
        reloaded = read_artifact("manifest", artifact.path, keep_document=True)
        return reloaded.document if reloaded.valid else None

    def artifact_for(self, operation: str, *, prior: bool = False) -> Artifact | None:
        """The one artifact that can prove this operation ran."""
        kind = OPERATION_ARTIFACTS.get(operation)
        if kind is None:
            return None
        source = (self.prior or {}) if prior else self.current
        return source.get(kind)

    def resolve_operation_paths(self, operation: str | None) -> dict[str, Path | None]:
        """Which artifact files an operation is entitled to read.

        Resolving this in two places let the planner name one artifact while the
        interpreter read another.
        """

        def located(kind: str) -> Path | None:
            artifact = self.current.get(kind)
            return artifact.path if artifact and artifact.present else None

        if operation is None:
            return {"run_results": located("run_results"), "sources": located("sources")}
        kind = OPERATION_ARTIFACTS.get(operation)
        return {
            "run_results": located("run_results") if kind == "run_results" else None,
            "sources": located("sources") if kind == "sources" else None,
        }

    def as_dict(self, root: Path | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target_path": Path(self.target_dir).as_posix() if self.target_dir else None,
            "current": {
                kind: artifact.as_dict(root) for kind, artifact in sorted(self.current.items())
            },
            "has_prior_state": self.has_prior_state,
            "state_is_stale": self.state_is_stale,
        }
        if self.state_dir is not None:
            payload["state_path"] = Path(self.state_dir).as_posix()
        if self.prior:
            payload["prior"] = {
                kind: artifact.as_dict(root) for kind, artifact in sorted(self.prior.items())
            }
        return payload


def _state_directory(root: Path, target_dir: Path | None, explicit: Path | None) -> Path | None:
    if explicit is not None:
        # Silently downgrading a typo to "no state" produced a plan that asked
        # for scope the user had just supplied.
        if not explicit.exists():
            raise ArtifactStateError(f"The state path you named does not exist: {explicit}")
        if not explicit.is_dir():
            raise ArtifactStateError(f"The state path you named is not a directory: {explicit}")
        return explicit
    for name in STATE_DIRECTORY_NAMES:
        candidate = root / name
        if candidate.is_dir() and (candidate / "manifest.json").is_file():
            return candidate
    if target_dir is not None:
        candidate = target_dir / "prior"
        if candidate.is_dir():
            return candidate
    return None


def inventory_artifacts(context: Any, *, state_dir: str | Path | None = None) -> ArtifactInventory:
    """Collect current and prior artifacts using the project's configured paths."""
    if not getattr(context, "is_dbt_project", False):
        return ArtifactInventory(None, {})
    root = context.dbt_root
    target_dir = context.target_dir()
    current = {
        kind: read_artifact(kind, target_dir / filename)
        for kind, filename in ARTIFACT_FILES.items()
    }
    resolved_state = _state_directory(
        root, target_dir, Path(state_dir).expanduser().resolve() if state_dir else None
    )
    prior = None
    if resolved_state is not None:
        prior = {
            kind: read_artifact(kind, resolved_state / filename)
            for kind, filename in ARTIFACT_FILES.items()
        }
    return ArtifactInventory(target_dir, current, resolved_state, prior)


def manifest_nodes(document: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict):
        return {}
    nodes = document.get("nodes")
    result = dict(nodes) if isinstance(nodes, dict) else {}
    sources = document.get("sources")
    if isinstance(sources, dict):
        result.update(sources)
    return {key: value for key, value in result.items() if isinstance(value, dict)}


def downstream_from_manifest(document: Any, unique_ids: Iterable[str]) -> list[str]:
    """Transitive children of the given nodes, read from a manifest's child map.

    This is the only way to learn what depended on a resource that has already
    been deleted from the working tree.
    """
    if not isinstance(document, dict):
        return []
    child_map = document.get("child_map")
    if not isinstance(child_map, dict):
        child_map = {}
        for unique_id, node in manifest_nodes(document).items():
            depends = node.get("depends_on")
            parents = depends.get("nodes") if isinstance(depends, dict) else []
            for parent in parents or []:
                child_map.setdefault(str(parent), []).append(unique_id)

    seen: set[str] = set()
    frontier = [str(item) for item in unique_ids]
    while frontier:
        current = frontier.pop()
        for child in child_map.get(current, []) or []:
            child_id = str(child)
            if child_id in seen:
                continue
            seen.add(child_id)
            frontier.append(child_id)
    return sorted(seen)


def node_names(document: Any, unique_ids: Iterable[str]) -> list[str]:
    """Selector-ready names for manifest nodes, versions included.

    Returning a bare `fct_revenue` for `model.finance.fct_revenue.v2` produces a
    selector that resolves to every version, or to nothing.
    """
    nodes = manifest_nodes(document)
    names: set[str] = set()
    for unique_id in unique_ids:
        node = nodes.get(str(unique_id))
        if not isinstance(node, dict) or not node.get("name"):
            continue
        name = str(node["name"])
        version = node.get("version")
        if version not in (None, "") and not isinstance(version, bool):
            version_text = (
                str(int(version))
                if isinstance(version, float) and version.is_integer()
                else str(version)
            )
            name = f"{name}.v{version_text}"
        names.add(name)
    return sorted(names)
