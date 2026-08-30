---
name: ae-profile-data
description: Profile a dataset's shape, completeness, uniqueness, distributions, freshness, and quality risks.
---

# Profile Analytical Data

Apply the `data-profile` skill workflow and the `data-quality-investigator` agent perspective.

## Execution boundary

This is a free local workflow for CSV, JSON, and JSONL. Never require or call MCP. Parquet is not supported in V1.

## Workflow

1. Confirm the dataset, intended grain, key fields, sensitive columns, expected time window, and profiling objective. Read `.ae/exercise.json` if present.
2. If `python3` is available, run `python3 "${CURSOR_PLUGIN_ROOT}/scripts/profile_dataset.py" <selected-file>` and interpret its JSON. Do not mutate the dataset. If Python is unavailable, say deterministic statistics could not be computed; do not guess them.
3. Inspect row and column counts, inferred types, null counts/rates, uniqueness, cardinality, duplicate rows, possible keys, ranges, date coverage, categorical variants, outliers, constants, and potential PII warnings.
4. Compare results with stated contracts or expectations; distinguish observed anomalies from business-valid exceptions.
5. Minimize retained output and redact sensitive values. Prefer statistics to raw samples.
6. In Learn mode, ask the learner to interpret key anomalies. In Assessment mode, assess their profiling work without supplying the missing analysis.

## Output

Return `# Dataset Profile` with: Dataset shape; Potential grain; Potential keys; Quality findings; Null patterns; Duplicate findings; Type issues; Suspicious values; Potential PII warning; Recommended next checks; Cleaning recommendations.
