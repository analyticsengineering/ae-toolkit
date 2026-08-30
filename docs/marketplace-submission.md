# Cursor Marketplace submission

This checklist follows Cursor's current official plugin documentation:

- [Plugins](https://cursor.com/docs/plugins)
- [Plugins reference](https://cursor.com/docs/reference/plugins)
- [Customize Cursor](https://cursor.com/docs/customize-cursor)
- [Marketplace publishing form](https://cursor.com/marketplace/publish)

## 1. Validate the Cursor Plugin

The plugin root must contain a valid Cursor Plugin manifest at:

```text
.cursor-plugin/plugin.json
```

Before submission, confirm:

- `name` is unique, lowercase, and kebab-case;
- `description` clearly states the plugin's purpose;
- `version` is valid semantic versioning;
- every declared component path is relative, exists, and contains no `..`;
- skill, rule, agent, command, hook, and MCP files use the current supported formats;
- every plugin variable referenced as `${VAR}` is declared in the manifest schema;
- `README.md` explains installation, use, configuration, privacy, safety, and limitations;
- connected capabilities are not claimed as available unless the separately operated endpoint implements them.

Use the `.cursor-plugin/plugin.json` format for this project. A root `plugin.json` is the separate Agent Plugins format and should not replace this Cursor Plugin manifest.

Cursor documents `.cursor-plugin/marketplace.json` for repositories that distribute multiple plugins. Analytics Engineering Toolkit is one plugin, so it does not include that multi-plugin manifest. This repository already places `.cursor-plugin/plugin.json` at its root, which is the required layout.

## 2. Host it in a public Git repository

The plugin lives at `https://github.com/analyticsengineering/ae-toolkit`. Marketplace plugins are distributed from Git repositories and must be open source, so confirm the repository visibility is public before submitting.

Note that the repository name (`ae-toolkit`) intentionally differs from the plugin name (`analytics-engineering-toolkit`). Cursor identifies the plugin by the manifest `name`, not the repository name.

An optional logo may be committed to the repository and referenced by relative path from the manifest, for example:

```json
{
  "logo": "assets/logo.svg"
}
```

Cursor's reference recommends committing the logo to the repository. Confirm that its path and case are correct.

## 3. Test under `~/.cursor/plugins/local`

Cursor's documented local-test location is:

```text
~/.cursor/plugins/local/analytics-engineering-toolkit
```

Install a real directory:

```bash
mkdir -p ~/.cursor/plugins/local
rsync -a --exclude '.git' /path/to/ae-toolkit/ \
  ~/.cursor/plugins/local/analytics-engineering-toolkit/
```

Do not use a symlink here, despite Cursor's documentation suggesting one. Cursor 3.8.11 rejects a local plugin whose symlink target lies outside the plugins folder, and it does so silently: the plugin never loads, and the reload still reports `failures=0`. Verify the install in the **Cursor Plugins** output channel and expect `1 plugins loaded`, not the summary line.

The resulting manifest path must be:

```text
~/.cursor/plugins/local/analytics-engineering-toolkit/.cursor-plugin/plugin.json
```

If the destination exists, inspect it before replacing it. A marketplace install with the same plugin name takes precedence over the local copy.

## 4. Reload and verify in Customize

1. Restart Cursor, or run **Developer: Reload Window**.
2. Open **Customize** from the Cursor sidebar.
3. Confirm the plugin appears.
4. Confirm the expected rules, skills, agents, commands, hooks, and MCP server are discovered.
5. Run all nine free workflows with the optional MCP endpoint disabled.
6. Confirm unavailable connected tools fail clearly and local workflows continue.
7. Confirm destructive database statements are denied and approved read-only operations still ask for target confirmation.

Cursor loads local plugins only when local imports are allowed. On Teams and Enterprise, administrators control **Allow Local Plugin Imports** under **Dashboard → Settings → Security & Identity → Marketplace and Plugins**; Cursor documents that this setting is off by default on Enterprise.

## 5. Submit the repository URL

Open [https://cursor.com/marketplace/publish](https://cursor.com/marketplace/publish) and submit the **public repository URL**.

Cursor manually reviews every marketplace plugin before listing it. Submission is a review request, not immediate publication. Be prepared to address validation, security, documentation, branding, or functionality feedback and to submit an updated repository revision.

## Final submission checklist

Most of this list is enforced by `tests/run_tests.py` and by CI rather than by reading, so an item is checked here when something fails when it stops being true. The unchecked items are the ones no test can reach, because they need the Cursor application or a person.

- [x] Public Git repository is accessible without authentication. Verified by an anonymous shallow clone that produced both the manifest and the logo.
- [x] `.cursor-plugin/plugin.json` is present and valid.
- [x] Plugin `name` is lowercase and kebab-case. Uniqueness is decided by the marketplace and cannot be confirmed before review.
- [x] Description accurately identifies Analytics Engineering Toolkit.
- [x] Version and MIT license metadata are correct, and the manifest version matches the newest closed changelog section.
- [x] All component files and frontmatter are valid.
- [x] All manifest paths are relative, valid, and contained in the plugin.
- [x] Optional logo is committed and referenced by a valid relative path.
- [x] README documents configuration and usage.
- [x] Privacy policy states zero V1 anonymous telemetry and exact opt-in connected data classes. A test asserts no shipped hook or script can import a networking module, so the claim fails loudly rather than quietly.
- [x] Security policy documents disclosure and destructive database posture.
- [x] Nine free workflows have no dependency on the remote MCP service; the public contract suite checks that their command boundaries remain explicitly local-only.
- [x] Connected features are labeled conditional; the repository does not imply that configuration equals implementation.
- [x] No credentials, tokens, private data, production rows, or learner submissions are committed.
- [x] Offline and unavailable-server behavior was tested.
- [x] Hook and unit tests pass.
- [ ] Local test completed under `~/.cursor/plugins/local`. **Needs the application.** Follow [Install locally](../README.md#install-locally).
- [ ] Cursor was reloaded and all expected components were checked in Customize. **Needs the application.** Expect twelve skills, four agents, sixteen commands, three rules, the hook configuration, and one MCP server; a component that fails to load is absent rather than reported, so a short list is the signal.
- [ ] Repository URL was submitted at [cursor.com/marketplace/publish](https://cursor.com/marketplace/publish). **Needs a person**, since submission is a web form.
- [ ] Manual review feedback is tracked and resolved before release.

## Release evidence

Record the tested commit SHA, Cursor version, operating system, test output, Customize component inventory, and reviewer notes in the release process. Do not include secrets, user data, raw warehouse rows, or real course submissions in evidence.
