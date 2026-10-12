---
name: metric-definition
description: Defines canonical business metric contracts with explicit population, grain, formula, dimensions, time semantics, ownership, and acceptance cases. Use when a KPI needs an authoritative definition, competing definitions must be reconciled, or a metric contract must be specified before implementation.
---

# Metric Definition

Specify the canonical business contract for one metric. Define meaning and governance; do not implement a semantic layer, BI model, or warehouse query.

## When to use

- Establish or review an authoritative KPI definition.
- Reconcile multiple calculations that use the same business name.
- Convert approved analytics requirements into a versioned metric contract.
- Do not use when the request is only to trace an existing number or implement vendor artifacts.

## Mode and context

Default silently to **Work** mode. Use **Learn** only when teaching is requested and **Assessment** only when evaluation without answers is requested or `.ae/exercise.json` requires it.

Obtain or mark unresolved:

- Business decision, consumers, owner, steward, and approval authority.
- Metric name, business event, entity, output grain, population, formula, and unit.
- Dimensions, valid slices, status rules, identity, deduplication, and null behavior.
- Event time, reporting time zone, period boundaries, late data, corrections, and restatement policy.
- Existing definitions, source contracts, service expectations, privacy limits, and effective date.

## Local inspection procedure

1. Read `.ae/exercise.json` and `.ae/project.yml` when present.
2. Inspect local metric registries, glossaries, requirements, models, tests, exposures, semantic artifacts, BI files, and documentation before asking questions.
3. Infer naming, YAML layout, ownership, versioning, adapter, transformation tool, and BI/vendor conventions from repository evidence. Apply strong conventions; label weak or absent evidence; ask one decisive question for split conventions.
4. Locate every definition of the metric name and equivalent expressions. Treat disagreement as evidence, not as permission to choose silently.
5. Trace each candidate's population, formula, grain, filters, joins, time anchor, dimensions, unit, and correction behavior.
6. Separate business decisions from implementation details. Repository code can prove current behavior but cannot approve business meaning.
7. Specify the canonical contract, examples, counterexamples, invariants, acceptance cases, owner, effective date, and version/deprecation policy.
8. Mark the contract `READY`, `READY WITH APPROVED ASSUMPTIONS`, or `NOT READY`. A material ambiguity in population, grain, formula, or time semantics blocks readiness.

## Canonical contract

Define:

- **Identity:** canonical name, plain-language meaning, owner, aliases, version, and effective date.
- **Calculation:** numerator, denominator, aggregation, unit/currency, precision, and zero-denominator behavior.
- **Population:** included and excluded entities/events, statuses, identity, deduplication, and null/unknown handling.
- **Grain and dimensions:** evaluation grain, permitted slices, non-additive dimensions, and join constraints.
- **Time:** event timestamp, time zone, window boundaries, comparison logic, late-data cutoff, corrections, and restatement.
- **Quality and service:** source assumptions, completeness conditions, readiness expectation, tolerances, and acceptance cases.

## Evidence required

For every material choice, cite a local file, stakeholder-provided statement, policy, canonical contract, or explicit approved assumption. For competing definitions, show the exact difference and affected consumers. Never present a name, label, comment, or inferred source grain as proof of business meaning.

Use formal **Evidence**, **Risk**, **Recommendation**, and **Verification** findings with severity and confidence when reviewing competing definitions or reporting material semantic risk. For straightforward contract authoring, report Changed, Why, Verified, and Remaining uncertainty.

## Failure modes

- Calling a currently implemented expression canonical without business authority.
- Defining a rate without population, numerator, denominator, or zero-denominator behavior.
- Omitting grain, time zone, late-data, correction, unit, or restatement semantics.
- Hiding filters in semantic or BI implementation instead of the contract.
- Creating separate definitions per dashboard instead of documenting intentional variants.
- Inventing ownership, approval, service expectations, or source reliability.

## Output contract

For straightforward contract authoring, return `# Metric Definition` with: Changed; Why, including formula, population, grain, and time semantics; Verified; Remaining uncertainty. For competing-definition reviews or migration decisions, add consumer impact, source evidence, versioning, approval state, and open decisions.

State blocking decisions near the top. Include only open decisions that can change the metric; say none when repository and supplied evidence settle them.

## Verification

- Walk one normal case and at least one boundary or counterexample.
- Confirm two competent implementers would produce the same population, value, and period.
- Trace every acceptance case to a contract clause.
- Search local model, semantic, and BI artifacts for conflicting definitions and list the searched scope.
- Confirm owner approval is observed evidence before calling the definition canonical.

## Safety and repository writes

- Local Basic only: use local files and user-provided material. Never call MCP, access a warehouse, or execute dbt.
- Minimize sensitive fields and never expose credentials, raw personal data, or unreleased metric values.
- Explicitly requested reversible contract-document edits may proceed without a second approval. Changing an already canonical definition, deleting files, or expanding scope requires a preview, downstream blast radius, and approval.
- Do not silently change consumers when a canonical definition changes; report migration and comparability risk.
