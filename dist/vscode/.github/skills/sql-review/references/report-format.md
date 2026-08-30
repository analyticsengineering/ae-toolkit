# SQL review report format

Link to this file directly from `SKILL.md`; do not create deeper references.

## Finding

```markdown
### [SEVERITY] Short imperative title

- Location: `path:line` or `CTE > expression`
- Status: Observed | Inferred | Unknown
- Evidence: Exact query behavior, schema fact, plan signal, or reproducible case.
- Impact: Which rows, metric, consumer, reliability property, cost, or privacy boundary is affected.
- Recommendation: Smallest safe correction or named next check.
- Verification: Focused test/query and expected result.
```

For **BLOCKER** and **HIGH**, Evidence must also state:

- the triggering input or logical path;
- expected versus actual behavior;
- why the impact meets that severity.

## Severity summary

List counts in this order:

```text
BLOCKER: n
HIGH: n
MEDIUM: n
LOW: n
INFO: n
```

Do not invent empty findings merely to populate a severity.

## Verdict mapping

- `BLOCK`: at least one substantiated BLOCKER.
- `CHANGES REQUESTED`: at least one HIGH, or MEDIUM findings collectively make approval unsafe.
- `APPROVE WITH NOTES`: only non-blocking findings.
- `APPROVE`: no actionable findings in the inspected scope.

The mapping is a default. Explain any departure based on explicit repository policy or impact.
