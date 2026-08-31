---
name: data-profile
description: Profiles tabular datasets with compute-first evidence about schema, distributions, nulls, uniqueness, and anomalies. Use when the user asks to inspect, summarize, validate, or understand a dataset or extract.
---

# Data Profile

Profile from computed results, not visual guesses. The canonical profiler is `scripts/profile_dataset.py` relative to the analytics-engineering toolkit root.

## When to use

- Profile CSV, JSON, or JSONL. Parquet is planned, not supported in V1.
- Establish dataset shape, field behavior, candidate keys, quality risks, and next checks.
- Use before modeling when source behavior is unknown.

## Required context

Obtain:

- Local dataset path.
- File format, delimiter/encoding when relevant, and expected grain if known.
- Business purpose, sensitive-field constraints, and whether full-file computation is acceptable.

Default silently to Work mode and optimize for decisions and reusable evidence. In Learn mode, explain each statistic and its limits. In Assessment mode, evaluate the learner's submitted interpretation without constructing the answer.

## Inspection procedure

1. Confirm the input and privacy/cost boundary. This skill is local-only and never calls MCP.
2. Locate `scripts/profile_dataset.py` from the toolkit root. Inspect its `--help` or source only as needed to determine supported arguments; do not alter it.
3. **Compute first:** invoke `scripts/profile_dataset.py` on the approved dataset before drawing conclusions. Prefer the narrowest supported bounded invocation that still answers the request.
4. If the script is missing, incompatible, or fails, report the exact blocker and command/error evidence. Do not silently replace it with ad hoc profiling. Offer a fallback and wait for approval.
5. For JSON, verify the record-bearing array or object path before interpreting row count. Never treat an API envelope as the analytical record grain merely because it parsed successfully. When the profiler reports more than one plausible record array, choose with `--record-path` and say which one you chose and why, rather than accepting whichever it found first.
6. Capture reproducibility details: input identity, size or row count, invocation, sampling/limits, parser settings, and profiler version or file revision when available. Report `header_normalizations` when present: a duplicate or blank column heading was renamed to profile the file at all, and the reader's column list will not match the file's.
7. Interpret shape and schema; null counts/rates; distinct counts; candidate uniqueness; numeric and temporal ranges; categorical variants; duplicate rows; constants; outliers; PII warnings; and parse/type anomalies. Read `null_count`, `sentinel_null_count`, and `missing_count` as three different facts: an empty cell, a value such as `N/A` or `unknown` standing in for one, and the two together. A column that is complete on the first measure and half sentinel on the second is a data-quality finding, not a clean column.
8. On a column the profiler marked `potential_pii`, extrema, ranges, and outlier bounds are withheld deliberately. Do not reconstruct them from the raw file to fill the section. Report the distributional facts that do not identify anyone, and say the range was suppressed.
9. Compare related fields and declared expectations. Treat candidate keys, outliers, semantic types, and value-pattern PII warnings as hypotheses until field semantics support them.
10. Prioritize material anomalies and propose targeted next tests.

## Decision framework

Classify each observation:

- **Confirmed property** — directly computed over the declared scope.
- **Quality risk** — computed pattern conflicts with a stated requirement or likely use.
- **Hypothesis** — plausible semantic interpretation needing domain validation.
- **Coverage gap** — profiler or input scope cannot answer it.

Prioritize by business impact, prevalence, downstream propagation, and reversibility. A rare value is not automatically bad; a unique column is not automatically a key.

## Failure modes

- Describing a dataset before running the canonical profiler.
- Treating a sample statistic as a full-dataset fact.
- Inferring semantic meaning from names or types alone.
- Reporting outliers without units, domain bounds, or population context.
- Loading an unbounded remote table or leaking raw sensitive values.
- Quietly switching tools when the canonical script fails.

## Evidence required

Every quantitative claim includes:

- Metric, numerator/denominator where applicable, and evaluated scope.
- Script invocation and whether results are full-file, sampled, or limited.
- Column(s), observed value/range/pattern, and relevant expectation.
- For an anomaly, at least one reproducible statistic; include example values only when privacy-safe.

Label computed facts, domain assumptions, and proposed tests separately.

## Output contract

Return `# Dataset Profile` with: Dataset shape; Potential grain; Potential keys; Quality findings; Null patterns; Duplicate findings; Type issues; Suspicious values; Potential PII warning; Recommended next checks; Cleaning recommendations. Do not dump raw sensitive values.

Keep reproducibility metadata to one compact scope line unless the user requests an audit trail; omit hashes, byte counts, and scanner implementation details when they do not change a decision. Put each recommendation in one section rather than repeating it under findings, next checks, and cleaning. Default to the five highest-value checks or cleaning actions per dataset.

## Verification

- Confirm the script exited successfully and the output corresponds to the intended input.
- Reconcile counts and percentages; denominators must be explicit. Separate figures the profiler computed from figures you derived by hand, and recheck each derived figure against the profiler output or the file before it appears in the report.
- Check sampling, parser warnings, truncation, and unsupported types.
- Re-run only focused, approved checks for surprising results.
- Ensure no claim exceeds the computed scope.

## Safety/privacy

- Do not print secrets, tokens, direct identifiers, or unrestricted row samples.
- Prefer aggregates, masked examples, and minimum necessary columns.
- Do not upload data or connect to a service without explicit user instruction.
- Warn before operations likely to scan large files or incur warehouse cost.

## What not to assume

Do not assume inferred types are correct, blanks equal nulls, uniqueness implies a key, correlation implies causation, timestamps share a zone, missingness is random, a sample represents the population, or an unusual value is invalid.
