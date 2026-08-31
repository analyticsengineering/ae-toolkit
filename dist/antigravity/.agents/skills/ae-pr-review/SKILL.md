---
name: ae-pr-review
description: Review an analytics-engineering pull request for correctness, impact, safety, and adequate verification.
---
This is the `ae-pr-review` alias of the `pr-review` skill. Follow that skill's full procedure and output contract; the summary below orients the request and does not replace it.

# Review an Analytics Engineering Pull Request

Apply the `pr-review` skill workflow and the `senior-ae-reviewer` agent perspective.

## Execution boundary

- **Local Basic (default/free):** Review the local branch, diff, tests, and artifacts only. Never require or call MCP or fetch remote PR data.
- **Connected Advanced:** Only after the user explicitly requests a remote or warehouse-backed review. Authenticate, preview the destination and redacted content or queries, obtain approval, then use read-only access.

## Workflow

1. Confirm base and head scope, then use `python3 ".agents/ae-toolkit/scripts/inspect_git.py" <repository>` or equivalent read-only `git status`, `git diff`, and `git log`. Inspect all included analytics changes—not only the latest commit. Read `.ae/exercise.json` if present.
2. Trace changes through sources, SQL, models, macros, seeds, snapshots, tests, docs, metrics, contracts, and downstream consumers.
3. Check grain, joins, incremental behavior, backfills, schema compatibility, privacy, correctness, reliability, warehouse cost, and rollback or reconciliation.
4. Evaluate whether tests and evidence verify the changed behavior and edge cases.
5. Report only actionable findings with exact local evidence, Risk, Recommendation, Verification, severity, and confidence. Avoid style-only blockers.
6. In Assessment mode, review without supplying corrected code or editing. In Learn mode, explain the principle behind each finding.
7. End with release readiness, checks performed, evidence gaps, and residual risk.

## Output

For each review comment include file, line/section where possible, severity, evidence, impact, recommended fix, and verification. Prioritize grain/cardinality/metric/model-contract changes, downstream breaks, removed or missing tests, incremental/source changes, and production risk. Do not flood the review with superficial style comments.
