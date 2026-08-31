---
name: ae-learn
description: Infer this repository's analytics-engineering conventions from its existing models and propose a project profile.
---
This is the `ae-learn` alias of the `project-profile` skill. Follow that skill's full procedure and output contract; the summary below orients the request and does not replace it.

# Learn This Project

Apply the `project-profile` skill workflow. Report the conventions the repository already follows; judging whether they are good conventions is a different request.

## Execution boundary

This is a free local workflow. Use local project files only. Never require or call MCP, connect to a warehouse, or run dbt.

## Workflow

1. Confirm the project root. Read `.ae/exercise.json` if present, silently default to Work otherwise, and note whether `.ae/project.yml` already exists.
2. Run `python3 ".agents/ae-toolkit/scripts/infer_conventions.py" <project-root> --json` when Python is available. Treat its tallies as the evidence base for every convention you report.
3. Compare the inference against any stored `.ae/project.yml`. Human edits outrank inference; report differences as drift instead of replacing them.
4. Open the contradicting files behind each `split` convention and decide whether the disagreement is real, a legacy directory, or a migration in progress.
5. Report each convention at its evidence strength, and route every unresolved split into a single confirmation step rather than a series of questions.
6. Keep the profile ephemeral unless the user explicitly asks to persist or share it. An explicit save request permits creating `.ae/project.yml`; replacing a human-edited profile requires showing drift and receiving approval.
7. If the user edits a value you inferred, or a stored profile contradicts a fresh inference, collect those disagreements as inference corrections. Skip this entirely when the profile is accepted unchanged.
8. In Assessment mode, do not write the profile. In Learn mode, explain what each convention changes for later model building.

## Output

Return `# Project Profile` with: Detected stack; Conventions by strength; Open questions; Drift from stored profile; Proposed `.ae/project.yml`; What to confirm.

Open questions carries only `split` conventions and genuinely semantic unknowns, and What to confirm is a single accept-or-edit on the whole profile. Anything already reported as `strong` or `weak` is settled and must not reappear as a question. Both sections are legitimately empty in a consistent repository; say so rather than inventing a question to fill them.

Add `Inference corrections` only when a human value disagrees with a counted inference, and omit the heading otherwise. Give the field, the inferred value with its strength and counts, and the value the person chose, ordered so that an override of a `strong` inference comes first. Nothing is sent: the section exists so a defect in the inference can be described accurately, sharing is optional and carried by the person, and any value that could name a vendor, client, or business domain is flagged with a redacted form beside it.
