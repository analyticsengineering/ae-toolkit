#!/usr/bin/env python3
"""Plan the smallest set of dbt validations a change set actually requires.

This script never executes dbt. It emits a deterministic JSON plan for an agent
to preview and approve before running any warehouse-capable command.

A change set is rarely one thing. Editing a model, retuning a source's freshness,
and adding a singular test in the same branch are three independent validations,
and collapsing them into one intent either skips work or does far too much. The
plan therefore describes ordered, independently bounded operations. The older
single-`intent` fields are still derived from those operations so existing
callers keep working.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import artifact_inventory  # noqa: E402
import git_scope  # noqa: E402
import infer_conventions  # noqa: E402
import inspect_dbt  # noqa: E402
import inspect_git  # noqa: E402
import project_context  # noqa: E402
import resource_identity  # noqa: E402


PLAN_VERSION = 2

PRODUCTION_TARGET = re.compile(
    r"(?:^|[-_])(?:prod|production|prd|main)(?:$|[-_])",
    re.IGNORECASE,
)
WAREHOUSE_INTENTS = {"compile", "test", "run", "build", "source_freshness"}
INTENT_RANK = {
    "static": 0,
    "compile": 1,
    "source_freshness": 2,
    "test": 3,
    "run": 4,
    "build": 5,
}

DEPENDENCY_WIDE_FILENAMES = {
    "dbt_project.yml",
    "dbt_project.yaml",
    "packages.yml",
    "packages.yaml",
    "dependencies.yml",
    "dependencies.yaml",
    "profiles.yml",
}


class ValidationPlanError(ValueError):
    """Raised when repository evidence cannot produce a safe validation plan."""


# --- YAML change classification ----------------------------------------------


def _document_models(document: Any) -> list[str]:
    models = document.get("models") if isinstance(document, dict) else None
    if not isinstance(models, list):
        return []
    return sorted(
        {str(model["name"]) for model in models if isinstance(model, dict) and model.get("name")}
    )


def _unit_test_models(document: Any) -> list[str]:
    unit_tests = document.get("unit_tests") if isinstance(document, dict) else None
    if not isinstance(unit_tests, list):
        return []
    return sorted(
        {str(test["model"]) for test in unit_tests if isinstance(test, dict) and test.get("model")}
    )


def _document_sources(document: Any) -> list[dict[str, str]]:
    sources = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(sources, list):
        return []
    resources: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, dict) or not source.get("name"):
            continue
        source_name = str(source["name"])
        tables = source.get("tables") if isinstance(source.get("tables"), list) else []
        for table in tables:
            if isinstance(table, dict) and table.get("name"):
                resources.append({"source": source_name, "table": str(table["name"])})
    return sorted(resources, key=lambda item: (item["source"], item["table"]))


def _changed_source_resources(
    before: dict[str, Any],
    current: dict[str, Any],
) -> list[dict[str, str]]:
    def source_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        sources = document.get("sources")
        if not isinstance(sources, list):
            return {}
        return {
            str(source["name"]): source
            for source in sources
            if isinstance(source, dict) and source.get("name")
        }

    changed: set[tuple[str, str]] = set()
    old_sources, new_sources = source_map(before), source_map(current)
    for source_name in sorted(set(old_sources) | set(new_sources)):
        old_source = old_sources.get(source_name, {})
        new_source = new_sources.get(source_name, {})

        def tables(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
            entries = source.get("tables")
            if not isinstance(entries, list):
                return {}
            return {
                str(table["name"]): table
                for table in entries
                if isinstance(table, dict) and table.get("name")
            }

        old_tables, new_tables = tables(old_source), tables(new_source)
        old_header = {key: value for key, value in old_source.items() if key != "tables"}
        new_header = {key: value for key, value in new_source.items() if key != "tables"}
        if old_header != new_header:
            changed.update((source_name, table) for table in set(old_tables) | set(new_tables))
            continue
        for table_name in set(old_tables) | set(new_tables):
            if old_tables.get(table_name) != new_tables.get(table_name):
                changed.add((source_name, table_name))
    return [{"source": source, "table": table} for source, table in sorted(changed)]


def _without_keys(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {key: _without_keys(item, keys) for key, item in value.items() if key not in keys}
    if isinstance(value, list):
        return [_without_keys(item, keys) for item in value]
    return value


def _without_keys_pruned(value: Any, keys: set[str]) -> Any:
    """Remove nested keys and containers made empty by that removal."""
    if isinstance(value, dict):
        result = {
            key: _without_keys_pruned(item, keys) for key, item in value.items() if key not in keys
        }
        return {key: item for key, item in result.items() if item not in ({}, [])}
    if isinstance(value, list):
        return [_without_keys_pruned(item, keys) for item in value]
    return value


def _parse_yaml_text(text: str) -> tuple[dict[str, Any], list[str]]:
    document, unsupported = project_context.parse_yaml_checked(text)
    return (document if isinstance(document, dict) else {}), unsupported


def _metadata_only_document(document: dict[str, Any]) -> bool:
    if set(document) - {"version", "models"}:
        return False
    models = document.get("models")
    if not isinstance(models, list):
        return False
    for model in models:
        if not isinstance(model, dict) or set(model) - {
            "name",
            "description",
            "columns",
            "tests",
            "data_tests",
        }:
            return False
        for column in model.get("columns") or []:
            if not isinstance(column, dict) or set(column) - {
                "name",
                "description",
                "tests",
                "data_tests",
            }:
                return False
    return True


def _contains_test_declaration(value: Any) -> bool:
    if isinstance(value, dict):
        if "tests" in value or "data_tests" in value:
            return True
        return any(_contains_test_declaration(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_test_declaration(item) for item in value)
    return False


def _source_change_kind(before: dict[str, Any], current: dict[str, Any]) -> str:
    """Classify source YAML without treating resource SLAs as model contracts."""
    if before == current:
        return "formatting_or_comments_only"
    if _without_keys(before, {"description"}) == _without_keys(current, {"description"}):
        return "description_only"
    if _without_keys(before, {"description", "tests", "data_tests"}) == _without_keys(
        current, {"description", "tests", "data_tests"}
    ):
        return "test_only"
    if _without_keys_pruned(before, {"loaded_at_field", "freshness"}) == _without_keys_pruned(
        current, {"loaded_at_field", "freshness"}
    ):
        return "source_freshness"
    return "source_contract"


def _semantic_resources(document: dict[str, Any]) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for key, resource_type in (
        ("semantic_models", "semantic_model"),
        ("metrics", "metric"),
        ("saved_queries", "saved_query"),
    ):
        entries = document.get(key)
        if not isinstance(entries, list):
            continue
        resources.extend(
            {"resource_type": resource_type, "name": str(entry["name"])}
            for entry in entries
            if isinstance(entry, dict) and entry.get("name")
        )
    return resources


@dataclass
class YamlChange:
    kind: str
    models: list[str] = field(default_factory=list)
    semantic: list[dict[str, str]] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def _yaml_change(
    context: project_context.ProjectContext,
    change: git_scope.ChangedPath,
) -> YamlChange:
    root = context.git_root or context.dbt_root
    path = context.absolute(change.path)

    if change.is_removal or path is None or not path.is_file():
        previous_git_path = change.original_git_path or change.git_path
        text = git_scope.previous_text(root, previous_git_path)
        if text is None:
            return YamlChange("rename_or_delete")
        before, unsupported = _parse_yaml_text(text)
        return YamlChange(
            "rename_or_delete",
            _document_models(before),
            _semantic_resources(before),
            _document_sources(before),
            unsupported,
        )

    current_text = path.read_text(encoding="utf-8", errors="replace")
    current, unsupported = _parse_yaml_text(current_text)
    models = sorted(set([*_document_models(current), *_unit_test_models(current)]))
    semantic = _semantic_resources(current)
    sources = _document_sources(current)
    if unsupported:
        return YamlChange("unsupported_yaml", models, semantic, sources, unsupported)

    previous_raw = git_scope.previous_text(root, change.git_path)
    if previous_raw is None:
        if semantic:
            return YamlChange("semantic_or_metric", models, semantic, sources)
        if sources:
            return YamlChange(_source_change_kind({}, current), models, [], sources)
        if _unit_test_models(current):
            return YamlChange("test_only", models)
        if _metadata_only_document(current):
            kind = "test_only" if _contains_test_declaration(current) else "description_only"
            return YamlChange(kind, models)
        return YamlChange("contract", models)

    before, before_unsupported = _parse_yaml_text(previous_raw)
    if before_unsupported:
        return YamlChange(
            "unsupported_yaml", models, semantic, sources, sorted(set(before_unsupported))
        )

    source_resources = _changed_source_resources(before, current)
    sources_changed = before.get("sources") != current.get("sources")
    if not sources_changed:
        source_resources = []
    if before == current:
        return YamlChange("formatting_or_comments_only", models, [], source_resources)
    if sources_changed:
        # A mixed model/source document still gets the more conservative source
        # classification when the source block changed.
        changed_models = models if before.get("models") != current.get("models") else []
        return YamlChange(
            _source_change_kind(before, current), changed_models, semantic, source_resources
        )
    if before.get("unit_tests") != current.get("unit_tests") and _without_keys(
        before, {"unit_tests"}
    ) == _without_keys(current, {"unit_tests"}):
        return YamlChange(
            "test_only",
            sorted(set([*_unit_test_models(before), *_unit_test_models(current)])),
            semantic,
            source_resources,
        )
    if _without_keys(before, {"description"}) == _without_keys(current, {"description"}):
        return YamlChange("description_only", models, [], source_resources)
    if _without_keys(before, {"description", "tests", "data_tests"}) == _without_keys(
        current, {"description", "tests", "data_tests"}
    ):
        return YamlChange("test_only", models, [], source_resources)
    if any(
        before.get(key) != current.get(key)
        for key in ("semantic_models", "metrics", "saved_queries")
    ):
        semantic_by_identity = {
            (item["resource_type"], item["name"]): item
            for item in [*_semantic_resources(before), *semantic]
        }
        return YamlChange(
            "semantic_or_metric",
            models,
            sorted(
                semantic_by_identity.values(),
                key=lambda item: (item["resource_type"], item["name"]),
            ),
            source_resources,
        )
    return YamlChange("contract", models, [], source_resources)


# --- Change set ---------------------------------------------------------------


@dataclass
class ChangeSet:
    """Every independent validation obligation the change set creates."""

    build_models: dict[str, bool] = field(default_factory=dict)
    test_selectors: dict[str, str] = field(default_factory=dict)
    freshness_sources: list[dict[str, str]] = field(default_factory=list)
    models: set[str] = field(default_factory=set)
    semantic_resources: list[dict[str, str]] = field(default_factory=list)
    source_resources: list[dict[str, str]] = field(default_factory=list)
    singular_tests: set[str] = field(default_factory=set)
    unresolved_dependency_changes: set[str] = field(default_factory=set)
    yaml_change_kinds: dict[str, str] = field(default_factory=dict)
    unsupported_yaml: dict[str, list[str]] = field(default_factory=dict)
    unresolvable_deletions: list[dict[str, Any]] = field(default_factory=list)
    state_evidence: str | None = None

    def want_build(self, name: str, *, downstream: bool = False) -> None:
        self.build_models[name] = self.build_models.get(name, False) or downstream
        self.models.add(name)

    def want_test(self, selector: str, reason: str) -> None:
        self.test_selectors.setdefault(selector, reason)


def _source_consumers(
    index: resource_identity.ResourceIndex,
    resources: Sequence[dict[str, str]],
) -> set[str]:
    refs = [
        resource_identity.ResourceRef(
            resource_identity.SOURCE, item["table"], source_name=item["source"]
        )
        for item in resources
    ]
    return {
        resource.name
        for resource in index.consumers_of(refs)
        if resource.resource_type == resource_identity.MODEL
    }


def _downstream_model_names(
    index: resource_identity.ResourceIndex,
    names: Iterable[str],
) -> set[str]:
    refs = [resource_identity.ResourceRef(resource_identity.MODEL, name) for name in names]
    return {
        resource.name
        for resource in index.downstream_of(refs)
        if resource.resource_type == resource_identity.MODEL
    }


def _deleted_model_downstream(
    context: project_context.ProjectContext,
    inventory: artifact_inventory.ArtifactInventory,
    name: str,
) -> tuple[list[str], str, str]:
    """Find what depended on a model that no longer exists on disk.

    Selecting `deleted_model+` cannot work: dbt has no node to anchor the
    selector to. Prior build state is the only record of the edge, so it is
    consulted before falling back to requiring an explicit scope.
    """
    project = context.layout.name if context.layout else None
    unique_id = f"model.{project}.{name}" if project else None
    for prior, label in ((True, "prior state"), (False, "current manifest")):
        document = inventory.manifest_document(prior=prior)
        if document is None or unique_id is None:
            continue
        nodes = artifact_inventory.manifest_nodes(document)
        if unique_id not in nodes:
            continue
        children = artifact_inventory.downstream_from_manifest(document, [unique_id])
        return (
            artifact_inventory.node_names(document, children),
            "high" if prior else "medium",
            label,
        )
    return [], "low", "none"


def classify_changes(
    context: project_context.ProjectContext,
    index: resource_identity.ResourceIndex,
    inventory: artifact_inventory.ArtifactInventory,
    scope: git_scope.GitScope,
) -> ChangeSet:
    """Turn normalized changes into independent validation obligations."""
    changes = ChangeSet()
    for path, constructs in index.unsupported_yaml.items():
        changes.unsupported_yaml.setdefault(path, constructs)

    for change in scope.changes:
        relative = change.path
        suffix = Path(relative).suffix.lower()
        kind = context.layout.kind_of(relative) if context.layout else None
        filename = Path(relative).name

        if filename in DEPENDENCY_WIDE_FILENAMES:
            changes.unresolved_dependency_changes.add(relative)
            continue

        if kind == "model" and suffix in resource_identity.MODEL_SUFFIXES:
            name, _version, _language = resource_identity.classify_model_file(relative)
            if change.is_removal:
                downstream, confidence, evidence = _deleted_model_downstream(
                    context, inventory, name
                )
                changes.state_evidence = evidence
                if downstream:
                    for child in downstream:
                        changes.want_build(child)
                    changes.models.add(name)
                elif confidence == "low":
                    changes.unresolvable_deletions.append(
                        {
                            "resource_type": "model",
                            "name": name,
                            "path": relative,
                            "reason": (
                                "The model was deleted and no prior dbt state records what "
                                "depended on it, so downstream scope cannot be resolved."
                            ),
                        }
                    )
                    changes.models.add(name)
                else:
                    changes.models.add(name)
            else:
                changes.want_build(name)
            continue

        if kind == "test" and suffix in {".sql", ".py"}:
            test_name = Path(relative).stem
            changes.singular_tests.add(test_name)
            changes.want_test(test_name, "A singular test changed.")
            absolute = context.absolute(relative)
            if absolute is not None and absolute.is_file():
                for ref in resource_identity.parse_refs(
                    absolute.read_text(encoding="utf-8", errors="replace")
                ):
                    if ref.resource_type == resource_identity.MODEL:
                        changes.models.add(ref.name)
                    else:
                        changes.source_resources.append(
                            {"source": str(ref.source_name), "table": ref.name}
                        )
            continue

        if kind == "macro" and suffix == ".sql":
            changes.unresolved_dependency_changes.add(relative)
            continue

        if kind == "snapshot" and suffix == ".sql":
            changes.want_build(Path(relative).stem)
            continue

        if kind == "seed" and suffix == ".csv":
            changes.want_build(Path(relative).stem)
            continue

        if suffix in {".yml", ".yaml"}:
            yaml_change = _yaml_change(context, change)
            changes.yaml_change_kinds[relative] = yaml_change.kind
            if yaml_change.unsupported:
                changes.unsupported_yaml[relative] = yaml_change.unsupported
                changes.unresolved_dependency_changes.add(relative)
            changes.models.update(yaml_change.models)
            changes.semantic_resources.extend(yaml_change.semantic)
            changes.source_resources.extend(yaml_change.sources)
            consumers = _source_consumers(index, yaml_change.sources)
            changes.models.update(consumers)

            if yaml_change.kind in {"contract", "rename_or_delete"}:
                for name in yaml_change.models:
                    changes.want_build(name, downstream=True)
            elif yaml_change.kind == "source_contract":
                for name in consumers:
                    changes.want_build(name, downstream=True)
            elif yaml_change.kind == "source_freshness":
                changes.freshness_sources.extend(yaml_change.sources)
            elif yaml_change.kind == "test_only":
                if yaml_change.sources:
                    for source in yaml_change.sources:
                        changes.want_test(
                            f"source:{source['source']}.{source['table']}",
                            "Source test declarations changed.",
                        )
                for name in yaml_change.models:
                    changes.want_test(name, "Test declarations changed.")
            continue

    source_by_identity = {
        (item["source"], item["table"]): item for item in changes.source_resources
    }
    changes.source_resources = sorted(
        source_by_identity.values(), key=lambda item: (item["source"], item["table"])
    )
    freshness_by_identity = {
        (item["source"], item["table"]): item for item in changes.freshness_sources
    }
    changes.freshness_sources = sorted(
        freshness_by_identity.values(), key=lambda item: (item["source"], item["table"])
    )
    semantic_by_identity = {
        (item["resource_type"], item["name"]): item for item in changes.semantic_resources
    }
    changes.semantic_resources = sorted(
        semantic_by_identity.values(), key=lambda item: (item["resource_type"], item["name"])
    )
    return changes


# --- Steps --------------------------------------------------------------------


@dataclass
class ValidationStep:
    operation: str
    intent: str
    selectors: list[str]
    purpose: str
    reason: str
    executes_warehouse: bool
    requires_approval: bool
    confidence: str = "high"
    blocked_reason: str | None = None
    command: str | None = None

    def as_dict(self, order: int) -> dict[str, Any]:
        payload = {
            "step": order,
            "operation": self.operation,
            "intent": self.intent,
            "selectors": list(self.selectors),
            "command": self.command,
            "executes_warehouse": self.executes_warehouse,
            "requires_approval": self.requires_approval,
            "purpose": self.purpose,
            "reason": self.reason,
            "confidence": self.confidence,
        }
        if self.blocked_reason:
            payload["blocked_reason"] = self.blocked_reason
        return payload


def _command(*parts: str) -> str:
    return shlex.join(parts)


def model_display_selectors(
    changes: ChangeSet,
    build_models: dict[str, bool],
    *,
    explicit_models: Sequence[str],
) -> list[str]:
    """Every model the change set touches, whether or not it must be rebuilt.

    A description edit still needs its selector resolved so a reader can confirm
    the plan is pointed at the right models, even though nothing will be built.
    """
    names = set(explicit_models) if explicit_models else set(changes.models) | set(build_models)
    return [f"{name}+" if build_models.get(name) else name for name in sorted(names)]


def _narrow(requested: str, natural: str, *, allow_broader: bool) -> str:
    """Reconcile the user's intent with what one operation actually justifies.

    A requested intent narrower than the evidence is honoured, because the user
    may be deliberately taking a smaller step. A broader one is refused unless
    explicitly allowed, because over-validation is how a bounded check becomes a
    warehouse-wide rebuild nobody asked for.
    """
    if requested == natural:
        return natural
    if INTENT_RANK.get(requested, 0) > INTENT_RANK.get(natural, 0):
        return requested if allow_broader else natural
    return requested


def build_obligations(
    changes: ChangeSet,
    *,
    explicit_models: Sequence[str],
    changes_present: bool,
    override: bool = False,
) -> dict[str, bool]:
    """Decide which models must actually be rebuilt.

    Naming models supplies scope, not work. When the evidence already settles
    what changed, an explicit list narrows the obligations that exist; it does
    not manufacture a build out of a description edit. When the evidence cannot
    settle it — a macro edit, a semantic change, a deletion with no prior state,
    or a clean tree — the named models are the only scope available, and so it is
    when the user has explicitly overridden the recommendation.
    """
    if not explicit_models:
        return dict(changes.build_models)
    if override:
        return {name: changes.build_models.get(name, False) for name in explicit_models}
    unresolvable = bool(
        changes.unresolved_dependency_changes
        or changes.semantic_resources
        or changes.unresolvable_deletions
        or changes.unsupported_yaml
    )
    if unresolvable or not changes_present:
        return {name: changes.build_models.get(name, False) for name in explicit_models}
    return {
        name: downstream
        for name, downstream in changes.build_models.items()
        if name in set(explicit_models)
    }


def build_steps(
    context: project_context.ProjectContext,
    changes: ChangeSet,
    *,
    explicit_models: Sequence[str],
    requested_intent: str,
    allow_broader_intent: bool,
    target: str | None,
    changes_present: bool,
) -> list[ValidationStep]:
    """Produce the ordered, independently bounded operations for a change set."""
    root = str(context.dbt_root)
    steps: list[ValidationStep] = [
        ValidationStep(
            operation="parse",
            intent="static",
            selectors=[],
            purpose="Validate project parsing, Jinja, and graph construction.",
            reason="Static parsing is always safe and catches graph breakage first.",
            executes_warehouse=False,
            requires_approval=False,
            command=_command("dbt", "parse", "--project-dir", root),
        )
    ]

    build_models = build_obligations(
        changes,
        explicit_models=explicit_models,
        changes_present=changes_present,
        override=allow_broader_intent and requested_intent in WAREHOUSE_INTENTS,
    )
    build_selectors = [
        f"{name}+" if downstream else name for name, downstream in sorted(build_models.items())
    ]
    model_selectors = model_display_selectors(
        changes, build_models, explicit_models=explicit_models
    )
    semantic_selectors = [f"{item['name']}+" for item in changes.semantic_resources]
    source_selectors = [
        f"source:{item['source']}.{item['table']}" for item in changes.source_resources
    ]
    freshness_selectors = [
        f"source:{item['source']}.{item['table']}" for item in changes.freshness_sources
    ]
    test_selectors = sorted(changes.test_selectors)
    if explicit_models:
        test_selectors = [
            selector for selector in test_selectors if selector in set(explicit_models)
        ]

    # `dbt build` already runs a model's tests, so a model in the build step is
    # dropped from the test step rather than validated twice.
    built = set(build_models)
    test_selectors = [selector for selector in test_selectors if selector not in built]

    resolution_selectors = sorted(
        set([*model_selectors, *semantic_selectors, *source_selectors, *test_selectors])
    )
    if resolution_selectors:
        steps.append(
            ValidationStep(
                operation="resolve",
                intent="static",
                selectors=resolution_selectors,
                purpose="Confirm the selector resolves only the intended resources.",
                reason="Selector resolution is checked before anything touches the warehouse.",
                executes_warehouse=False,
                requires_approval=False,
                command=_command(
                    "dbt", "ls", "--project-dir", root, "--select", *resolution_selectors, "--output", "name"
                ),
            )
        )

    if freshness_selectors:
        intent = _narrow(
            requested_intent, "source_freshness", allow_broader=allow_broader_intent
        )
        if intent == "source_freshness":
            steps.append(
                ValidationStep(
                    operation="source_freshness",
                    intent="source_freshness",
                    selectors=freshness_selectors,
                    purpose="Validate freshness for only the changed source tables.",
                    reason="Freshness or loaded-at configuration changed for these sources.",
                    executes_warehouse=True,
                    requires_approval=True,
                )
            )

    if test_selectors:
        intent = _narrow(requested_intent, "test", allow_broader=allow_broader_intent)
        if intent in WAREHOUSE_INTENTS:
            reasons = sorted({changes.test_selectors[name] for name in test_selectors if name in changes.test_selectors})
            steps.append(
                ValidationStep(
                    operation="test",
                    intent=intent,
                    selectors=test_selectors,
                    purpose="Run only the tests whose declarations changed.",
                    reason=" ".join(reasons) or "Test declarations changed.",
                    executes_warehouse=True,
                    requires_approval=True,
                )
            )

    if build_selectors:
        intent = _narrow(requested_intent, "build", allow_broader=allow_broader_intent)
        if intent in WAREHOUSE_INTENTS:
            steps.append(
                ValidationStep(
                    operation="model_validation",
                    intent=intent,
                    selectors=build_selectors,
                    purpose=f"Run bounded {intent} validation for the selected resources.",
                    reason=(
                        "Model code, contract, rename, or deletion changes require model "
                        "and test validation."
                    ),
                    executes_warehouse=True,
                    requires_approval=True,
                    confidence="medium" if changes.unresolvable_deletions else "high",
                )
            )

    for step in steps:
        if not step.executes_warehouse:
            continue
        command_intent = ("source", "freshness") if step.intent == "source_freshness" else (step.intent,)
        step.command = _command(
            "dbt",
            *command_intent,
            "--project-dir",
            root,
            "--select",
            *step.selectors,
            *(("--target", str(target)) if target else ()),
        )
    return steps


def _blocking_reason(
    changes: ChangeSet,
    steps: Sequence[ValidationStep],
    *,
    explicit_models: Sequence[str],
    requested_intent: str,
    target: str | None,
) -> str | None:
    warehouse_steps = [step for step in steps if step.executes_warehouse]
    if changes.unsupported_yaml and not explicit_models and requested_intent in WAREHOUSE_INTENTS:
        paths = ", ".join(sorted(changes.unsupported_yaml))
        return (
            f"Unsupported YAML constructs in {paths} prevent a reliable change "
            "classification; name the affected models explicitly."
        )
    if (
        changes.unresolved_dependency_changes
        and not explicit_models
        and requested_intent in WAREHOUSE_INTENTS
    ):
        return (
            "Macro, package, or project configuration changes require an explicit "
            "affected model scope before warehouse validation."
        )
    if changes.semantic_resources and not explicit_models and requested_intent in WAREHOUSE_INTENTS:
        return (
            "Semantic or metric changes require an explicit affected model scope "
            "before warehouse validation."
        )
    if changes.unresolvable_deletions and not explicit_models:
        names = ", ".join(sorted(item["name"] for item in changes.unresolvable_deletions))
        return (
            f"Deleted resources ({names}) have no prior dbt state recording their "
            "consumers; name the affected downstream models explicitly."
        )
    if not warehouse_steps:
        if requested_intent in WAREHOUSE_INTENTS and not any(
            [changes.build_models, changes.test_selectors, changes.freshness_sources, explicit_models]
        ):
            return "No changed or explicitly named dbt models established a bounded scope."
        return None
    if not target:
        return "A local or development target must be named explicitly before warehouse validation."
    if PRODUCTION_TARGET.search(target):
        return (
            f"Target {target!r} appears production-like and is not eligible for "
            "automated validation."
        )
    return None


def plan_validation(
    path: str | Path,
    *,
    models: Sequence[str] | None = None,
    paths: Sequence[str] | None = None,
    target: str | None = None,
    intent: str = "build",
    allow_broader_intent: bool = False,
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    if intent not in {"static", *WAREHOUSE_INTENTS}:
        raise ValidationPlanError(f"Unsupported validation intent: {intent}")

    try:
        context = project_context.resolve_project_context(path)
    except project_context.ProjectContextError as exc:
        raise ValidationPlanError(str(exc)) from exc
    if not context.is_dbt_project:
        if context.discovery_note:
            raise ValidationPlanError(context.discovery_note)
        raise ValidationPlanError("No dbt_project.yml was found.")

    index = resource_identity.build_index(context)
    inventory = artifact_inventory.inventory_artifacts(context, state_dir=state_dir)
    scope = git_scope.collect_scope(context)
    if paths:
        scope = git_scope.restrict_to(scope, paths)

    changes = classify_changes(context, index, inventory, scope)
    explicit = sorted({item.strip() for item in (models or []) if item.strip()})
    excluded = list(scope.excluded_changes)
    if explicit:
        for relative in sorted(changes.unresolved_dependency_changes):
            excluded.append(
                {"path": relative, "reason": "superseded by the requested model scope"}
            )

    steps = build_steps(
        context,
        changes,
        explicit_models=explicit,
        requested_intent=intent,
        allow_broader_intent=allow_broader_intent,
        target=target,
        changes_present=bool(scope.changes),
    )
    build_models = build_obligations(
        changes,
        explicit_models=explicit,
        changes_present=bool(scope.changes),
        override=allow_broader_intent and intent in WAREHOUSE_INTENTS,
    )
    blocked_reason = _blocking_reason(
        changes,
        steps,
        explicit_models=explicit,
        requested_intent=intent,
        target=target,
    )
    warehouse_steps = [step for step in steps if step.executes_warehouse]
    if blocked_reason:
        steps = [step for step in steps if not step.executes_warehouse]

    natural_intent = "static"
    if changes.freshness_sources:
        natural_intent = _max_intent(natural_intent, "source_freshness")
    if changes.test_selectors:
        natural_intent = _max_intent(natural_intent, "test")
    if build_models:
        natural_intent = _max_intent(natural_intent, "build")
    # Over-validation is a property of the whole plan, not of one operation. A
    # freshness step in a build change set is narrower on purpose, and warning
    # about it would train a reader to ignore the warning that matters.
    over_validation = INTENT_RANK.get(intent, 0) > INTENT_RANK.get(natural_intent, 0)

    effective_intent = "static"
    for step in warehouse_steps:
        effective_intent = _max_intent(effective_intent, step.intent)

    selected = explicit or sorted(changes.models)
    model_selectors = model_display_selectors(
        changes, build_models, explicit_models=explicit
    )
    semantic_selectors = [f"{item['name']}+" for item in changes.semantic_resources]
    source_selectors = [
        f"source:{item['source']}.{item['table']}" for item in changes.source_resources
    ]
    resolve_step = next((step for step in steps if step.operation == "resolve"), None)
    resolution_selectors = (
        list(resolve_step.selectors)
        if resolve_step
        else sorted(set([*model_selectors, *semantic_selectors, *source_selectors]))
    )
    primary = max(
        warehouse_steps,
        key=lambda step: INTENT_RANK.get(step.intent, 0),
        default=None,
    )
    legacy_selectors = (
        list(primary.selectors)
        if primary
        else (model_selectors or semantic_selectors or source_selectors)
    )

    warnings: list[str] = []
    if not scope.available and scope.error:
        warnings.append(f"Git scope unavailable: {scope.error}")
    if over_validation and not allow_broader_intent:
        warnings.append(
            f"Requested intent {intent!r} exceeds the deterministic recommendation "
            f"{natural_intent!r}; the broader warehouse command was omitted. "
            "Review the recommendation or explicitly allow the broader intent."
        )
    for relative, constructs in sorted(changes.unsupported_yaml.items()):
        warnings.append(
            f"{relative} uses YAML constructs this reader cannot interpret "
            f"({', '.join(constructs)}); its change classification is unknown."
        )
    if changes.state_evidence in {"current manifest"}:
        warnings.append(
            "Downstream scope for a deleted resource came from the current manifest "
            "rather than prior production state, so it may be incomplete."
        )
    if context.discovery_note:
        warnings.append(context.discovery_note)

    commands = [step.as_dict(order) for order, step in enumerate(steps, start=1)]
    for command in commands:
        command.pop("operation", None)
        command.pop("selectors", None)
        command.pop("intent", None)
        command.pop("confidence", None)
        command.pop("reason", None)

    return {
        "ok": True,
        "plan_version": PLAN_VERSION,
        "project_root": str(context.dbt_root),
        "repository_root": str(context.git_root) if context.git_root else None,
        "scope": {
            "models": selected,
            "selectors": legacy_selectors,
            "resolution_selectors": resolution_selectors,
            "source": "explicit" if explicit else "git_diff",
            "contract_change": any(changes.build_models.get(name) for name in selected)
            or bool(changes.semantic_resources),
            "yaml_change_kinds": changes.yaml_change_kinds,
            "semantic_resources": [] if explicit else changes.semantic_resources,
            "source_resources": changes.source_resources,
            "singular_tests": [] if explicit else sorted(changes.singular_tests),
            "unresolved_dependency_changes": []
            if explicit
            else sorted(changes.unresolved_dependency_changes),
            "unsupported_yaml": changes.unsupported_yaml,
            "unresolvable_deletions": changes.unresolvable_deletions,
            "changed_paths": [change.path for change in scope.changes],
            "excluded_changes": excluded,
        },
        "target": {
            "name": target,
            "production_like": bool(target and PRODUCTION_TARGET.search(target)),
        },
        "intent": effective_intent,
        "requested_intent": intent,
        "recommended_intent": natural_intent,
        "recommendation_reason": _recommendation_reason(changes, natural_intent, explicit),
        "broader_intent_requires_override": over_validation and not allow_broader_intent,
        "validation_steps": [step.as_dict(order) for order, step in enumerate(steps, start=1)],
        "commands": commands,
        "state": inventory.as_dict(context.dbt_root),
        "blocked_reason": blocked_reason,
        "warnings": warnings,
        "execution_note": "Planning only; dbt was not executed and no warehouse was contacted.",
    }


def _max_intent(left: str, right: str) -> str:
    return left if INTENT_RANK.get(left, 0) >= INTENT_RANK.get(right, 0) else right


def _recommendation_reason(changes: ChangeSet, intent: str, explicit: Sequence[str]) -> str:
    if intent == "build":
        if explicit and not changes.build_models:
            return "The user supplied affected model scope for a dependency-wide change."
        return "Model code, contract, rename, or deletion changes require model and test validation."
    if intent == "test":
        if changes.singular_tests:
            return "Only singular tests changed, so run those tests without rebuilding models."
        return "Only test declarations changed, so rebuilding models is unnecessary."
    if intent == "source_freshness":
        return "Only source freshness or loaded-at configuration changed, so validate those sources."
    if changes.unsupported_yaml:
        return "Unsupported YAML constructs prevent a reliable classification of the change."
    if changes.semantic_resources:
        return "Semantic resources must be resolved to affected models before warehouse validation."
    if changes.unresolved_dependency_changes:
        return (
            "Macro, package, or project configuration changes need explicit affected "
            "model scope before warehouse validation."
        )
    if explicit:
        return "The user supplied both model scope and validation intent."
    return "Only comments, formatting, descriptions, or other non-executable metadata changed."


def _parser() -> argparse.ArgumentParser:
    parser = inspect_dbt.JsonArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="dbt project directory")
    parser.add_argument("--model", action="append", dest="models", help="Model to validate; repeatable")
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Restrict the change scope to this project-relative path; repeatable",
    )
    parser.add_argument("--target", help="Explicit local or development dbt target")
    parser.add_argument(
        "--state",
        dest="state_dir",
        help="Directory holding prior dbt artifacts for deletion and downstream resolution",
    )
    parser.add_argument(
        "--intent",
        choices=["static", "compile", "test", "run", "build", "source_freshness"],
        default="build",
    )
    parser.add_argument(
        "--allow-broader-intent",
        action="store_true",
        help="Keep a requested warehouse intent even when static analysis recommends less work",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = plan_validation(
            args.path,
            models=args.models,
            paths=args.paths,
            target=args.target,
            intent=args.intent,
            allow_broader_intent=args.allow_broader_intent,
            state_dir=args.state_dir,
        )
    except (ValidationPlanError, inspect_dbt.DbtInspectionError, OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
