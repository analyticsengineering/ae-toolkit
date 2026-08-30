---
name: explain-data-code
description: Explains SQL, Python, dbt, and analytics code at beginner, analyst, or analytics-engineer depth with traced data behavior and verified semantics. Use when a user asks what data code does, why it works, or how to learn from it.
---

# Explain Data Code

Explain what the code does to data, why, and under which assumptions. Do not confuse a plausible reading with verified behavior.

## When to use

- Explain a query, model, notebook, pipeline transformation, macro, test, or code diff.
- Teach syntax and analytics concepts or document unfamiliar data code.
- Diagnose meaning, but use an incident/review skill when the primary request is defect triage.

## Required context

Obtain:

- Complete relevant code, language/dialect/framework, and directly referenced definitions.
- Intended input/output, known schema, and business purpose.
- Requested explanation level: **beginner**, **analyst**, or **analytics-engineer**.
- Operating mode: **Work**, **Learn**, or **Assessment**.

If level is unstated, infer from the user's vocabulary and say which level was used. In Work mode, optimize for concise operational understanding. In Learn mode, teach progressively and invite a check for understanding. In Assessment mode, ask the learner to explain first and evaluate only their submitted reasoning; do not provide an answer or answer-equivalent walkthrough.

## Inspection procedure

1. Establish the code boundary, dialect/runtime, entry point, and declared purpose.
2. Inspect definitions needed to resolve macros, helper functions, models, configuration, and schemas.
3. Trace inputs through transformations to outputs in execution order, noting grain and schema changes.
4. Explain filters, joins, aggregations, windows, state, side effects, error paths, and temporal behavior. For predicates, concatenation, arithmetic, and conditional aggregates, trace how a null in each nullable input affects row eligibility, numerator membership, denominator membership, and the final value.
5. Separate syntax mechanics, data semantics, business assumptions, and operational behavior.
6. Choose depth:
   - **Beginner:** define terms, use a tiny example, explain one transformation at a time, minimize jargon.
   - **Analyst:** emphasize grain, joins, metrics, nulls, filters, and how results should be interpreted.
   - **Analytics-engineer:** include compilation/runtime, lineage, materialization, incremental behavior, contracts, testing, performance, and maintainability.
7. Identify ambiguities or risks without turning the response into an unsolicited rewrite.
8. Verify claims from code or safe evidence. Suggest execution only when static inspection cannot answer.

Connected repositories, warehouses, notebooks, or execution require an explicit user trigger. Any stateful, costly, or data-revealing action requires approval.

## Decision framework

For each point, label mentally or explicitly:

- **Certain from code** — directly follows from visible semantics.
- **Context-dependent** — depends on schema, dialect, configuration, or data.
- **Business assumption** — requires domain confirmation.
- **Runtime unknown** — needs execution, logs, or query-plan evidence.

Prioritize the user's goal and level. Explain conceptual invariants before incidental syntax.

## Failure modes

- Paraphrasing every line without explaining data flow.
- Inventing source schemas, business meanings, or macro behavior.
- Saying a join is safe without cardinality evidence.
- Overwhelming beginners or under-explaining operational behavior to engineers.
- Running code solely to make the explanation feel authoritative.
- Presenting a bug hypothesis as what the code necessarily does.

## Evidence required

Anchor claims to a function, CTE, expression, config, or traced path. Include a compact worked example when it materially clarifies grain, nulls, windows, or aggregation. State what evidence would resolve context-dependent claims. Never fabricate output rows.

## Output contract

Return:

1. **One-sentence purpose**.
2. **Inputs and output** — including grain when relevant.
3. **Step-by-step data flow** at the chosen level.
4. **Key concepts** appropriate to beginner, analyst, or analytics-engineer depth.
5. **Assumptions and edge cases**.
6. **Operational notes** when relevant.
7. **Verification questions/tests** if behavior is unresolved.

In Learn mode, end with one short comprehension check or next concept. In Assessment mode, provide evaluation criteria and targeted feedback rather than silently completing the exercise.

For Analyst and Analytics Engineer levels, default to the 3–5 highest-impact risks and verification checks. Keep direct code semantics separate from repository facts: cite the exact config/artifact for adapter, variable, materialization, or runtime claims, otherwise label them unknown. Avoid peripheral repository details and do not repeat the same caveat in flow, risks, and runtime-unknown sections.

## Verification

- Re-trace the explanation against the code in execution order.
- Check every expression used to classify or match rows for null propagation that can exclude a row from a numerator while retaining it in the denominator.
- Confirm dialect/framework-specific claims.
- Check that stated grain changes match joins and aggregations.
- Distinguish static facts from runtime/data-dependent behavior.
- Ensure terminology and detail match the selected level.

## Safety/privacy

- Do not execute code, query data, or open connected systems without explicit instruction.
- Redact credentials, secrets, personal data, and proprietary values from examples.
- Use synthetic examples when row values are unnecessary.
- Warn when code appears to mutate, export, or broaden access to data.

## What not to assume

Do not assume names equal semantics, comments are current, inputs satisfy constraints, joins are one-to-one, ordering is deterministic, macros are standard, the environment is production-safe, or the user already understands unexplained jargon.
