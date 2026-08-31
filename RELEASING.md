# Releasing

A release of this toolkit changes how an agent behaves inside someone else's
repository. There is no runtime kill switch and no telemetry to tell us it went
wrong, so the release gate is evidence that behavior held, not that the code
compiles.

## What a version number means here

- **Patch** — a workflow produces better output for the same request, a
  reference resolves that previously did not, or a defect in a script is fixed.
  No skill, command, or agent is added or removed, and no gate loosens.
- **Minor** — a skill, command, or reference is added, or an existing workflow
  gains a capability. Existing requests keep working.
- **Major** — a request that previously succeeded now behaves differently, a
  gate changes what it permits, or an installed layout moves.

Loosening an approval gate is never a patch, however small the diff. A user who
reads "1.2.1 — packaging fixes" and upgrades has not consented to an agent that
now edits something it previously asked about.

## Before a release

Run everything and require green. Each check answers a different question, so a
skip is a gap, not a shortcut.

```bash
python3 tests/run_tests.py                 # public behavior and packaging
python3 scripts/build_targets.py --check   # generated hosts match the source
```

Then, in the private validation repository:

```bash
python3 scripts/sync_toolkit.py ../ae-toolkit   # pin the commit under measurement
python3 tests/run_tests.py                      # fixed-matrix and inspector suites
python3 scripts/scenario_evidence.py            # declared evidence matches fixtures
python3 scripts/check_boundaries.py             # no holdout or credential material tracked
uv run python -m unittest discover -s tests -p test_sdk_evals.py
```

Confirm the version consistency the tests enforce: the manifest version equals
the newest released changelog heading, no version is documented twice, and the
headings descend.

## Behavioral evidence

Automated suites verify that the toolkit says what it is supposed to say. They
cannot verify that it is better than the same agent without it. That requires a
paired run.

Any release that changes a rule, a skill body, a gate, or a reference document
needs a paired behavioral matrix over the affected workflows, compared against
the previous baseline on safety, delivery rate, framework leakage, adapter
correctness, and response length. Report the number of trials. A single paired
draw is an observation; treat it as one, and do not publish a percentage derived
from it.

Sealed holdouts live outside this repository. Run them before reading them. A
holdout whose expected answer was read while fixing the thing it measures has
stopped being evidence and nobody downstream can tell.

## Privacy check

The public repository must contain no private scenario identifier, run artifact,
holdout material, secret, personal email address, or absolute local path. The
packaging suite enforces the paths and the secret scan; the author identity on
each commit is not covered by any test, so check it directly:

```bash
git log --format='%an <%ae>' | sort -u
```

Every address should be a GitHub `noreply` address. A commit already pushed with
a personal address cannot be corrected without rewriting published history, so
this check belongs before the first push of a branch, not after.

## Cutting the release

1. Move the accumulated `Unreleased` entries into a dated version heading.
2. Set the manifest version to match.
3. Record the evidence for the release using the template below.
4. Commit, and stop.

Pushing, tagging, publishing a GitHub Release, and submitting to a marketplace
are separate deliberate acts. Nothing in this document performs them.

## Release evidence template

Copy this into the release notes or the pull request that cuts the version.

```markdown
## Release evidence — <version>

Toolkit commit:
Date:

### Suites
- Public suite: <count> tests, pass/fail
- Generated target drift: in sync / drifted
- Private fixed matrix: <count> tests, pass/fail
- Scenario evidence: pass/fail
- Mocked SDK harness: <count> tests, pass/fail
- Boundary check: pass/fail

### Behavioral comparison
- Baseline compared against:
- Workflows exercised:
- Trials per cell:
- Safety: <toolkit> vs <vanilla>
- Delivery rate:
- Framework leakage:
- Adapter correctness:
- Median response length:
- Assertion contract hash:

### Holdouts
- Sealed sets run:
- Run before their expected answers were read: yes/no

### Privacy
- Tracked private material: none / <list>
- Commit author addresses: <list>

### Known gaps
What this release was not able to verify, and why.
```
