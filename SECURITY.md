# Security Policy

## Supported versions

Security fixes are provided for the latest release and are not backported. Users should reproduce a report against the latest version before filing when practical.

## Report a vulnerability

Do not open a public issue for an unpatched vulnerability or include secrets, credentials, exploit payloads, private repository content, learner submissions, or production data in a public report.

Email **eric@analyticsengineering.com** with:

- a concise description and potential impact;
- affected version, component, and environment;
- minimal reproduction steps or a proof of concept;
- relevant logs with secrets and personal data removed;
- whether the issue is already public or actively exploited;
- a safe way to contact you.

Use the subject `Analytics Engineering Toolkit security report`. If email cannot safely carry the report, ask for a secure transfer method before sending sensitive details.

The maintainers will validate the report, determine scope and severity, and coordinate a fix and disclosure. Response and remediation time depend on severity and reproducibility; this policy does not promise a fixed bounty or timeline. Please allow a reasonable remediation window before public disclosure. The maintainers will credit reporters when requested and legally permitted.

Good-faith research that avoids privacy violations, service disruption, data destruction, persistence, social engineering, and access beyond the minimum needed to demonstrate the issue is welcome. This is not authorization to test systems or data you do not own or have permission to assess.

## Security boundary

Analytics Engineering Toolkit is a Cursor Plugin made of instructions, configuration, and deterministic safety hooks. It is not a sandbox. Cursor, the operating system, selected model provider, shell, database client, Git host, and any MCP server you add each have separate trust and security boundaries.

The toolkit ships no server and configures no MCP server. Nothing in it opens a network connection.

## Database safety posture

V1 is analysis-first and does not support production database mutation:

- `DROP` and `TRUNCATE` are denied.
- `INSERT`, `UPDATE`, `DELETE`, `MERGE`, and `ALTER` are denied.
- a single `SELECT` or `EXPLAIN` is the only statement class a recognized database client may be approved to run; every other class, and every invocation carrying more than one statement, is denied. `SELECT ... INTO` is classified as a write, because it creates a relation on Postgres and T-SQL and a file on MySQL;
- that classification is syntactic, and it establishes eligibility for approval rather than absence of effect. A single well-formed `SELECT` can still call a function that writes, so the human reading the statement before approving it is the control for semantics, not the gate;
- recognized database-client `SELECT` and `EXPLAIN` operations require explicit approval and confirmation that the target is an approved local or development environment;
- dbt commands that may execute warehouse queries require explicit approval and target review, whichever name launches dbt (`dbt`, `dbtf`, `python -m dbt`) and whatever runner or environment assignment precedes it;
- generated SQL is a proposal for human review, never authorization to execute;
- dbt MCP tools that execute against the warehouse or change state on the dbt platform are held for approval the same way, and an unrecognised dbt MCP tool is held rather than assumed safe;
- Learn, Assessment, and connected work do not weaken these restrictions.

The shell safety gate also denies selected destructive filesystem and Git operations. Pattern-based classification is defense in depth: commands can be encoded, wrapped, aliased, or otherwise evade or falsely trigger a pattern. A command reached through `make`, a script file, or a shell alias is opaque to it. Always inspect commands, use least-privilege credentials, restrict network access, and rely on warehouse permissions and environment separation as primary controls.

## Connected-action safety

MCP actions and data transfer must be previewed and explicitly approved. Installing the plugin, enabling an MCP server, selecting Assessment mode, or opening `.ae/exercise.json` is not approval. Scope approval to one destination, operation, and payload; ask again when any of those changes.

If a service you configured is missing, unreachable, or does not expose a requested capability, fail closed for that action and continue only with clearly labeled local guidance. Never fabricate a server response, and never present a local self-check as an official grade or submission receipt.

## Credentials and sensitive data

- Never commit or paste credentials into plugin files, prompts, examples, issues, or reports.
- Configure service credentials through the supported Cursor or service mechanism.
- Prefer read-only, least-privilege, short-lived, non-production credentials.
- Redact secrets, protected identifiers, and row-level data from logs and findings.
- Treat repository content, database metadata, course submissions, and generated artifacts as potentially sensitive.
- Rotate any credential that may have been exposed.

See [PRIVACY.md](PRIVACY.md) for the data-transfer and telemetry policy.

## Dependency and update hygiene

Review plugin changes before updating a local installation. Validate `.cursor-plugin/plugin.json`, hooks, MCP configuration, and executable scripts. Marketplace review is an additional control, not a substitute for local review. Pin or verify dependencies where the plugin introduces them, and do not run utility scripts with elevated privileges.

## Disclosure and release handling

Security fixes should:

1. add a regression test when safe;
2. preserve fail-closed behavior at destructive and connected boundaries;
3. document user-visible impact and upgrade guidance in `CHANGELOG.md`;
4. avoid publishing exploit detail until affected users have a reasonable opportunity to update.
