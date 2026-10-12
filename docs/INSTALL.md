# Installing AE Toolkit

AE Toolkit is authored once, as a Cursor plugin, and generated into layouts for other hosts. Pick the install that matches your editor:

| | Cursor plugin | VS Code, Antigravity | Skills only |
| --- | --- | --- | --- |
| Skills and their scripts | yes | yes | yes |
| Always-on rules | loaded by Cursor | `AGENTS.md` | read by each skill |
| Commands and agents | yes | yes | no |
| Shell and dbt MCP gates | enforced, fail closed | enforced; a gate that cannot launch leaves the call ungated | none |
| Published-model guard | yes | no | no |

Python 3.9 or newer is required for the inspectors, the hooks, and the tests. Windows is not yet supported. After any install, run the doctor (see [Troubleshooting](#troubleshooting)).

## Cursor

Cursor loads local plugins from `~/.cursor/plugins/local`. The plugin name is `analytics-engineering-toolkit`, so the install directory keeps that name even though the repository is `ae-toolkit`.

```bash
git clone https://github.com/analyticsengineering/ae-toolkit.git
cd ae-toolkit
mkdir -p ~/.cursor/plugins/local
rsync -a --exclude '.git' ./ ~/.cursor/plugins/local/analytics-engineering-toolkit/
```

If that destination already exists, inspect it before replacing it. Do not create a second plugin with the same name. A copy does not track the repository, so re-run the `rsync` after each pull, then reload the window.

**Install a real directory, not a symlink.** Cursor's documentation suggests a symlink for faster iteration, but Cursor refuses to load a local plugin whose symlink resolves outside the plugins folder, and the refusal is quiet: the plugin is simply absent, and the reload still reports `failures=0`. The reason appears only in the log, as

```text
loadUserLocalPlugin analytics-engineering-toolkit rejected: symlink target
  <your clone> is outside ~/.cursor/plugins/local
```

This was observed on Cursor 3.8.11. The doctor detects a symlinked install on any version.

Then:

1. Restart Cursor, or run **Developer: Reload Window** from the Command Palette.
2. Open **Customize** in the Cursor sidebar.
3. Confirm **Analytics Engineering Toolkit** is present and its skills, rules, commands, and hooks are visible.
4. Enable only the components and scopes you intend to use.

On Teams and Enterprise, local imports may be disabled by an administrator. The setting is **Allow Local Plugin Imports** under **Dashboard → Settings → Security & Identity → Marketplace and Plugins**; it is off by default on Enterprise. An installed marketplace plugin with the same name takes precedence over a local copy.

See Cursor's [Plugins guide](https://cursor.com/docs/plugins) and [Plugins reference](https://cursor.com/docs/reference/plugins).

## VS Code and Google Antigravity

The workflows, the rules, and the safety gates are the same files reaching the same verdicts; only the packaging differs. Build the targets, then install one into your repository:

```bash
python3 scripts/build_targets.py
python3 scripts/install_target.py --host vscode --workspace /path/to/your/repo
```

Use `--host antigravity` for Antigravity, and add `--dry-run` to see what would change first.

The installer does three things a plain copy does not:

- **It merges rather than overwrites.** An `AGENTS.md` or hook configuration you already maintain keeps its contents; the toolkit's rules land inside a marked block that a reinstall updates in place.
- **It rewrites hook commands to absolute paths.** This matters most on Antigravity, where a relative path is resolved against the directory the session started in, and a hook that fails to launch does not block the call it was meant to gate.
- **It checks enforcement.** It runs a command the gate is required to refuse and reports whether it was refused, so you learn at install time whether enforcement works on your machine.

What lands in your repository:

| | VS Code | Antigravity |
|---|---|---|
| Skills | `.github/skills/` | `.agents/skills/` |
| Commands | `.github/prompts/` as prompt files | `.agents/skills/` as skills |
| Agents | `.github/agents/` | `.agents/agents/` |
| Rules | `AGENTS.md` | `AGENTS.md` |
| Safety gates | `.github/hooks/ae-toolkit.json` | `.agents/hooks.json` |
| Scripts and references | `.github/ae-toolkit/` | `.agents/ae-toolkit/` |

Cursor gives shell execution and MCP calls their own hook events, while VS Code and Antigravity route every tool through a single `PreToolUse` event. Both gates are registered on that one event, and each stands aside for traffic that is not its own, so the behavior matches Cursor even though the wiring does not. The published-model guard is the exception: it reads Cursor's edit-tool payloads and conversation record, and is registered on Cursor only.

Neither host lets a hook declare that it must block when it fails to launch. Keep `python3` available: on these two hosts, an absent interpreter silently removes the gate instead of stopping the work.

## Skills only: Claude Code, Codex, Gemini CLI, OpenCode, and other Agent Skills hosts

```bash
npx skills add analyticsengineering/ae-toolkit
```

Add `--skill <name>` to take only some. Each skill carries the scripts and references it calls and a copy of the toolkit's always-on rules, so a skill installed by itself still runs its deterministic inspectors.

A skills-only install has no hooks, so nothing enforces the approval gates; the rules ask the agent to follow them, and that is all. Use the Cursor plugin, or the VS Code or Antigravity install, when you want the gates enforced.

## Using it with the dbt MCP server

The dbt MCP server can stay configured. The toolkit ships and configures no MCP server of its own. Its MCP gate holds the dbt server's warehouse-executing tools (`build`, `run`, `test`, `show`, `execute_sql`, `query_metrics`, job triggers, and similar) for approval, exactly as the shell gate holds `dbt run`, and lets its metadata tools through.

## Troubleshooting

Start with the doctor. It runs each gate on a payload the gate must refuse or hold, checks the interpreter the hooks will actually use, and catches a symlinked Cursor install and relative hook paths, all without touching a shell, warehouse, or network:

```bash
python3 scripts/doctor.py --workspace /path/to/your/repo
```

From an installed VS Code or Antigravity target, run the copy under `.github/ae-toolkit/scripts/` or `.agents/ae-toolkit/scripts/`. In chat, `/ae-doctor` runs it and explains anything that failed.

### The plugin does not appear in Cursor

- Confirm the final path is `~/.cursor/plugins/local/analytics-engineering-toolkit/.cursor-plugin/plugin.json`.
- Confirm the install is a real directory rather than a symlink.
- Open the **Output** panel (`Cmd+Shift+U` on macOS), select **Cursor Plugins**, and search for `rejected: symlink target` or another load warning.
- Restart Cursor or run **Developer: Reload Window**.
- Open Customize and check the correct user or workspace scope.
- Ask your administrator whether local plugin imports are allowed.
- Remove naming conflicts; a marketplace install with the same name wins.

### A workflow is missing

Re-copy and reload after changing the source repository. In Customize, confirm the skill is enabled. If a skill is missing on VS Code or Antigravity, the cause is almost always its `name` disagreeing with its directory name, which both hosts treat as a reason to skip the file without saying so; `python3 tests/run_tests.py` checks that.

### A dbt MCP tool asked for approval

That is the MCP gate treating it like `dbt run` in the shell. Read what it will execute, confirm the target is development, and approve only that call. Metadata tools such as `get_model_details` or `list_metrics` pass without asking.

### A command was blocked

Read the safety gate's reason. Destructive database writes are intentionally unsupported. For approved read-only work, confirm the target is local or development, narrow the query, and approve only the displayed command.

## Host smoke test

The generated layouts are checked against each host's published documentation and by the test suite. What those cannot show is whether the editor actually discovers the files, because that needs the editor. This checklist takes a few minutes per host.

Install into a scratch repository rather than a real one, so a mistake costs nothing:

```bash
python3 scripts/build_targets.py
mkdir -p /tmp/ae-smoke && cd /tmp/ae-smoke && git init
python3 /path/to/ae-toolkit/scripts/install_target.py --host vscode --workspace .
```

The installer reports whether the safety gate refuses a command it must refuse. If that line says FAILED, stop there: the remaining checks mean nothing without it.

**In Cursor**, after installing as above:

1. Customize lists the toolkit's skills, rules, commands, and hooks.
2. `/ae-doctor` reports every gate check as passing.
3. Ask the agent to run `psql -c "drop table orders"`. The hook must deny it.

**In VS Code**, open the scratch repository and confirm four things:

1. **Chat: Open Customizations** lists the twenty-five skills, four agents, and eighteen prompts. A skill that loaded is present here; a skill that failed to load is silently absent, so a short list is the failure signal.
2. Right-click the Chat view and select **Diagnostics**. It should report no load errors.
3. Type `/` in chat. The skills and prompts should appear as slash commands; run `/ae-learn` against a dbt project and confirm it reports conventions rather than asking you to describe them.
4. Ask the agent to run `psql -c "drop table orders"`. The hook must deny it. This is the check that matters most, because it is the one that fails silently if the hook is misconfigured.

**In Antigravity**, repeat with `--host antigravity`, then confirm the skills appear, run `/hooks` in the CLI to see `ae-toolkit-safety` registered, and repeat the destructive-command check. Do that last check **from a subdirectory** as well as from the repository root: Antigravity resolves relative hook paths against the session directory, and a hook that fails to launch does not block the call. The installer writes absolute paths to prevent this, and a subdirectory session is what would expose a regression.
