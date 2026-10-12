## What changes

<!-- The behaviour a user will notice, in one or two sentences. -->

## Why

<!-- The analytics-engineering practice this follows, or the defect it fixes. -->

## Checklist

- [ ] `python3 tests/run_tests.py` passes
- [ ] `python3 scripts/build_targets.py --check` passes (rebuild with `python3 scripts/build_targets.py` after editing skills, rules, commands, agents, hooks, or scripts)
- [ ] Tests cover the new behaviour, and a gate change has a test that fails without it
- [ ] `CHANGELOG.md` has an entry under Unreleased
- [ ] No credentials, production data, personal data, or absolute local paths in code, fixtures, or docs
