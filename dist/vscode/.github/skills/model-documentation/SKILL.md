---
name: model-documentation
description: Authors and reviews business-facing documentation for analytical models and columns. Use when adding or improving model or column descriptions, documenting grain, keys, measures, dimensions, null semantics, lineage, or docs blocks; when resolving stale or copied descriptions; or when build-model needs documentation for a model.
---

# Model Documentation

Document what a model means and how it may be used, without restating its SQL or inventing business semantics.

## When to use

- Add or review model descriptions, column descriptions, and reusable docs blocks.
- Document grain, keys, measures, dimensions, time anchors, null meaning, and safe aggregation behavior.
- Repair stale, copied, contradictory, or implementation-only model documentation.
- When `build-model` reaches its documentation step, perform this discovery automatically; users do not need to invoke another skill.
- Do not use for source declarations, test design, or YAML-only restructuring unless those domains are independently triggered.

## Mode and conventions

Read `.ae/exercise.json` when present and honor its mode, constraints, rubric, allowed tools, and artifacts. Otherwise use a user-requested mode; if none is requested, silently use **Work**.

- **Work:** author evidence-backed documentation and authorized changes.
- **Learn:** teach with a hint ladder and leave the learner's wording to them.
- **Assessment:** grade submitted documentation against stated criteria without rewriting or editing it.

Read `.ae/project.yml` first and treat human edits as authoritative. If absent, run `python3 ".github/ae-toolkit/scripts/infer_conventions.py" <project-root> --json`, then inspect representative model SQL, YAML, and docs blocks. Infer YAML strategy, file naming, prose style, and documentation depth from the repository. Apply strong conventions silently, state weak assumptions, ask about real splits, and label defaults where evidence is absent.

## Procedure

1. Establish the model's grain, purpose, key, upstream inputs, downstream consumers, and selected columns from local artifacts.
2. Trace each documented field to SQL, contracts, tests, requirements, or existing authoritative prose. A name alone is not a definition.
3. Write the model description in business terms: one row per what, why the model exists, and material scope or exclusions.
4. Describe keys by role and measures by unit, time anchor, aggregation behavior, filters, and known non-additivity. Explain meaningful nulls.
5. Describe transformations only when they change interpretation. Do not narrate CTEs, casts, aliases, or obvious implementation.
6. Reconcile contradictions explicitly. Never silently choose among different business definitions for the same metric.
7. Place documentation according to the repository's model-level, grouped-YAML, or docs-block pattern.
8. Apply explicitly requested, reversible documentation edits to project-owned YAML or Markdown without asking for a second approval. Preview and ask before deleting or moving files, changing business meaning, or expanding beyond the requested models.
9. If composing with `build-model`, return the documentation, evidence, target path, and any unresolved semantic gate; do not redo source setup, SQL construction, or model-test design.

## Evidence required

Cite the SQL expression or authoritative local requirement behind every material semantic claim. Cite tests or contracts supporting keys and accepted values, plus downstream artifacts supporting usage claims. Separate observed meaning from hypotheses and identify undocumented columns rather than guessing.

## Failure modes

- Restating SQL, aliases, or column names instead of explaining business meaning.
- Claiming uniqueness, freshness, additivity, or completeness without evidence.
- Hiding grain, time anchors, exclusions, or null semantics that change interpretation.
- Copying descriptions between models whose grain or filters differ.
- Resolving contradictory metric definitions without stakeholder evidence.
- Treating YAML formatting as documentation work when semantics are unchanged.
- Changing shared business meaning or documentation outside the requested models without preview and approval.

## Output contract

For ordinary creation or editing, return `# Model Documentation` with: Changed; Why; Verified; Remaining uncertainty. Name the model grain and any semantic claim that could not be established. Use formal severity and evidence findings only when reviewing documentation quality or reporting a material risk.

## Verification

- Confirm every documented model and column exists locally.
- Compare descriptions against SQL filters, joins, aggregations, and time logic.
- Confirm grain and key language agrees with contracts and tests without overstating them.
- Search project-owned documentation for conflicting definitions of named metrics or fields.
- Parse affected YAML or validate docs-block references with local static tools.
- Propose the smallest documentation-generation or parse command without running dbt.

## Safety/privacy

- Local Basic only: use repository files and static local tools; never call MCP, execute dbt, or contact a warehouse.
- Do not place credentials, connection strings, PII, raw row values, or unreleased sensitive metrics in documentation.
- New files may be created and must be listed.
- Explicitly requested reversible documentation edits may proceed; deletions, moves, semantic changes, and scope expansion require preview, blast radius, and approval.
- In Assessment mode, make no repository changes.
