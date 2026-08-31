---
name: project-profile
description: Infers a repository's own analytics-engineering conventions from the models it already contains and records them for later workflows. Use when onboarding to an unfamiliar dbt project, establishing team conventions, or refreshing a stale project profile.
---

# Project Profile

Derive the team's conventions from the repository. Never ask a person to describe a pattern their own models already demonstrate.

## When to use

- Open an unfamiliar dbt project and need its naming, testing, documentation, and SQL conventions.
- Establish or refresh `.ae/project.yml` before building, refactoring, or documenting models.
- Reconcile a stored profile with a repository that has drifted since it was written.
- Do not use this skill to impose external best practice. It reports what this team does, not what a different team should do.

## Required context

Obtain:

- Project root and whether `.ae/project.yml` already exists.
- Scope of the profile when a monorepo holds more than one dbt project.

Default silently to Work mode and produce a profile ready to use. In Learn mode, explain why each convention matters downstream. In Assessment mode, evaluate a submitted profile without correcting it.

## Inspection procedure

1. Confirm the project root contains `dbt_project.yml`. Without it there is nothing to infer, and saying so is the correct answer. When `python3 ".agents/ae-toolkit/scripts/project_context.py" <repository-root>` reports more than one project, profile one of them by name; a monorepo's finance and marketing projects have separate conventions, and averaging them describes neither.
2. Run `python3 ".agents/ae-toolkit/scripts/infer_conventions.py" <project-root> --json`. Treat its tallies as the evidence base; do not restate conventions from memory of another repository. Read `project.adapter_confidence` before writing any warehouse-specific SQL: `none` means the repository has not said which warehouse it runs on, and `partition_by` or `cluster_by` in the models is not an answer, because several warehouses use both.
3. Read `.ae/project.yml` if it exists and compare its stored profile fingerprint against fresh inference. Report a changed fingerprint as staleness, then compare values; a human edit outranks an inference and must not be silently overwritten.
4. Inspect the highest-signal disagreements directly. When a convention is `split`, open the contradicting files named in `examples` and determine whether the split is a real disagreement or an artifact of layering, vendored packages, or a legacy directory mid-migration.
5. Separate **house conventions** from **observed resource patterns/contracts**. SQL/YAML style, test keys, naming, and surrogate-key implementations can be team-wide conventions. A source's `loaded_at_field` and freshness thresholds are resource contracts that can correctly differ by ingestion system, domain, or SLA; report them by source/table and never turn their majority into a default for an unrelated source. Materializations, schedules, and orchestration are declared configuration, not inferred patterns, and are reported as facts.
6. Identify what the repository cannot answer at all, and carry those forward as open questions rather than defaults.

## Decision framework

Report each convention at the strength the evidence supports:

- `strong`: dominant and repeated. Safe to apply silently in later workflows.
- `weak`: a real majority on thin or contested evidence. Usable, but every later application states the assumption.
- `split`: no dominant pattern. Escalate to a question with the candidate counts attached.
- `absent`: no evidence. Neither a convention nor a question; later workflows pick a defensible default and say so.

A young repository legitimately produces mostly `weak` conventions. Reporting thin evidence as settled practice is a worse failure than reporting uncertainty.

## Failure modes

- Asking the user which naming convention they use when the models answer it.
- Filling a required output section with an invented question because the repository left it empty.
- Presenting an inference as a team decision, or a personal preference as an inference.
- Treating the most common source load field or freshness SLA as a team-wide convention.
- Overwriting hand-edited profile values with a fresh inference.
- Reading a vendored `dbt_packages` directory as if it were the team's own code.
- Averaging away a genuine split so the profile looks complete.
- Treating a convention that holds across three models as established practice.
- Raising inference corrections when the profile was accepted unchanged, which turns a useful offer into a recurring prompt.

## Evidence required

Every convention cites its supporting count, contradicting count, and at least one example file. Percentages state their denominator. Drift between a stored profile and the repository names both values and the files that disagree.

## Output contract

Return `# Project Profile` with: Detected stack; House conventions by strength; Observed resource patterns/contracts; Open questions; Drift from stored profile; Proposed `.ae/project.yml`; What to confirm. Add `Inference corrections` only under the condition described below.

Present conventions as "detected from N models," and put every `split` convention in Open questions with its candidates. Ask for confirmation of the whole profile once rather than field by field.

Two of these sections are frequently empty, and empty is the correct result rather than an incomplete one:

- Open questions holds only `split` conventions and genuinely semantic unknowns. A repository that is internally consistent produces none. Write "None; every convention below is settled by the repository" and move on.
- What to confirm is a single accept-or-edit on the whole profile, not a list of decisions to relitigate. Nothing reported as `strong` or `weak` may reappear here as a question. If you have already counted a prefix, a directory, a test pair, a YAML layout, or a SQL style, it is settled, and asking the reader to choose it contradicts the section above that just proved it.

Never manufacture a question to fill a section. If both sections are empty, the profile is finished, and saying so is the strongest possible answer.

## Inference corrections

When a person changes a value this workflow inferred, that edit is the most informative thing the run produces. It is a labelled example of static inference being wrong, or of a convention that files alone cannot express, and it costs nothing to surface because it already exists on disk.

Include this section only when a human value disagrees with a counted inference: an edit made to the proposed profile during this run, or a stored `.ae/project.yml` value that contradicts a fresh inference. Omit it entirely otherwise. Unlike the sections above it is an offer rather than a finding, and an offer repeated when there is nothing to offer is noise.

Report each disagreement as the field, the inferred value with its strength and counts, and the value the human chose. They do not carry equal information, so order them accordingly:

- Overriding a `strong` inference is the strongest signal. Either the counting misread the repository, or the team is deliberately moving away from its own dominant pattern. Both matter and the files cannot distinguish them, so report it without deciding which it is.
- Filling an `absent` or `split` field shows what static inference cannot see at all.
- Correcting a `weak` inference points at mis-tuned evidence thresholds rather than a misreading.

Nothing is transmitted. This plugin has no network path, and the section exists so that someone who wants to report an inference defect can copy an accurate description of one. State that sharing is optional, one-directional, and carried by the person rather than the tool.

Field names, strengths, and counts are generic and identify nobody. Values are not always: a source schema can name a vendor, a directory can name a client, and a prefix can encode a business domain. Flag any value carrying that risk and offer a redacted form beside it, so the decision to share is made against a payload the reader has actually seen.

## Verification

- Re-run the inference after the user edits the profile and confirm the edits survive.
- Spot-check at least one example file per `strong` convention before publishing it.
- Confirm counts sum correctly against the model inventory and that excluded paths are named.
- Recompute any percentage you derive yourself rather than restating a tool figure with new arithmetic on top.

## Safety/privacy

- Inference is static. Never execute dbt, contact a warehouse, or call MCP to build a profile.
- Keep inference ephemeral unless the user explicitly asks to persist or share the profile. An explicit save request permits creating `.ae/project.yml`; replacing a human-edited profile still requires showing drift and receiving approval.
- Never copy credentials, connection strings, or profile targets into the output.
- Inference corrections are written into the local output and nowhere else. Never offer to send one, and never read a willingness to share as approval for anything further.

## What not to assume

Do not assume the largest directory is canonical, that a stored profile is current, that vendored packages reflect team style, that a convention with few instances is settled, or that a split is an error rather than a migration in progress.
