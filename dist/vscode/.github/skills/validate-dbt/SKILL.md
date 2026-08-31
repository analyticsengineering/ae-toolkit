---
name: validate-dbt
description: Plans and runs the smallest safe dbt validation loop for changed or named resources. Use when the user asks to validate, compile, test, build, check, or verify dbt work, or asks the agent to fix failures and recheck them.
---

# Validate dbt

Close the loop from static evidence to a bounded, approved dbt result. Default silently to Work mode; use Learn or Assessment only when requested or required by `.ae/exercise.json`.

## Boundary

- This is a free local workflow. Never require or call MCP.
- Static inspection and planning never contact a warehouse.
- A warehouse-capable command runs only after the exact command, selector, target, and likely side effects are previewed and approved.
- Only an explicitly confirmed local or development target is eligible. Never infer a target, use a production-like target, run globally without a selector, or use `--full-refresh`.

## Procedure

1. Read `.ae/exercise.json` and `.ae/project.yml` when present.
2. Run the static inspectors before proposing execution:
   - `python3 ".github/ae-toolkit/scripts/inspect_dbt.py" <project-root> --pretty`
   - `python3 ".github/ae-toolkit/scripts/inspect_git.py" <project-root> --pretty`
3. Determine whether the user named a scope. If not, derive it only from changed dbt resources. Do not turn an unrelated dirty worktree into validation scope.
4. Run `python3 ".github/ae-toolkit/scripts/plan_dbt_validation.py" <project-root> --intent <intent> [--model <name>] [--target <dev-target>] --pretty`.
5. Review the plan rather than trusting it blindly. Confirm every selected node exists, YAML changes map to the reported models, renamed resources include downstream consumers, and the scope is not global.
6. Run static `dbt parse` and `dbt ls` steps one at a time when useful. Stop if selector resolution differs from the plan.
7. Before `compile`, `show`, `test`, `run`, `build`, `debug`, or `docs generate`, show one exact command and state:
   - why this is the smallest sufficient command;
   - the explicit target and evidence it is local/development;
   - resources and materializations in scope;
   - whether warehouse objects may be created or replaced.
8. Obtain approval, then run exactly that command. Do not batch a second dbt command into the same shell call.
9. Read the resulting `target/run_results.json` or bounded log with `python3 ".github/ae-toolkit/scripts/interpret_dbt_results.py" --run-results <path> [--log <path>] --pretty`.
10. If validation fails, identify the smallest repair. A new file may be created and reported. Any repair to an existing file requires a proposed diff, downstream blast radius, and approval before editing.
11. Re-plan after a repair. Never broaden a selector silently. Stop after five execution attempts and report unresolved evidence rather than looping.

## Command choice

- `parse`: project structure, Jinja parsing, and graph construction.
- `ls`: prove a selector resolves the intended resources.
- `compile`: compiled SQL is needed to resolve uncertainty; treat as warehouse-capable because adapter macros may connect.
- `test`: existing relations are current and only assertions need checking.
- `run`: build is needed but tests are intentionally out of scope.
- `build`: models and their tests both require validation; preferred final check for new model work.

Never auto-run `deps`, `seed`, `snapshot`, `run-operation`, a global command, or any command with `--full-refresh`.

## Failure interpretation

Separate compile, database, permission, dependency, selector, and test-assertion failures. A failing uniqueness test is evidence about candidate grain; it is not merely a test to weaken. A missing column may mean stale lineage, a wrong target, or a model defect. Resolve those alternatives from files and artifacts before editing.

## Output

Return `# dbt Validation` with: Status; Scope and selector evidence; Target confirmation; Commands planned and run with exit codes; Failures interpreted; Changes created; Existing-file repairs awaiting approval; Remaining uncertainty; Next smallest command or “None.”

## Verification

- Every execution used an explicit non-production target and a non-empty selector.
- Planned and resolved selector sets agree.
- Reported pass/fail comes from the current command and artifact, not an older terminal transcript.
- Every existing-file repair was approved before application.
- No credentials, profile values, raw rows, or unbounded logs appear in output.
