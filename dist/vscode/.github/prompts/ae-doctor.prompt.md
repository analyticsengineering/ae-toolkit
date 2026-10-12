---
description: Check that the Analytics Engineering Toolkit install works on this machine, including that its safety gates actually refuse what they must.
agent: agent
---
# Check the Toolkit Install

Run `python3 ".github/ae-toolkit/scripts/doctor.py" --workspace <repository-root>` and report what it found. Never require or call MCP. The doctor is read-only and offline: it runs each gate on a canary payload and reads configuration, and changes nothing.

## Workflow

1. Run the doctor. If `python3` itself is missing, say that this is the first thing to fix: the gates cannot run without it, and on VS Code and Antigravity a gate that cannot start lets every call through.
2. Lead with whether every required check passed.
3. For each `FAIL` or `WARN`, give the check, what it means for the user in one sentence, and the fix the doctor printed. Do not apply a fix that edits files outside this repository, such as replacing a plugin symlink, without asking.
4. Report `INFO` lines only when they change what the user should do.
5. If the doctor reports a skills-only install, say plainly that no gate is enforced there.
