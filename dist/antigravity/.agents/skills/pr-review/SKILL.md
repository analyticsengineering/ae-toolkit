---
name: pr-review
description: Reviews analytics-engineering pull requests from read-only diffs for correctness, data-model, quality, privacy, performance, and deployment risk. Use when the user asks for a PR, branch, commit, or local-change review.
---

# PR Review

Review the change, not the author's intent. Use read-only Git inspection and provide findings only when supported by the diff and relevant context.

## When to use

- Review a pull request, branch diff, commit range, staged changes, or working-tree changes.
- Focus on analytics risks in SQL, dbt, orchestration, ingestion, metrics, tests, and configuration.
- Do not modify code, post comments, approve, merge, or push unless separately requested.

## Required context

Obtain:

- Review target and base/ref, PR description or intended behavior, and repository conventions.
- Changed files plus relevant surrounding definitions, tests, lineage, and deployment context.
- Critical models/metrics, warehouse/dialect, and known rollout constraints.

Default silently to Work mode and deliver merge-focused findings. In Learn mode, explain why each issue matters and how to review it. In Assessment mode, evaluate only the learner's submitted review without revealing missed-answer details that server policy withholds.

## Inspection procedure

1. Confirm review scope and base. Use only read-only commands such as `git status`, `git diff`, `git diff --stat`, `git log`, and `git show`; never stage, reset, checkout, commit, push, or alter Git state.
2. Read the complete diff, including deletions, renames, configuration, tests, and generated-artifact implications.
3. Inspect only the surrounding code and lineage needed to evaluate changed behavior.
4. Reconstruct intended before/after behavior and identify changed grains, keys, filters, joins, metrics, history, state, and side effects.
5. Evaluate analytics risks:
   - semantic correctness and metric definitions;
   - grain, fanout, deduplication, nulls, and temporal boundaries;
   - incremental state, idempotency, late data, backfills, and deletes;
   - schema contracts, compatibility, and downstream blast radius;
   - tests, observability, ownership, and rollback;
   - warehouse cost/performance and deployment ordering;
   - secrets, PII, access, retention, and unsafe logging.
6. Check tests for behavior coverage, not merely presence. Identify missing tests only when tied to a concrete risk.
7. Avoid comments on unchanged pre-existing issues unless the change makes them newly reachable or materially worse.
8. Consolidate findings, rank by merge risk, and verify each against the diff.

Fetching remotes, reading a hosted PR, running CI/tests, accessing warehouses, posting comments, or any other connected functionality requires an explicit user trigger. Any external write or potentially costly execution requires approval.

## Decision framework

Use:

- **BLOCKER** — merging would likely cause destructive behavior, data corruption, security/privacy exposure, or materially wrong critical outputs.
- **HIGH** — probable material correctness, reliability, schema, or deployment failure.
- **MEDIUM** — bounded defect or meaningful maintainability/performance risk.
- **LOW** — minor robustness or clarity issue.
- **INFO** — non-defect question or optional improvement.

Only report actionable issues introduced or exposed by the change. BLOCKER/HIGH require a concrete code path, triggering conditions, expected versus actual behavior, and impact. If evidence is incomplete, ask a question or lower severity.

## Failure modes

- Reviewing only filenames or PR description instead of the diff.
- Mutating Git state to inspect changes.
- Flagging style preferences as defects.
- Assuming tests pass, sources are unique, or downstream schemas tolerate change.
- Missing SQL fanout, incremental-boundary, backfill, or metric-denominator changes.
- Posting review comments or approvals without user authorization.

## Evidence required

Each finding includes severity, changed file and line/snippet, triggering scenario, evidence from changed behavior, impact, and smallest safe remediation. Cite relevant unchanged context only to establish the path. Distinguish observed defects, inferred risks, and unresolved questions.

## Output contract

Return a concise scope and verdict, followed by severity-ordered review comments. Every comment must include file, line/section where possible, severity, evidence, impact, recommended fix, and verification. Include a clean-review statement when there are no actionable findings.

Keep summaries brief; findings are the primary deliverable.

## Verification

- Re-open each cited diff hunk and trace the triggering path.
- Confirm the issue is introduced or materially exposed by the reviewed change.
- Ensure BLOCKER/HIGH evidence meets the stated threshold.
- Check whether existing tests already cover the scenario.
- Remove duplicates and non-actionable preferences.
- State what was not run or accessed.

## Safety/privacy

- Keep Git inspection read-only.
- Do not expose secrets found in diffs; identify location and redact value.
- Do not run production queries, pipelines, broad test suites, or network calls without explicit instruction and approval where needed.
- Never post, approve, merge, close, or otherwise mutate a hosted PR unless the user explicitly requests it.

## What not to assume

Do not assume the base branch, PR description, tests, schemas, lineage, source uniqueness, backward compatibility, default target, CI result, rollout safety, or author intent. Verify or state the uncertainty.
