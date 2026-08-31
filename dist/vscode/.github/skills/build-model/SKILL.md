---
name: build-model
description: Builds a new dbt model from existing upstream models, following the repository's own naming, key, testing, documentation, and SQL conventions. Use when creating a staging, intermediate, fact, or dimension model, or when adding its tests and documentation.
---

# Build Model

Produce the model a teammate familiar with this repository would have written. Infer everything the repository states; ask only about grain and business meaning.

## When to use

- Create a staging, intermediate, fact, or dimension model from named upstream models or sources.
- Add the surrogate key, documentation, and tests that this repository would expect alongside a new model.
- Do not use this skill to design a warehouse from nothing, or to guess at columns that no upstream model exposes.

## Required context

Obtain:

- The target model's purpose and the upstream models or sources it draws from.
- The convention profile, from `.ae/project.yml` or fresh inference.

Default silently to Work mode and build the model. In Learn mode, explain each modeling decision as it is made. In Assessment mode, evaluate a submitted model without writing or repairing it.

## Build procedure

1. Establish the convention profile before naming anything. Prefixes, directories, surrogate key implementation, YAML strategy, test defaults, and SQL style all come from the repository, not from a question.
2. Inspect every named upstream model: its SQL, its documented columns, its tests, and what it references in turn. A column that no upstream model exposes does not exist, however natural its name.
3. Determine each input's grain from its declared primary key, its uniqueness tests, or its aggregation. Where an input's grain is undeclared and untested, treat it as an assumption and record it.
4. Determine the target grain, and stop here if two grains survive. Derive candidate grains from the keys of the inputs and the join paths between them, then apply the rule below. When the rule says to ask, the build ends at this step and you return the grain decision instead of a model. Do not continue to step 5 with an unresolved grain.
5. Check candidate keys for the target grain. A single column that is unique at the target grain is the key; otherwise the key is the smallest column combination that is, and that combination is what the surrogate key hashes.
6. Identify fanout risk and resolve it in the SQL, not in a caveat. A join from a coarser input to a finer one multiplies the coarser input's rows, so any measure carried from the coarser side is inflated. A warning in prose does not fix a column that a consumer will sum. Choose one: leave the coarser measure out of the finer-grain model and keep it in a model at its own grain, allocate it across the finer rows by an explicit and documented rule, or carry it on exactly one row per coarser key and null it elsewhere. Say which you chose and why. Selecting the coarser measure unchanged alongside a note that it should not be summed is the failure, not the mitigation.
7. Write the model in the repository's SQL style, with CTE structure, comma placement, keyword case, and indent width taken from the profile rather than from preference.
8. Generate the surrogate key with the implementation the repository already uses. Do not introduce a hashing macro or package that the project does not have.
9. Document the model where this repository documents models, following its YAML strategy and filename pattern, and write descriptions in business terms.
10. Add the tests this repository attaches to a primary key, plus relationship tests where the repository uses them, plus any test justified by a specific risk you identified.
11. Validate that every `ref` and `source` resolves to a model or source that exists in this project, and that every column selected exists upstream.
12. Check what the new model inherits. A directory's block in `dbt_project.yml` applies to every model placed there, so a new model silently acquires that materialization and those platform settings. Read the block for the directory you are writing into and confirm each inherited key is valid for the model you built: a partition column must exist in the model, a cluster or sort column must exist, an incremental strategy needs a unique key, and a file format must suit the grain. Override explicitly what does not fit, and say what you overrode and why. Overriding the materialization does not clear the rest of the block, which is the trap: a dimension placed beside a partitioned event fact will still try to partition on a date column it does not have.
13. Report what was created, what needs approval, which conventions were applied, and what remains unverified.

## Determining grain

Grain is the one decision the repository frequently cannot make for you, so treat it deliberately:

