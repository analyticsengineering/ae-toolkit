---
name: freshness-investigation
description: Investigates whether analytical data is ready by separating configured schedules and freshness expectations from locally observed timestamps and run artifacts. Use when data appears stale, late, incomplete, or unavailable; it explains timing evidence and gaps without inventing runtime history or querying external systems.
---

# Freshness Investigation

Explain data readiness from configured expectations and observed timing evidence. A schedule describes intent; only current, inspected runtime evidence describes what happened.

## When to use

- Investigate stale, delayed, missing, or not-yet-ready analytical data.
- Explain when an asset is expected, what local evidence shows, and which timing boundary is unknown.
- Compare source arrival, ingestion, transformation, publication, and BI refresh timing.
- Use for diagnosis and readiness reporting, not pipeline reruns or remediation.

## Mode and context

Default silently to **Work** mode. Use **Learn** only when teaching is requested and **Assessment** only when evaluation without answers is requested or `.ae/exercise.json` requires it.

Obtain or mark missing:

- Asset, affected consumers, expected availability, evaluation time, business impact, and required time zone.
- Source event/updated time, ingestion time, transformation run time, publication time, and consumer refresh time where available.
- Local schedules, freshness policies, manifests, results, source-status artifacts, logs, state files, and incident notes.
- Environment, partition/window, recent changes, owners, and known backfill or late-data behavior.

## Local inspection procedure

1. Read `.ae/exercise.json` and `.ae/project.yml` when present.
2. Infer orchestration, transformation, adapter, artifact, naming, schedule, time-zone, and BI/vendor conventions from local configuration before interpreting timing.
3. Build a current exact inventory of candidate files and record each file's path, embedded generation/invocation timestamp, environment, and scope. File modification time is supporting metadata, not proof of a data event.
4. Separate evidence into:
   - **Configured:** schedules, cron expressions, dependencies, freshness warn/error thresholds, SLAs/SLOs, retry policies, and publication rules.
   - **Observed:** timestamps and statuses in inspected run results, source freshness results, logs, state, exported metadata, or user-provided incident evidence.
   - **Derived:** lags or readiness windows recomputed from observed timestamps with formula and time zone.
   - **Unknown:** timing boundaries with no current evidence.
5. Trace readiness upstream to downstream: source availability, extraction, load, transformation, tests/gates, publication, semantic/BI refresh, and consumer visibility.
6. Identify the first boundary where expected and observed timing diverge. Do not anchor on the latest change.
7. Rank hypotheses and record evidence for, evidence against, status, and the smallest local or user-run test that distinguishes them.
8. Report current readiness and confidence. Never convert missing evidence into an on-time or late claim.

## Readiness states

- **READY** — inspected evidence shows required upstream data and publication gates completed for the named window.
- **NOT READY** — inspected evidence shows a required boundary incomplete or beyond its configured/approved expectation.
- **CONFIGURATION MISMATCH** — schedules, thresholds, dependencies, or time zones cannot satisfy the stated expectation.
- **UNKNOWN** — current evidence cannot establish one or more required boundaries.

State configured expectation and observed status separately even when they agree.

## Evidence required

Maintain a ledger with evidence class, exact file, embedded timestamp, environment, scope/window, observed value, interpretation, and limitations. Runtime claims require current inspected runtime evidence; configuration, comments, stale artifacts, remembered runs, and terminal summaries cannot substitute.

For every derived duration, show start, end, time zone, formula, and units. For historical rates or percentiles, state the run population and denominator; if multiple comparable observations are absent, do not invent a trend.

Every actionable finding includes **Evidence**, **Risk**, **Recommendation**, and **Verification**, plus severity and confidence from `.agents/ae-toolkit/references/severity-model.md`.

## Failure modes

- Treating a cron schedule or freshness threshold as proof a run occurred.
- Treating one current artifact as runtime history or a service-level trend.
- Comparing timestamps without normalizing time zones, windows, or environments.
- Using file modification time as source arrival or completion time.
- Equating transformation success with complete source data or BI visibility.
- Calling data late when the promised consumer availability time is unknown.
- Declaring root cause from temporal proximity or recovery alone.

## Output contract

Return `# Freshness Investigation` with: Readiness and confidence; Asset/window/evaluation time; Configured expectations; Observed timing; Derived lags; End-to-end boundary status; First divergence; Hypothesis ledger; Consumer impact; Unknowns; Recommended next evidence; Verification.

Lead with whether the named data window is `READY`, `NOT READY`, `CONFIGURATION MISMATCH`, or `UNKNOWN`. Include a concise expected-versus-observed timeline only for boundaries supported by evidence. Say explicitly when no runtime history was available.

## Verification

- Re-read every cited artifact and confirm environment, invocation, window, and timestamp semantics.
- Recompute lags after normalizing to the stated time zone.
- Check an affected and an unaffected asset or partition when local evidence permits.
- Distinguish source freshness, load completion, transformation success, publication, and BI refresh.
- Propose exact bounded user-run checks for remaining unknowns; do not execute them.

## Safety and repository writes

- Local Basic only: use local files and user-provided material. Never call MCP, access a warehouse, execute dbt, contact an orchestrator/BI service, or rerun a pipeline.
- Never expose credentials, connection strings, raw incident payloads, personal data, or protected metric values.
- New files may be created only when requested. Before editing or deleting any existing file, show the exact proposed change, state blast radius across sources, models, tests, exposures, schedules, semantic artifacts, and BI consumers, and obtain explicit approval.
- Preserve evidence and separate diagnosis from any later remediation request.
