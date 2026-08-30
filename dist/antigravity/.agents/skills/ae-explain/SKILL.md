---
name: ae-explain
description: Explain analytical SQL, dbt, data models, or pipeline logic at the user's requested depth.
---
# Explain Analytics Engineering Code

Apply the `explain-data-code` skill workflow and, for exercises, the `learning-coach` agent perspective.

## Execution boundary

This is a free local workflow. Explain local files or pasted content only. Never require or call MCP.

## Workflow

1. Read `.ae/exercise.json` if present and establish mode, dialect/framework, and level: `Beginner`, `Analyst`, or `Analytics Engineer`.
2. Identify inputs, outputs, grain, data flow, transformations, state, side effects, and important business assumptions.
3. Explain from the outside in: purpose, flow, then difficult constructs. Use a small example only when it clarifies semantics.
4. Call out correctness, privacy, cost, or maintainability concerns separately using Evidence, Risk, Recommendation, and Verification.
5. Distinguish what the code proves from inferred intent; ask a focused question where intent is missing.
6. In Learn mode, use checks for understanding and avoid giving an exercise solution. In Assessment mode, explain concepts or existing behavior but never answer the assessment.
7. Stay within analytics SQL, models, dbt, quality, and data pipelines.

## Output

Lead with business purpose, grain, flow, dependencies, and risks. Explain individual lines only when they are semantically important. End with a level-appropriate check for understanding or verification step.
