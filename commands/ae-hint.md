---
name: ae-hint
description: Request a progressive, non-solution hint for the active analytics-engineering exercise through the approved learning workflow.
---

# Request an Exercise Hint

Apply the `learning-coach` agent and its progressive hint ladder. This is an explicitly triggered connected learning command.

## Execution boundary

- **Local Basic:** Read `.ae/exercise.json` and the learner-selected local artifact only to identify mode and prepare a minimal, redacted content preview. Do not call MCP or produce the hint in this stage.
- **Connected Advanced:** Required for hint delivery. Authenticate with the configured learning provider, show the provider and exact redacted content preview, and obtain explicit approval before transmitting anything. If authentication or approval is absent, stop without a hint.

## Workflow

1. Verify `.ae/exercise.json` exists and parse exercise identity, Learn or Assessment mode, constraints, allowed context, hint state, and expected artifact. If missing or invalid, stop and explain.
2. Ask the learner to select the relevant artifact and summarize what they tried and where they are stuck.
3. Minimize and redact the payload: remove secrets, credentials, connection strings, PII, unrelated code, raw data, and hidden answer or rubric content.
4. Authenticate, then display the destination, payload preview, and privacy risk. Ask for explicit approval; command invocation alone is not approval.
5. After approval, request exactly one next-level hint: Hint 1 gives conceptual direction; Hint 2 is more specific; Hint 3 points to the relevant construct or pattern.
6. A solution is allowed only when server policy permits it, the user explicitly requests it after attempts, and the exercise is not in Assessment mode. Never reveal hidden tests or answer keys.
7. Record or report the hint level only if permitted; verify the learner can state their next step.
