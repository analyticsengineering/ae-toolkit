# How AE Toolkit is evaluated

AE Toolkit changes how a coding agent behaves inside someone else's data repository. "The tests pass" only shows that the toolkit says what it is supposed to say. It does not show that an agent using it does better work. So the toolkit is checked two ways:

1. **Deterministic tests** check the code: the safety gates, the inspectors, the packaging, and the rules the workflows must follow. They run on every change and anyone can run them.
2. **Paired behavioral evaluation** checks the outcome. The same agent does the same analytics-engineering task with and without the toolkit, many times, and the results are scored the same way.

This page explains both, reports the latest results, and says plainly what they do not prove.

## Results at a glance

On tasks written by a separate author who never saw the toolkit, the same agent missed about 40% fewer of the checks a task required once AE Toolkit was installed:

| | Agent alone | Agent + AE Toolkit | Change |
| --- | --- | --- | --- |
| Holdout set A: checks missed | 21.0% | 12.5% | 40% fewer |
| Holdout set B: checks missed | 18.2% | 11.2% | 38% fewer |

| Holdout set A: 8 tasks, 320 runs | Mean score | Runs with every check passed |
| --- | --- | --- |
| Agent alone | 0.790 | 69 of 160 (43%) |
| Agent + AE Toolkit | **0.875** | **82 of 160 (51%)** |

| Holdout set B: 12 tasks, 287 runs | Mean score | Runs with every check passed |
| --- | --- | --- |
| Agent alone | 0.818 | 78 of 143 (55%) |
| Agent + AE Toolkit | **0.888** | 79 of 144 (55%) |

A score is the share of a task's checks that passed, averaged over every run, and "checks missed" is one minus the mean score. Set A's result is statistically clear. Set B's points the same way with smaller margins and is not conclusive on its own; the sections below give the head-to-head results for each. The rest of this page covers how the runs were made and where the toolkit did worse.

## Deterministic tests

These run in CI on Python 3.9 and 3.13, on Linux and macOS:

```bash
python3 tests/run_tests.py                 # behavior, safety, and packaging
python3 scripts/build_targets.py --check   # generated host layouts match the source
```

The public suite covers:

- **Safety gates.** Commands the shell gate must deny, hold for approval, or allow, including launch forms written to slip past it (`FOO=1 rm -rf`, `python -m dbt`, `uvx dbt build`, a second SQL statement hidden behind a semicolon). Several tests switch a guard off and confirm the original defect returns, so a refactor cannot quietly remove a protection.
- **The published-model guard.** Which edits it pauses, which it lets through, and what it does when it cannot tell.
- **Inspectors and planners.** dbt v1 and dbt v2 fixture projects, including stale artifacts, `--no-write-json`, reused results under dbt State, versioned and deleted resources, monorepos, and renamed resource paths. [COMPATIBILITY.md](COMPATIBILITY.md) lists what each dbt feature's support rests on.
- **Workflow contracts.** Each workflow must state its evidence, output, and approval boundaries, and two workflows may not give contradictory instructions.
- **The Agent Skills standard.** A skill whose name disagrees with its folder, or whose description is too long, is dropped by hosts without an error, so the suite fails first.

Maintainers also run a private suite before each release. It holds a fixed matrix of inspector cases, checks that each scenario's declared evidence matches its fixture, tests the evaluation harness itself, and confirms that no holdout or credential material is tracked anywhere public.

## Paired behavioral evaluation

### What is compared

Every task is run by two setups. The agent, model, task, and repository are identical in both, and only the installed guidance differs:

- **Agent alone**: no extra skills or rules.
- **Agent + AE Toolkit**: the full Cursor plugin, including rules and hooks.

### The tasks

Each task is a small, realistic repository plus a request, the way an analytics engineer would phrase it to a colleague. Tasks are drawn from work where a wrong answer is expensive, such as:

- building models at the right grain;
- incremental logic and late-arriving data;
- tests and freshness, especially when one is failing;
- changing a model other teams consume;
- snapshots and stored history;
- requests that contradict the repository's own documentation;
- package upgrades;
- non-dbt repositories;
- ordinary changes where the right answer is simply to do the work.

Each set mixes tasks that reward stopping to ask with ordinary controls that look similar but should simply be done. A toolkit that pauses on everything loses points on the controls.

Each request is written four ways: **direct**, **terse**, **conversational**, and **edge** (adversarial wording, such as "skip the analysis, this is a simple rename"). Each phrasing runs several times per setup, because one run of a language model is a single draw, not a result.

### Keeping the test honest

- **A separate author.** The holdout tasks were written by an agent that could not see the toolkit, earlier task sets, or past results.
- **Run before reading.** A holdout set's tasks and expected outcomes stay unread until its runs finish and are scored. Once a set has been read, it can't measure anything fixed using what was learned from it, so it is retired and not reused for a headline.
- **Rules fixed in advance.** Each set's scoring checks are fingerprinted before the runs start, and the harness refuses to continue if they change midway.
- **Isolated runs.** Each run gets a fresh copy of the repository in its own scratch folder. Every transcript is audited for reads outside that folder, and a run that touched another run's files is excluded rather than scored.
- **Scored on what changed.** Most checks inspect the files the agent created, changed, or left alone. The rest check that the response says something specific, for example that it asked the one question the task depends on. When a wording check turned out to misread normal phrasing, it was corrected for every setup at once and every run was rescored.
- **Paired comparison.** Results are compared run against run on the same task, phrasing, and trial. A win means one setup scored higher on that draw.

