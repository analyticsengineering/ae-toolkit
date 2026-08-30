---
name: ae-grade
description: Grade the active analytics-engineering exercise against its supplied rubric without editing or revealing the answer.
---
# Grade an Exercise Submission

Apply the `learning-coach` agent's Assessment workflow. This is an explicitly triggered connected grading command.

## Execution boundary

- **Local Basic:** Read `.ae/exercise.json`, rubric references, and the learner-selected submission only to validate scope and prepare a minimal redacted preview. Do not call MCP, assign a grade, or edit files.
- **Connected Advanced:** Required for grading. Authenticate with the configured grading provider, show the provider and exact redacted content preview, and obtain explicit approval before transmission. If any gate fails, stop without grading.

## Workflow

1. Require a valid `.ae/exercise.json` in Assessment mode with exercise identity, permitted artifacts, and rubric or criteria. Do not invent criteria or silently change modes.
2. Freeze the submission scope. The first grading pass is strictly read-only: never edit, format, fix, or execute destructive actions.
3. Remove secrets, credentials, PII, raw data, unrelated files, hidden answers, and unnecessary context from the payload.
4. Authenticate, show destination, permissions, redacted payload, and risks, then wait for explicit approval; command invocation alone is not approval.
5. After approval, evaluate only against supplied criteria and authorized tests. Separate correctness evidence from style and from unavailable evidence.
6. Return score, rubric categories, passed checks, failed checks, and next actions, with criterion-level evidence and confidence.
7. Never reveal the expected answer, provide replacement SQL/code, or edit the submission. Offer conceptual next steps only.