- Proceed without asking when a single grain is consistent with both the join path and the requested measures, and say which grain you chose in the output.
- Ask when two grains are genuinely plausible, which typically means a one-to-many join sits between two entities the request could reasonably be about. Present the candidates concretely, one row per order against one row per order item, rather than asking an open question.
- Requested measures often settle it. A measure that is additive only at the coarser grain implies the coarser grain, and building at the finer grain would double count it.
- A model whose grain cannot be stated in a single sentence is not ready to be written.

When two grains survive, asking is the deliverable. Return the grain decision and write no model file. Naming the alternative in a caveat and then building anyway is not asking; it hands over a finished model whose grain the requester never chose, which is the outcome this step exists to prevent.

A request to create the files does not settle the grain. Most requests are phrased as instructions to build, and a column list that spans both a header and its lines is evidence of ambiguity rather than a decision. Stopping to ask one question is the faster path for the requester, because a model built at the wrong grain has to be found, understood, and rebuilt after its numbers have already been quoted.

## Failure modes

- Asking for a naming convention, directory, test set, or SQL style the repository already demonstrates.
- Selecting a column that exists in the request but not in any upstream model.
- Joining a coarser fact to a finer one and carrying the coarser measure through without aggregation, including when a warning about summing it accompanies the unchanged column.
- Treating a request to create files, or a column list spanning two grains, as having settled which grain the model should represent.
- Introducing a surrogate key implementation the project does not use, or hashing a column set that is not unique at the target grain.
- Adding uniqueness tests to a key that the join path cannot guarantee is unique.
- Documenting the implementation rather than the meaning, so the description restates the SQL.
- Writing files into a directory the repository does not use for that layer.
- Accepting a directory's inherited `dbt_project.yml` configuration without checking that its partition, cluster, sort, or incremental settings are valid for the model's own columns.

## Evidence required

Name the grain and the evidence for it. Cite the upstream file and column for every field selected, the test or declaration establishing each input's key, and the convention and its support count for every naming, style, or test decision. State plainly which assumptions are untested.

## Output contract

There are two contracts, and step 4 selects which one applies.

When the grain is resolved, return `# Model Build` with: Changed, including every path; Why, including grain, inputs, keys, and conventions and what ruled the other grain candidate out; Verified, including tests and static reference checks; Remaining uncertainty. Never print `Mode: Work` or internal skill routing.

When two grains survive, return `# Grain Decision Needed` instead, with: The question, naming both candidates as one row per X against one row per Y; What each choice implies for the requested measures, including which become non-additive; Conventions already inferred, with support counts, so the answer does not have to be re-supplied; Inputs and their keys; What will be built once the grain is chosen. Create no model, documentation, or test file in this branch. This is a complete, successful response, not a refusal.

List conventions as applied decisions with their support counts, not as questions. Keep Open risks for assumptions a warehouse query would have to settle.

## Verification

- Confirm every `ref` and `source` names a resource that exists in this project.
- Confirm the surrogate key hashes a column combination that is unique at the stated grain.
- Confirm each selected column exists in the cited upstream model.
- Confirm every column named by an inherited or declared partition, cluster, or sort key exists in the model being written.
- Re-read the generated SQL against the profile's style conventions before finishing.
- Hand the completed scope to `validate-dbt`, which plans the smallest selector and asks before any warehouse-capable command. Building the model itself never runs dbt.

## Safety/privacy

- Static construction only. Never execute dbt, query a warehouse, or call MCP to build a model.
- Creating a new model file, a new documentation file, or a new test file is additive and permitted; report every path created.
- Explicitly requested reversible SQL/YAML/test/documentation edits may proceed without a second approval. Contract changes, renames, deletions, and edits outside the requested scope require preview, blast radius, and approval.
- Never embed credentials, connection strings, or sampled row values in a model or its documentation.

## What not to assume

Do not assume an undeclared key is unique, that an upstream model's grain matches its name, that a one-to-many join is safe, that the requested measures are additive at the chosen grain, that a documented column is populated, or that passing tests upstream imply correctness at the new grain.
