---
name: bi-model
description: Implements or reviews an existing repository's BI semantic model, including LookML or another detected vendor's measures, dimensions, joins, filters, and access rules. Use when BI-layer logic must align with canonical metrics and warehouse models; it detects the vendor and never assumes Looker or invents unsupported syntax.
---

# BI Model

Implement or review the semantic logic already used by the repository's BI platform. Treat BI calculations and filters as part of metric lineage, not presentation-only details.

## When to use

- Review or author LookML when Looker evidence is present.
- Review or author another BI semantic format only when its repository artifacts and conventions are detected.
- Align BI measures, dimensions, joins, filters, time behavior, and access rules with canonical contracts and model grain.
- Do not use for dbt/MetricFlow semantic artifacts; use the semantic-layer workflow for those.

## Mode and prerequisites

Default silently to **Work** mode. Use **Learn** only when teaching is requested and **Assessment** only when evaluation without answers is requested or `.ae/exercise.json` requires it.

Require or mark missing:

- Canonical metric contract and acceptance cases.
- BI project root, local configuration, vendor evidence, version or dialect evidence, and existing examples.
- Upstream model grains, keys, relationships, field types, ownership, and intended consumers.

## Detection and convention procedure

1. Read `.ae/exercise.json` and `.ae/project.yml` when present.
2. Inventory local BI directories, project/configuration files, model/view/dataset definitions, generated metadata, and downstream references.
3. Identify the vendor from explicit repository evidence. Detect LookML from Looker project artifacts, not from the request's generic use of “BI model.”
4. Infer file placement, naming, includes/imports, refinement or inheritance patterns, formatting, join syntax, measure types, time groups, access controls, and validation conventions from local examples.
5. If vendor or syntax evidence is split or absent, report the candidates and stop before authoring vendor syntax.
6. Trace each requested field or metric from its canonical contract through upstream model expressions into the BI definition.
7. Map all joins, relationship declarations, hidden filters, default filters, access filters, and aggregate-awareness behavior that can alter results.
8. Author the smallest native change or review the submitted artifacts using the checks below.

## BI semantic checks

- **Measures:** formula, population, aggregation, units, nulls, distinctness, and non-additive behavior match the contract.
- **Dimensions:** source expression, type, labels, groups, allowed values, time zone, and privacy exposure are intentional.
- **Joins:** keys, relationship/cardinality declarations, required joins, and fanout controls match observed model grain.
- **Scope:** explores/datasets and included fields support intended questions without exposing unsafe join paths.
- **Filters:** hidden, default, always-on, row-level, and access filters are included in the business meaning.
- **Reuse:** extensions, refinements, shared views, and aliases do not create divergent duplicate definitions.
- **Portability:** syntax and features are supported by the detected vendor and repository version.

## Evidence required

Cite the BI config, each definition file, upstream model expression, canonical contract clause, and consumer reference used. Labels and relationship declarations are intent, not proof of formulas, key uniqueness, or cardinality. Name unsupported or unreadable file formats and exclude them explicitly from consumer counts.

Every actionable finding includes **Evidence**, **Risk**, **Recommendation**, and **Verification**, plus severity and confidence from `references/severity-model.md`.

## Failure modes

- Assuming Looker, Tableau, Power BI, Cube, or another vendor without repository evidence.
- Copying syntax from a different vendor or version.
- Treating a display label as the metric definition.
- Declaring a many-to-one relationship without grain or key evidence.
- Ignoring filters, time zones, symmetric-aggregate behavior, access rules, or hidden fields.
- Reimplementing a metric in BI when an authoritative reusable definition already exists.
- Claiming validation, query results, or deployed behavior from static files.

## Output contract

Return `# BI Model` with: Detected platform and evidence; Canonical contract alignment; Upstream grain; Measures; Dimensions; Joins and fanout; Filters and access; Reuse and duplicate definitions; Findings; Proposed artifacts or changes; Unknowns; Verification plan.

For implementation, show intended paths and concise native definitions. For review, lead with findings ordered by severity. If no BI platform is detected, return `NOT DETECTED` with searched paths and do not produce speculative vendor code.

## Verification

- Walk one normal query path and one fanout or boundary scenario for each critical measure.
- Compare formulas, filters, units, and time semantics with the canonical contract.
- Confirm every construct against detected local examples and version evidence.
- Search BI, semantic, model, test, and exposure files for duplicate definitions and downstream references.
- Propose vendor validation steps as a user-run plan only; do not contact the platform or execute queries.

## Safety and repository writes

- Local Basic only: use local files and user-provided material. Never call MCP, access a warehouse, execute dbt, or contact a BI service.
- Minimize field exposure and never print credentials, connection settings, raw personal data, or protected values.
- New files may be created only when requested. Before editing or deleting any existing file, show the exact proposed change, state blast radius across upstream models, tests, exposures, shared BI objects, dashboards, and downstream consumers, and obtain explicit approval.
- Flag row-level security or access-filter changes as potentially broad disclosure risks.
