# Warehouse and Tooling Portability

Analytics teams run on different warehouses, transformation tools, and BI layers. This toolkit is not written for one of them. The governing rule is the same one that governs naming and testing: the repository decides, and you read it before you write.

## Identify the platform before writing SQL

`scripts/infer_conventions.py` reports `adapter` and `adapter_source`, and it draws on more than one signal because most repositories do not commit `profiles.yml`:

1. `profiles.yml`, when a project happens to ship one.
2. A pinned adapter package in `requirements.txt`, `pyproject.toml`, or `setup.py`, such as `dbt-snowflake` or `dbt-bigquery`.
3. Configuration keys only one warehouse accepts, such as `snowflake_warehouse`, `partition_by` with `cluster_by`, or `file_format: delta`.

Two pinned adapters yield no answer rather than a guess, because a monorepo can hold projects for different warehouses. When the adapter is unknown, say so and write SQL that holds anywhere, rather than assuming the warehouse you have seen most often.

## Prefer the construct the repository already uses

The strongest dialect evidence is the project's own SQL. Before introducing a function, look for it in the existing models. A construct that appears nowhere in a repository is a claim you are making about the platform, and it is the claim most likely to be wrong.

This matters most where warehouses diverge quietly:

- **Surrogate keys.** `md5` is not available everywhere, and BigQuery teams typically reach for `farm_fingerprint` or `to_hex(md5(...))`. Use the macro or package the project already uses, and never introduce a hashing implementation absent from the repository.
- **Deduplication.** Snowflake, BigQuery, and Databricks support `QUALIFY`; Postgres and Redshift do not, and there the same intent is written as a subquery filtered on a window function.
- **Identifier case.** Snowflake folds unquoted identifiers to upper case, and many Snowflake projects name models and columns in caps as a result. That is a convention, not shouting. Match the case the repository uses rather than normalising it.
- **Semi-structured access.** Snowflake's `payload:field::type`, BigQuery's `STRUCT` and `UNNEST`, and Databricks' `explode` solve the same problem with incompatible syntax.
- **Incremental strategy.** `merge`, `insert_overwrite`, `delete+insert`, and `append` are not equally supported, and the right one depends on both the warehouse and the model's grain. Follow the strategy the project's other incremental models use.
- **Type names.** `NUMBER`, `NUMERIC`, `DECIMAL`, `STRING`, `VARCHAR`, and `TEXT` are not interchangeable across platforms.

## Inherited configuration is platform configuration

A directory's block in `dbt_project.yml` applies to every model placed in it, and those blocks are where platform settings live: `partition_by` and `cluster_by` on BigQuery, `dist` and `sort` on Redshift, `file_format` and `liquid_clustered_by` on Databricks, `snowflake_warehouse` and `transient` on Snowflake.

A new model inherits all of it. That is usually what you want, and occasionally it is broken in a way that only fails at run time: a dimension written beside a partitioned event fact inherits a partition on a date column the dimension does not have. Overriding the materialization does not clear the rest of the block. Read the directory's block, confirm every column it names exists in the model you wrote, and override explicitly what does not fit.

## Transformation tools other than dbt

Most of this toolkit's inspectors read dbt projects, and they say so when a project is not one. dbt is not the only option: SQLMesh, Dataform, and plain scheduled SQL all appear in production.

When the project is not dbt, do not describe it as one. The analytical reasoning still applies in full, because grain, keys, fanout, null semantics, time anchors, and test coverage are properties of the data rather than of the tool. What changes is where conventions live and what artifacts exist. Read the project's own configuration, state which tool it uses, and do not report dbt concepts such as `ref`, sources, or `schema.yml` as if they were present.

## BI and semantic layers

The cross-layer question, where a number comes from and whether the same name means the same thing at every hop, matters more than any single BI vendor. LookML, dbt semantic models and metrics, Cube, Tableau, and Power BI all define measures above the warehouse, and all can define one that disagrees with the model beneath it.

Treat a BI artifact as another hop in the chain. A measure's label is not evidence of its expression, a filter applied in the BI layer is part of the definition, and a metric defined in two layers is a duplicate definition to report rather than a detail to reconcile silently. When a BI directory exists but you cannot parse a format, name the files you could not read rather than reporting a consumer count that quietly excludes them.
