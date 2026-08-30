---
name: dbt-health
description: Assesses dbt project health from artifacts, configuration, lineage, tests, documentation, and run evidence. Use when auditing a dbt project, diagnosing project hygiene, or prioritizing dbt reliability improvements.
---

# dbt Health

Use a manifest-first, evidence-based audit. Never blindly run `dbt`.

## When to use

- Audit dbt project reliability, maintainability, lineage, tests, contracts, documentation, or deployment readiness.
- Diagnose health from existing artifacts and prior command results.
- Do not use this skill to assume warehouse correctness from dbt configuration alone.

## Required context

Obtain:

- Audit scope, business-critical models/exposures, dbt version, adapter, and environments.
- Available artifacts: `manifest.json` first, then `run_results.json`, `catalog.json`, `sources.json`, `semantic_manifest.json`, logs, or CI evidence.
- Project configuration and package/mesh boundaries where relevant.
- Operating mode: **Work**, **Learn**, or **Assessment**.

In Work mode, prioritize remediations by reliability impact. In Learn mode, explain artifact fields and dbt concepts. In Assessment mode, evaluate the submitted diagnosis without revealing the answer or repairing the project.

## Inspection procedure

1. Define health dimensions and create a current, exact file-existence inventory for `manifest.json`, `run_results.json`, `catalog.json`, `sources.json`, and `semantic_manifest.json` inside the project. A prior message, terminal transcript, cached summary, or remembered run is not an artifact.
2. Inspect `manifest.json` before reading models broadly only when that exact file is present in the current inventory and was opened during this workflow. Treat stale or mismatched artifacts as limited evidence. If an inspector reports an artifact as absent, report it absent; never reconstruct artifact metadata, invocation results, or test status from memory or static files.
3. From the manifest, inventory enabled resources, dependencies, materializations, tests, sources, exposures, groups/access, contracts, versions, docs, and configuration inheritance.
4. Identify critical lineage, high-fanout nodes, untested sources, disabled/orphaned resources, naming/config drift, and blast-radius concentrations.
5. Correlate `run_results.json` with manifest unique IDs for failures, skips, timing, flaky behavior, and partial-selection effects.
6. Use catalog/source freshness/semantic artifacts when present; do not infer database state from absence.
7. Inspect source files and singular tests to resolve artifact findings, distinguish intentional independent raw-source assertions from model-layer violations, and compare documented population, privacy/retention policy, metric caveats, and suppression claims with the predicates actually implemented.
8. Check whether models reading mutable or concurrently updated sources share a reproducible extraction/run boundary; comments describing a downstream release process are intent, not proof that the boundary exists.
9. Propose the smallest targeted commands needed to fill gaps. Show exact selectors, target, and purpose.

Never run `dbt build`, `dbt run`, `dbt test`, `dbt compile`, `dbt parse`, `dbt deps`, or warehouse-backed commands merely because they are available. Execution and connected warehouse functionality require an explicit user trigger; confirm target and obtain approval when cost, mutation, dependency installation, or production access is possible.

## Decision framework

Rate each dimension `Healthy`, `Needs attention`, `High risk`, or `Unknown`:

- Build/test reliability.
- Source freshness and data contracts.
- Lineage and ownership.
- Test coverage by risk, not raw test count.
- Documentation and discoverability.
- Configuration/materialization consistency.
- Deployment reproducibility and artifact integrity.
- Performance/cost signals.

Prioritize production impact, lineage blast radius, recurrence, detectability, and ease of recovery. Missing evidence remains `Unknown`, not `Healthy`.

## Failure modes

- Running all dbt resources without knowing target, selector, cost, or side effects.
- Starting with raw SQL files while ignoring the manifest.
- Comparing raw test counts across differently critical models.
- Treating a successful run as proof of data correctness.
- Reading stale artifacts as current warehouse truth.
- Recommending package upgrades without compatibility evidence.

## Evidence required

Every finding cites artifact/file, unique ID or resource, artifact metadata/recency, observed field or result, risk, and remediation. For coverage claims, define denominator and exclusions. For runtime claims, provide invocation/result timing and comparison basis. Label artifact absence separately from unhealthy behavior.

## Output contract

Return `# dbt Project Health` with: Health summary; Architecture; Testing; Documentation; Incremental/Snapshot risk; Dependency risks; Potential anti-patterns; Top 5 improvements.

Give each finding one primary location and avoid repeating it across the scorecard, risks, anti-patterns, and top five. Prioritize concrete metric/grain defects, reproducibility boundaries, and freshness/coverage gaps ahead of naming or generic hygiene. Cite only inspected project/artifact evidence; label comments and external-system descriptions as unverified intent.

## Verification

- Validate artifact schemas and metadata against the project/dbt version.
- Before citing any artifact field or runtime result, re-confirm that the exact artifact exists in the current inventory and that the cited value was read from it in this workflow.
- Cross-reference unique IDs across artifacts.
- Confirm selectors and targets before proposing or running commands.
- Separate parse/compile evidence from warehouse execution evidence.
- Reassess ratings after targeted evidence; never hide unresolved unknowns.

## Safety/privacy

- Prefer local artifacts and metadata over warehouse queries.
- Never print profile credentials, environment secrets, compiled sensitive SQL, or sampled protected data.
- Do not install dependencies, contact dbt services, or access a warehouse without explicit user instruction.
- Warn about production targets, full refreshes, hooks, snapshots, seeds, grants, and costly scans.

## What not to assume

Do not assume artifacts are current, the default target is safe, tests are comprehensive, disabled resources are obsolete, successful builds are semantically correct, source freshness is configured, contracts are enforced, or a command is read-only because its name sounds diagnostic.
