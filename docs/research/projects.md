# Python project workbench

Version 0.6 opens local Python folders without executing them. Flat scripts and `src/` packages use the same project application behind Web, desktop and CLI. [简体中文](projects.zh-CN.md)

## Workflow

1. Start `cdaf studio --project PATH`; open the research folder through **Open folder**.
2. In **运行入口 / Run entries**, choose a candidate or add a script-relative path or dotted module entry. Save arguments, working directory and machine interpreter/environment references. Install a `src/` package in its selected interpreter or explicitly author its import environment; indexing does not repair imports implicitly.
3. Click **运行 / Run**. The selected entry alone runs in a separate process. Expand a file/scope and double-click a variable to view actual saved evidence. A click only selects; use the context menu to open source or enter a scope, and **Back** to return.
4. Configure probes or apply a template. Save, then execute probes or replot explicitly. These actions use the selected run's archived inputs and freeze the newly selected probe configuration; they do not rerun the project entry.

Code shows computation/control/call relationships; Data shows variables and processing relationships. Both start collapsed and query bounded slices. Sources, graphs and evidence are revision-addressed. Old runs never substitute current source for missing archives.

Each effective presentation probe has a separate collapsible view. The default automatic view is a reusable template; disabling it remains effective after reload. Local overrides and project defaults remain separate. Missing exact inputs produce a diagnostic rather than a full-data conclusion.

## Intelligence and changes

Configure a provider-neutral service in model settings, then select that profile in the project assistant. Context preview is inert. Authorized tools retrieve versioned symbols, references, source excerpts and redacted evidence within a task budget; terminal text is excluded by default.

Multi-file proposals show per-file diffs and validation. Acceptance checks all base digests before writing, uses staging/backups/a recovery journal and blocks execution/indexing until recovery completes. Rollback creates a new proposal. Acceptance never runs the scientific code.

## Compatibility

**Single-file workspace** preserves existing definitions, IDs, evidence and scan scope. Opening a directory explicitly opts into project indexing. First project enrollment preserves the original `workbench.yaml.bak`; it never overwrites a previous backup or moves historical runs.

Preview old probe migration with `cdaf --json workbench migrate-config --project PATH`; add `--apply` only after reviewing diagnostics. Archives without project identity remain accessible through the compatibility workspace.

## CLI

`cdaf --json workbench project` provides `open`, `index`, `info`, `entries`, `graph`, `plan`, `run`. Every command accepts `--project PATH`. Save an entries JSON array, freeze a plan with `plan --entry ID`, then execute with `run --plan PLAN_ID`. Interactive `/project` commands use explicit project IDs and receive live run events; batch runs wait and return a nonzero code on failure/cancellation. See [examples](../../examples/research/projects/README.md).

## Limits

Local synchronous Python is the primary supported runtime. Dynamic dispatch, custom loaders, async code and generators retain partial-coverage markers. Third-party internals and spawned processes are not automatically instrumented. Notebook, multiple workspace roots, non-Python parsing and distributed execution are outside this release. Default visible graph slices are bounded at about 350 units with explicit omission counts. Windows installation, other-platform CI and real external model effects are separate acceptance claims.
