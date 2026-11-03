# Scientific Dataflow Inspector project workbench implementation

Goal: implement the user's approved P0-P5 plan, starting from 0.5.4 / 2fe95ff.
The user-approved plan in this conversation is the specification. This document records executable boundaries and decisions, not a reduction in its scope.

## Fixed requirements

- Local Python multi-file projects, script and `python -m` entries, real cross-module observations.
- Existing Web, Electron, CLI, adapters, probes, templates, providers and legacy single-file evidence remain usable.
- Indexing never imports or executes project source. Per-file analysis and revision-addressed sources are reused.
- Stable project/file/logical identities, separate execution instances; historical runs never read current source as their old source.
- Project-relative authored configuration; local interpreter and credential references remain machine-local.
- Explicit project identity in requests, bounded application-wide jobs, no ambient active-project backend state.
- Lazy directory/object/Code/Data graph navigation, one expanded level, no forced navigation on selection.
- Effective probes/templates exclusively determine object presentations; project/selection scopes freeze at planning.
- Task-scoped, versioned, redacted project model tools and reviewed recoverable multi-file changes.
- No notebook execution, multi-language parser, multi-root workspace, distributed execution or child-process auto-tracing in this release.

## Implementation contracts

### P0: baseline

Capture source checkout, existing tests, installed data inventory without mutating user runs. Freeze a multi-file fixture with import side effects, duplicated names, functions, branches and seeded randomness. Compare ordinary execution with observed execution.

### P1: project index

Add a `research/projects` package: models, storage, discovery, resolver and service. Public `ProjectService(root)` exposes `open(path)`, `index(project_id, cancel=None)`, `project(project_id)`, `revision(project_id, revision_id=None)`, `files(project_id, revision_id=None, offset=0, limit=200)`, `analysis(project_id, file_id, revision_id=None)`, `source(project_id, file_id, revision_id=None)`, `graph(project_id, revision_id=None, scope_id=None, view='code', limit=350)`, `entries(project_id)` and `close()`.

Use ResearchProject, SourceUnit, ProjectRevision, RunConfiguration, ProjectPlan and ProjectChangeSet. Index records are per file/edge, not one giant record. Reuse analyze_source. Resolve local imports, aliases, relative imports and finite re-exports, direct calls and argument/return relationships; ambiguous/dynamic targets retain coverage diagnostics. Publish a complete revision atomically. Record parsed/reused counts for incremental acceptance. Retain syntax-error files. Exclude .git/.venv/venv/node_modules/__pycache__/.cdaf/build/dist; prevent outward-link traversal.

### P2: runtime

Script and module modes retain real Python argv/cwd/import/cache/package semantics. Delegate normal imports, wrapping only local, indexed Python source loaders. One TraceSession across all observed files, distinct module and call scopes. Verify each loaded source hash. Module import completion does not finalize function control summaries. Finish all module runtimes at run completion. Expose real project runs, errors, cancellation, run versions and coverage. Application-wide execution budget is four jobs maximum, including legacy jobs.

### P3: API, CLI and workspace

Routes `/api/v1/research/projects/...`, explicit project + revision, 409 conflicts, project-scoped service dispatch; generated TypeScript models. CLI `cdaf workbench project open/index/info/graph/entries/plan/run`. Project tree and per-file objects, source switching/highlighting, Code/Data scoped graphs with boundary relationships, navigation back, lazy layout, selection and probe scopes. Reuse probe library/template/editor and result renderers. Project tasks and terminals do not leak into another project.

### P4: intelligence and changes

Provider-neutral model profiles; bounded project inventory/search/references/source/evidence tools. Read authorization independent from display edges. Digest-bound citations and cache invalidation. Create/edit-only multi-file proposals, complete digest check before applying, backups/staging/journal/recovery, reviewed rollback. Existing format-only AST/comment/order guarantees remain. Actual model request and fixture-only tests are separate evidence.

### P5: migration and release

Legacy single-file projects/IDs/bindings/evidence remain readable without expanding their scan scope. Build Python-only Web distribution and Windows desktop. Validate real installed shortcut/version/start/stop, old data retention and cross-project workflow. Update English/Chinese docs, examples, capabilities and missing coverage.

## Acceptance

Test flat and src layouts, script/module entries, relative/aliased/re-exported/circular imports, same-name symbols, unknown dynamic calls, dependency changes, project relocation, history, stale plans, model scope/citations, multi-file conflict/recovery and template disablement. Compare outputs/exceptions/RNG/evaluation/import counts. Use 100-file and 1000-file/100k-LOC fixtures; selection P95 <50ms; cancellation acknowledged <1s; layout in Worker and visible graph ~350 units. Verify 900/1100/1280/1600 widths and Windows scaling. Run existing Python/frontend/browser/package checks and record actual native/model coverage.

## Execution

Codex owns architecture, frozen acceptance, review and integration. DSH official Flash implements bounded batches with independent Codex checks. No credentials in worker tasks; one writer per file. Retain logs and a phase ledger. No success claims from mocks, empty fallbacks, unobserved data or worker self-report.