### Holdout set A

8 tasks × 4 phrasings × 5 runs × 2 setups = 320 runs. None failed or was excluded. Model: Cursor Composer 2.5. The toolkit was an earlier 1.4 pre-release build.

Head-to-head, run against run:

| Comparison | Wins | Losses | Ties | Chance of a split this lopsided if neither were better |
| --- | --- | --- | --- | --- |
| AE Toolkit vs. agent alone | 57 | 19 | 84 | 0.002% |

Most runs tie, because on most tasks both setups do well. The differences come from a minority of tasks where a plausible-looking answer is wrong. On two of those tasks, the agent alone scored 0.47 and 0.55, and the agent with AE Toolkit scored 0.80 and 0.92.

AE Toolkit did worse on 2 of the 8 tasks, both routine (0.91 against 1.00 for the agent alone). Most of the lost points came from pausing to confirm something the repository already settled.

### Holdout set B

12 tasks × 4 phrasings × 3 runs × 2 setups = 288 runs. One run of the agent alone was excluded because it read a file belonging to another run, leaving 287. Model: Cursor Composer 2.5. The toolkit was the 1.4.0 release candidate, with the same guidance and hooks as 1.4.0.

| Comparison | Wins | Losses | Ties | Chance of a split this lopsided if neither were better |
| --- | --- | --- | --- | --- |
| AE Toolkit vs. agent alone | 46 | 35 | 62 | 27% |

The mean score is higher with the toolkit, as on set A, but on this set alone the head-to-head result is not conclusive. The toolkit changed the outcome often, mostly for the better:

- AE Toolkit was ahead of the agent alone on 7 of the 12 tasks, often by a wide margin (0.48 to 0.74, 0.67 to 1.00, 0.74 to 0.97).
- It was behind on 4, by 0.05 to 0.13 each. The agent alone already handled all four well (0.92 to 1.00).
- By phrasing, it was ahead on direct, terse, and conversational requests (by 0.08 to 0.17) and behind on edge-case wording (0.852 against 0.942).
- It raised the mean score without raising the share of runs that passed every check. It fixed more of the large failures, and left slightly more small misses on routine tasks.

The same set was also run against the October 8 pre-release build measured on set A. The two builds scored the same (24 wins, 25 losses, and 95 ties against each other, with means within 0.003), so the release candidate kept set A's result without improving on it.

### Cost

The toolkit's rules and skills are read by the agent, so a request uses more tokens. Token counts were recorded for every run and priced at Cursor's published Composer 2.5 rates:

| Average model cost per request | Agent alone | Agent + AE Toolkit | Ratio |
| --- | --- | --- | --- |
| Holdout set A | $0.095 | $0.152 | 1.6× |
| Holdout set B | $0.089 | $0.172 | 1.9× |

Other models price tokens differently, so the cents change, but the extra reading is similar. Whether that is worth it depends on what a missed check costs your team: a broken dashboard or a hidden outage usually costs far more than a few cents.

### What these results do not show

- **Other models.** Every behavioral run used one model, Cursor Composer 2.5. Larger models already do some of what the toolkit encourages, so the gap may be smaller with them.
- **Real repositories.** The tasks are synthetic repositories built to resemble real projects. They are not anyone's production code.
- **Other hosts and skills-only installs.** Only the Cursor plugin was measured. The VS Code, Antigravity, and skills-only installs share the same guidance, but the skills-only install has no enforced gates, so its results may differ.
- **Long sessions.** Each run is a single request. Behavior over a long working session was not measured.
- **Per-skill value.** The toolkit is measured as a whole. These runs cannot say which individual skill helps, so none was removed on the strength of this data.
- **Comparing across sets.** Scores are only comparable within a set, because each set has different tasks and checks.

### Known weakness

On routine work the toolkit is sometimes more cautious than it needs to be, and adversarial phrasing makes this worse. It pauses for confirmation the repository has already given. This is the main thing the next release has to fix. Fixing it must not weaken the stops that produce the large wins, and the fix has to be measured on a new holdout set.

## Reproducing this

The holdout tasks stay private. Publishing them would let future guidance be tuned to them, and the measurement would stop meaning anything. The method does not depend on them, though. To check the toolkit on your own work:

1. Pick a handful of real requests from your team's history, including some where an AI agent, or a person, got it wrong.
2. Run each request several times in a fresh copy of the repository, with the toolkit and without it, on the same model.
3. Decide in advance what a correct result looks like, based on the files changed and the questions asked, and score every run the same way.

If you find a task where the toolkit makes the agent worse, please [open an issue](https://github.com/analyticsengineering/ae-toolkit/issues/new/choose). Those reports are the most useful thing a user can send.
