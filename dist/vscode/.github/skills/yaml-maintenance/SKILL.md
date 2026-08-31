---
name: yaml-maintenance
description: Maintains the structure and integrity of analytics YAML without inventing model semantics. Use when splitting, merging, moving, deduplicating, ordering, formatting, or version-updating dbt YAML; when repairing duplicate resource patches, misplaced properties, stale references, or schema-file layout; or when another skill needs a safe grouped-YAML change.
---

# YAML Maintenance

Restructure analytics YAML safely while preserving resource meaning, ownership, and effective configuration.

## When to use

- Split, merge, move, deduplicate, order, format, or version-update project-owned dbt YAML.
- Repair duplicate patches, misplaced properties, stale references, invalid structure, or repository-inconsistent schema-file layout.
- Apply an already-decided source, documentation, or test change to grouped YAML without redefining that change's semantics.
- When `build-model`, `source-setup`, `model-documentation`, or `model-tests` needs grouped-YAML maintenance, perform this discovery automatically; users do not need to invoke another skill.
- Do not use to invent source metadata, model descriptions, tests, contracts, or business definitions.

## Mode and conventions

Read `.ae/exercise.json` when present and honor its mode, constraints, rubric, allowed tools, and artifacts. Otherwise use a user-requested mode; if none is requested, silently use **Work**.

- **Work:** prepare a semantics-preserving YAML change and apply only authorized writes.
- **Learn:** explain structural choices with progressive hints and preserve learner agency.
- **Assessment:** evaluate submitted YAML read-only without correcting or editing it.

Read `.ae/project.yml` first and treat human edits as authoritative. If absent, run `python3 ".github/ae-toolkit/scripts/infer_conventions.py" <project-root> --json` and inspect representative YAML plus `dbt_project.yml`. Infer schema-file strategy, filename pattern, resource grouping, property order, indentation, quoting, version key, and test syntax from local evidence. Apply strong conventions silently, state weak assumptions, ask about genuine splits, and label defensible defaults where evidence is absent.

## Procedure

1. Inventory project-owned YAML files and map each source, model, seed, snapshot, analysis, metric, exposure, group, and semantic resource to its patch location.
2. Parse the target files before proposing changes. Distinguish syntax errors, duplicate keys, duplicate resource patches, stale references, and convention drift.
3. Establish the intended effective configuration before and after the change. Structural maintenance must not alter descriptions, tests, contracts, quoting, freshness, access, meta, tags, or configuration unless another triggered domain has supplied that semantic change.
4. Trace YAML anchors, aliases, docs references, package macros, selectors, and cross-file dependencies that a move or split could affect.
5. Choose the repository's established grouped, domain, directory, or model-level layout. Do not reorganize valid YAML solely to impose a preferred style.
6. Preserve comments where the parser and edit method allow it. Report comments or formatting that cannot be preserved exactly.
7. Apply explicitly requested, semantics-preserving edits to project-owned YAML without asking for a second approval. Preview the exact before/after structure and ask before moving, replacing, or deleting files, changing effective values, or expanding beyond the requested resources.
8. Make the smallest authorized structural change and reparse every affected YAML file.
9. When composing with another skill, consume its decided semantic payload and return paths, structural diff, preserved invariants, and approval status; do not redo its domain analysis.

## Evidence required

Cite every duplicate, stale reference, invalid key, and layout convention by file and resource. For moves or splits, enumerate the resources leaving and entering each file. Compare normalized effective content before and after and identify any value that changes.

## Failure modes

- Reformatting or reorganizing valid YAML without a repository-backed reason.
- Silently changing semantic values during a structural move.
- Dropping comments, anchors, aliases, tests, descriptions, meta, or config.
- Merging duplicate resource patches without checking for conflicting properties.
- Assuming a parser preserves ordering, quoting, or comments.
- Treating source, documentation, or test design as YAML maintenance.
- Moving, deleting, changing semantics, or expanding scope before diff preview and approval.
- Running dbt to discover errors that local parsing can identify.

## Output contract

For ordinary structural work, return `# YAML Maintenance` with: Changed; Why; Verified; Remaining uncertainty. Name preserved semantic invariants and any formatting or comments that could not be retained. Use formal severity and evidence findings only when auditing YAML quality or reporting a material risk.

## Verification

- Parse every affected YAML file and reject duplicate mapping keys.
- Confirm every resource has one intended patch location after the proposal.
- Compare normalized pre/post resources and list all semantic value changes; for structural-only work, there must be none.
- Resolve local model, source, docs, macro, exposure, selector, and test references statically.
- Confirm file placement and property syntax match the detected dbt version and repository examples.
- Propose the smallest parse command without running dbt.

## Safety/privacy

- Local Basic only: use repository files and static local tools; never call MCP, execute dbt, or contact a warehouse.
- Do not expose credentials, connection strings, profile targets, PII, or raw row values found in YAML.
- New files may be created and must be listed.
- Explicitly requested semantics-preserving YAML edits may proceed; moves, replacements, deletions, semantic changes, and scope expansion require preview, blast radius, and approval.
- Never perform destructive version-control or database operations.
