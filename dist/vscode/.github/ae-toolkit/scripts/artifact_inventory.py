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


def _load_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _generated_at(document: Any) -> str | None:
    if not isinstance(document, dict):
        return None
    metadata = document.get("metadata")
    if isinstance(metadata, dict) and metadata.get("generated_at"):
        return str(metadata["generated_at"])
    return None


def _age_hours(generated_at: str | None) -> float | None:
    if not generated_at:
        return None
    text = generated_at.replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
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
    document: Any = None

    @property
    def stale(self) -> bool:
        return self.age_hours is not None and self.age_hours > STALE_AFTER_HOURS

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
        }
        if self.present:
            payload.update(
                {
                    "valid": self.valid,
                    "generated_at": self.generated_at,
                    "age_hours": self.age_hours,
                    "stale": self.stale,
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
    generated_at = _generated_at(document)
    return Artifact(
        kind,
        path,
        present=True,
        valid=True,
        generated_at=generated_at,
        age_hours=_age_hours(generated_at),
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

    def manifest_document(self, *, prior: bool = False) -> Any:
        source = (self.prior or {}) if prior else self.current
        artifact = source.get("manifest")
        if artifact is None or not artifact.present:
            return None
        reloaded = read_artifact("manifest", artifact.path, keep_document=True)
        return reloaded.document if reloaded.valid else None

    def as_dict(self, root: Path | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target_path": Path(self.target_dir).as_posix() if self.target_dir else None,
            "current": {
                kind: artifact.as_dict(root) for kind, artifact in sorted(self.current.items())
            },
            "has_prior_state": self.has_prior_state,
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
        return explicit if explicit.is_dir() else None
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
    nodes = manifest_nodes(document)
    names: set[str] = set()
    for unique_id in unique_ids:
        node = nodes.get(str(unique_id))
        if isinstance(node, dict) and node.get("name"):
            names.add(str(node["name"]))
    return sorted(names)
