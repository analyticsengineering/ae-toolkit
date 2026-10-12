# dbt compatibility

AE Toolkit reads dbt projects and artifacts; it does not bundle or run dbt. This page states what works on dbt v1 (Core) and dbt v2 (formerly Fusion), and how each claim is backed.

**How support is established.** Every row marked supported is exercised by the test suite against fixture projects in `tests/fixtures/dbt/`. The dbt v2 fixtures are synthetic: they are modeled on dbt's published documentation and artifact schemas, not captured from a live dbt v2 run. Where dbt has not published a schema, the toolkit recognizes the file and says it is not interpreted rather than guessing at its structure.

| Status | Meaning |
| --- | --- |
| Supported | Implemented and covered by tests. |
| Partially supported | Some of the feature is handled; the row says which part. |
| Not applicable | The feature does not exist on that engine. |
| Not yet supported | Exists in dbt; the toolkit does not handle it yet. |

## Matrix

| Capability | dbt v1 | dbt v2 | Notes |
| --- | --- | --- | --- |
| Static project inspection | Supported | Supported | `dbt_project.yml`, models, YAML, configured paths. |
| Engine detection | Supported | Supported | From `.ae/project.yml`, dependency pins (`dbt-core`, `dbt`, `dbt-oss`, `dbt-fusion`), `require-dbt-version`, then the version recorded in existing artifacts. Conflicting evidence is reported as unknown. |
| `manifest.json` | Supported | Supported | dbt v2 writes the same v12 manifest schema. |
| `run_results.json` statuses | Supported | Supported | Includes `reused`, and clone or lag-tolerance successes under dbt State, reported as not executed. |
| `sources.json` from `dbt source freshness` | Supported | Supported | Planned freshness checks use this command on both engines. |
| `freshness.json` from `dbt freshness` | Not applicable | Partially supported | Recognized and tied to its invocation; contents are not interpreted because dbt publishes no schema for it. |
| `--no-write-json` and `write_json` | Supported | Supported | From the command, `DBT_ENGINE_WRITE_JSON` / `DBT_WRITE_JSON`, or `flags.write_json`. Results are reported as not written instead of reading an earlier run's files, and planned steps add `--write-json` when the project turns it off. |
| Information Schema | Not applicable | Partially supported | Detects generated files under `target/info_schema/` and the declared `info_schema.version`. The Parquet files are not read; queries go through `dbt show --info`. |
| `dbt show --info <view>` | Not applicable | Supported | Allowed without approval as a local metadata read. `--inline`, `--select`, `--target`, or any other flag on `show` requires approval. |
| Checks (`checks/`, `dbt check`) | Not applicable | Partially supported | Check files under `check-paths` are found and `dbt check` runs without approval. Check results are not interpreted yet. |
| Static analysis mode | Not applicable | Partially supported | Reads `--static-analysis`, `DBT_STATIC_ANALYSIS`, and settings in `dbt_project.yml`. Overrides in model YAML or SQL `config()` blocks are not read. |
| Column-level lineage | Not applicable | Partially supported | Never inferred from configuration. Used only from `dbt show --info column_lineage` output, and only for models dbt analyzed in strict mode. |
| dbt State (`manage_state`) | Not applicable | Supported | Detected from the command, `DBT_ENGINE_MANAGE_STATE`, or `flags.manage_state`; changes how results are read. `dbt state explain` requires approval because it consults dbt platform. |
| `dbt login` | Not applicable | Supported | Requires approval; it opens a browser and stores credentials. |
| Command approval for every dbt name | Supported | Supported | `dbt`, `dbtf`, `python -m dbt`, and dbt launched through `uv`, `pipx`, `conda`, and similar runners receive the same decision. |
| dbt MCP server | Supported | Supported | Tools that execute against the warehouse or dbt platform (`build`, `run`, `test`, `show`, `compile`, `execute_sql`, `query_metrics`, codegen, job triggers) require approval, as their shell forms do; an unrecognised dbt tool also asks; metadata tools pass. |
| Planned validation commands | Supported | Supported | Use only flags valid on both engines (`--select`, `--log-format-file`, `--log-path`); tested to avoid the flags dbt v2 deprecates. |
| Setting the invocation ID (`--invocation-id`) | Not applicable | Not yet supported | The invocation is recovered from the command's JSON log on both engines. |
| OpenTelemetry traces and logs | Not applicable | Not yet supported | Not read. Nothing is exported. |
| `dbt lint` | Not applicable | Not yet supported | Runs without approval; its findings are not interpreted. |

## Differences to keep in mind on dbt v2

- **Driver downloads.** dbt v2 adapters can download database drivers on first use. A command the toolkit treats as local, such as `dbt parse`, may make that one-time download. The toolkit itself makes no network calls.
- **Strict static analysis contacts the warehouse.** It downloads source schemas and needs `dbt login`. A run without credentials falls back to baseline, so a `strict` setting is not proof that strict analysis ran.
- **Reused results.** With dbt State, a passing status can describe an earlier run against identical inputs. Results list these nodes under `not_executed`, and they are never counted as evidence for the current change.
- **Stale artifacts after an upgrade.** A project that moved to dbt v2 may still hold artifacts written by dbt v1. Capability reports point this out.

## Checking a project

```bash
python3 scripts/dbt_capabilities.py path/to/project --pretty
```

The report lists each capability with its state, the basis for it (`command`, `environment`, `declared`, `observed`, `inferred`, or `default`), and the evidence. It reads files only. Environment values are those of the shell that runs it, which may differ from where dbt runs.
