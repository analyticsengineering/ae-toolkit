---
name: ae-diagnostic
description: Diagnose Analytics Engineering Toolkit setup, exercise context, and optional connection readiness without exposing secrets.
---

# Analytics Engineering Diagnostic

Apply the `learning-coach` agent in Assessment mode.

## Execution boundary

- **Unauthenticated/disconnected:** Offer and run a short local sample diagnostic, or explain the login flow. Clearly label local results as non-authoritative.
- **Connected:** Authenticate, request the server-authoritative diagnostic policy, preview the minimum assessment packet, and obtain approval before transmission.

## Workflow

1. Do not reveal hidden answer keys, rubric internals, or answers while the diagnostic is active.
2. Evaluate the configured domains: SQL; Modeling; dbt; Quality; Python/APIs; Engineering Workflow; AI Data Workflows.
3. Preserve the learner's submitted answers exactly; do not repair them before evaluation.
4. If connected, follow server rules for question selection, timing, attempts, feedback, scoring, and allowed review. Client-side Assessment mode is not tamper-proof.
5. If authentication or the endpoint is unavailable, fall back only to the labeled local sample or login guidance; never invent an official score.
6. Return domain-level strengths, evidence-based gaps, and next learning actions only to the extent server policy permits.
