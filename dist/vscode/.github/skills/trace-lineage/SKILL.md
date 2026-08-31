---
name: trace-lineage
description: Traces a column, metric, or business figure through models and BI artifacts to its source, and explains what it actually measures. Use when asked where a number comes from, what a metric means, what depends on a field, or why two reports disagree.
---

# Trace Lineage

Follow a figure from where it is consumed back to where it is produced, then explain in business terms what it actually measures.

## When to use

- Answer where a column, metric, or dashboard number comes from.
- Establish what a metric means before changing, reusing, or deprecating it.
- Find everything that depends on a field ahead of a rename or migration.
- Explain why two reports that claim the same metric disagree.
- Do not use this skill to assert warehouse values. It traces definitions, not data.

## Required context

Obtain:

- The figure to trace, and where the requester met it: a model column, a BI field, a metric, or a number in a report.
- The project root and any BI or semantic-layer directories inside it.

Default silently to Work mode and deliver the chain and its risks. In Learn mode, explain each transformation as it is traversed. In Assessment mode, evaluate a submitted trace without completing it.

## Trace procedure

1. Locate every definition of the name. A figure defined in more than one place is the finding, not an inconvenience to resolve by picking one.
2. Walk upstream through `ref` and `source` calls, recording at each hop the expression that produces the figure, the filters applied, and the join that carries it.
3. Stop at sources, and name the source table and the loader rather than speculating about the system behind it.
4. Walk downstream from the definition to every model, test, exposure, metric, and BI artifact that consumes it, and report the count with the files.
5. Reconstruct the business definition from the accumulated expressions and filters, including every predicate that narrows the population, not only the arithmetic.
6. Run the semantic checks below across the whole chain, not hop by hop, because these defects appear only when two hops are compared.
7. Separate what the files establish from what only a warehouse could confirm, and label the second group plainly.

## Semantic checks

Apply each of these to the assembled chain:

- **Inconsistent time anchors.** Two facts combined into one figure but anchored to different timestamps, such as a refund joined by the date it was processed against revenue anchored to the date its order was created, misattribute value across periods. The totals still reconcile in the aggregate, which is exactly why this survives review.
- **Population drift.** A filter applied at one hop and absent at another, so the figure means different things at different depths.
- **Duplicate definitions.** The same business name computed in more than one model or BI artifact, with expressions that are not identical.
- **Grain change mid-chain.** A join that multiplies rows before an aggregation, inflating a measure carried from the coarser side.
- **Unit and currency drift.** Amounts combined across differing units, scales, or currencies without conversion.
- **Null and default handling.** A hop that converts absent values to zero, or filters them out, changing what an average or a rate reports.

## Failure modes

- Reporting the first definition found while a second definition exists elsewhere.
- Reading a column description as the definition instead of the expression that computes it.
- Describing the implementation rather than the meaning, so the explanation restates the SQL.
- Presenting a compiled or remembered lineage graph as if the files had been read.
- Claiming a downstream consumer count without listing what was searched and what was excluded.
- Treating a BI artifact's label as evidence of the calculation behind it.

## Evidence required

Every hop cites a file and the expression at that hop. The consumer count states what was searched, including which directories and file types, and what could not be searched. The business definition is traceable to specific predicates and expressions. Anything inferred from a name rather than an expression is labeled as such.

## Output contract

Return `# Lineage Trace` with: What it measures; Definition site; Calculation chain; Upstream sources; Downstream consumers; Semantic risks; What the files cannot confirm.

State the business definition first, in one or two sentences a stakeholder would understand, before any SQL appears.

## Verification

- Confirm each hop by reading the file, not by inference from the model's name.
- Search for the name across models, macros, tests, exposures, metrics, semantic models, and BI artifacts before reporting a consumer count.
- Confirm that a claimed single definition is single by searching for the expression as well as the name.
- Re-read the assembled chain end to end before asserting what the figure measures.

## Safety/privacy

- Static tracing only. Never execute dbt, query a warehouse, or call MCP to complete a trace.
- Never print credentials, connection strings, or sampled row values encountered along the chain.
- A trace reads files and writes none. Any repair it suggests is a separate, approved change.

## What not to assume

Do not assume one definition exists because one was found, that a name means the same thing at every hop, that a dashboard label matches its underlying expression, that undocumented filters are unintentional, that a source table is the system of record, or that agreeing totals imply agreeing definitions.
