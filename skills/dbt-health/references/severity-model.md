# Review Severity Model

Use the highest severity justified by demonstrated impact. Do not inflate severity from style preference alone.

## Levels

- **Blocker** — Likely data loss, unauthorized disclosure, destructive production action, materially wrong published data, or an unusable critical pipeline. Must be resolved before release.
- **High** — Probable correctness, security, reliability, or cost failure with broad or important impact. Resolve before release unless an owner explicitly accepts the risk.
- **Medium** — Real but bounded issue affecting maintainability, observability, performance, or edge-case correctness. Plan a fix and verify it.
- **Low** — Small improvement with limited impact. Fix opportunistically.
- **Note** — Context, praise, question, or non-actionable observation. Not a defect.

## Required finding shape

Every actionable finding contains:

1. **Evidence** — Exact file, query, model, field, metric, or observed behavior. Separate fact from inference.
2. **Risk** — Who or what can be affected, how, and under which conditions.
3. **Recommendation** — Smallest practical change that addresses the cause.
4. **Verification** — Specific test, query, comparison, or acceptance criterion proving the change.

Include severity and confidence (`high`, `medium`, or `low`). State missing evidence rather than guessing. Combine duplicate findings and order results by severity, then confidence.

## Clean reviews

If no actionable findings are supported, say so. Still list verification performed, evidence gaps, and residual risks.
