---
description: Self-check an analytics-engineering exercise submission against its supplied rubric, locally and read-only, without editing or revealing the answer.
agent: agent
---
# Self-Check an Exercise Submission

Apply the `learning-coach` agent's Assessment workflow. This runs locally against the rubric the exercise supplies. It is a self-check, not an official grade: it records nothing, submits nothing, and sends nothing anywhere.

## Workflow

1. Read `.ae/exercise.json` for exercise identity, permitted artifacts, and the rubric or the path to it. If no rubric or criteria are supplied, say so and stop; do not invent criteria.
2. Freeze the submission scope to the permitted artifacts. The whole pass is read-only: never edit, format, fix, or run anything against a warehouse.
3. Evaluate only against the supplied criteria. Static checks (parsing, grain reasoning, test coverage, naming) are fine; anything that needs execution is reported as unverified, not passed.
4. Separate correctness evidence from style and from evidence that is unavailable locally.
5. Never reveal the expected answer, write replacement SQL or code, or edit the submission. Offer conceptual next steps only.

## Output

Return `# Local Self-Check` with:

- a first line stating this is a local self-check against the supplied rubric, not an official grade or submission;
- a score per rubric category, with the criterion and the evidence (file and line) behind each;
- passed checks, failed checks, and checks that could not be verified locally;
- next actions, conceptual only.
