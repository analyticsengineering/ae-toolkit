---
name: semantic-layer
description: Implements or reviews MetricFlow and dbt semantic-layer artifacts when that stack is detected in the repository. Use for semantic models, entities, dimensions, measures, metrics, or saved queries after a canonical metric contract exists; it does not introduce dbt Semantic Layer into projects that do not already use it.
---

# Semantic Layer

Implement or review repository-native MetricFlow/dbt semantic artifacts. Business meaning comes from an approved metric contract, not from YAML.

## When to use

- Review or author dbt semantic models, entities, dimensions, measures, metrics, and saved queries supported by the detected project version.
- Diagnose static definition, grain, join, time, or metric-contract mismatches in an existing MetricFlow/dbt stack.
- Use only when local repository evidence detects this stack.
- If no MetricFlow/dbt semantic layer is detected, report that fact and stop; do not introduce one or substitute another vendor.

## Mode and prerequisites

Default silently to **Work** mode. Use **Learn** only when teaching is requested and **Assessment** only when evaluation without answers is requested or `.ae/exercise.json` requires it.

Require or mark missing:

- Canonical metric contract, owner, consumers, and acceptance cases.
- Project root, dbt version evidence, package/configuration files, and semantic artifact locations.
- Model grains, keys, relationships, time dimensions, measures, and downstream consumers.

## Detection and convention procedure

1. Read `.ae/exercise.json` and `.ae/project.yml` when present.
2. Build a current local inventory of `dbt_project.yml`, dependency files, semantic YAML, `manifest.json`, and `semantic_manifest.json`. An artifact not opened in this workflow is not evidence.
3. Detect MetricFlow/dbt use from repository configuration or existing semantic resources. File names or a generic `metrics` directory alone are insufficient.
4. Infer resource syntax, property names, YAML placement, naming, entity types, time granularity, package boundaries, and version conventions from detected local files and version evidence.
5. Treat conflicting or absent syntax evidence as an unknown. Never invent a schema based on a remembered dbt or MetricFlow release.
6. Trace the canonical contract to physical models, confirming model grain, entity keys, relationships, time spine/time dimensions, measure aggregation, filters, and valid dimensions.
7. Search for duplicate metric names and calculations in dbt, semantic, and BI artifacts. Report duplicate authority rather than reconciling it silently.
8. Author the smallest repository-native artifact set or review the submitted set against the checks below.

## Semantic checks

- **Grain and entities:** each semantic model has an evidenced row grain; entity roles and keys support intended joins.
- **Measures:** aggregation behavior, non-additive dimensions, units, nulls, and expression inputs match the contract.
- **Metrics:** type, inputs, filters, windows, offsets, time behavior, and zero-denominator handling match canonical semantics.
- **Dimensions:** types, valid values, time configuration, and exposure of sensitive attributes are intentional.
- **Joins:** entity paths do not permit fanout, ambiguous routes, or unintended many-to-many aggregation.
- **Version fit:** every property is supported by the repository's evidenced dbt/MetricFlow version.
- **Consumers:** saved queries and downstream BI references preserve filters, dimensions, and time semantics.

## Evidence required

Cite each inspected file, resource name, model expression, contract clause, and artifact metadata used. Label compiled artifacts as stale or unmatched when recency cannot be established. Static configuration establishes intent, not successful parsing, queryability, or current warehouse values.

Every actionable finding includes **Evidence**, **Risk**, **Recommendation**, and **Verification**, plus severity and confidence from `references/severity-model.md`.

## Failure modes

- Introducing MetricFlow/dbt because a semantic layer sounds desirable.
- Translating an ambiguous KPI directly into semantic YAML.
- Assuming current syntax, defaults, supported metric types, or calendar behavior.
- Treating an entity declaration as proof of key uniqueness or join cardinality.
- Defining the same metric independently in semantic and BI layers.
- Claiming successful parsing or runtime results without current local evidence.
- Exposing protected dimensions through broadly accessible metrics or saved queries.

## Output contract

Return `# dbt Semantic Layer` with: Detection evidence; Contract alignment; Semantic models; Entities and joins; Dimensions and time; Measures; Metrics; Saved queries/consumers; Findings; Proposed artifacts or changes; Unknowns; Verification plan.

For implementation, show the intended file paths and concise artifact content. For review, lead with supported findings ordered by severity. If the stack is not detected, return `NOT DETECTED` with the searched scope and do not produce speculative YAML.

## Verification

- Compare every measure and metric field to the canonical contract and acceptance cases.
- Confirm resource names and properties against the detected local version and existing examples.
- Walk one normal join and one fanout or boundary scenario per critical metric.
- Search models, semantic artifacts, exposures, and BI files for duplicate definitions and downstream references.
- Propose exact targeted parse or semantic validation commands only as a user-run verification plan; do not execute them.

## Safety and repository writes

- Local Basic only: use local files and user-provided material. Never call MCP, access a warehouse, execute dbt, install packages, or contact dbt services.
- Never print profiles, credentials, compiled sensitive SQL, or sampled protected data.
- New files may be created only when requested. Before editing or deleting any existing file, show the exact proposed change, state blast radius across models, tests, exposures, metrics, saved queries, and BI artifacts, and obtain explicit approval.
- Do not claim runtime validity, data correctness, or availability from static semantic configuration.
