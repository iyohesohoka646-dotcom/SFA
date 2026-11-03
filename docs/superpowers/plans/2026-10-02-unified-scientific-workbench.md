# Unified Scientific Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved scientific tool workspace with unified probes, explicit execution and rendering, public plotting tools, an automatic task harness, reviewed reverse code changes, and equivalent local Web/desktop/CLI services.

**Architecture:** Keep the existing observation process, scientific adapters, SQLite evidence, model-provider service and symbol patch validator. Add a composed scientific workbench service with versioned analysis/configuration/plan/probe-output/task contracts; the harness uses registered tools against these contracts and never depends on frontend selections to construct invisible requests. The React workspace stores geometry separately from scientific meaning and evidence.

**Tech Stack:** Python >=3.11, Pydantic 2, FastAPI, SQLite, LibCST, Typer/Textual, React 19/TypeScript, React Flow/ELK, Electron; optional isolated Matplotlib/Seaborn/Plotly/Altair workers.

**Spec:** `docs/superpowers/specs/2026-10-02-unified-probe-workbench-design.md`, revision 3, including the user's 2026-10-02 implementation authorization and five amendments.

**Execution:** Native execution in this chat on the existing `feat/contract-driven-ai-flow` checkout. The user explicitly requested direct implementation of the approved design and amendments; no further design or plan approval is pending.

## Global Constraints

- Preserve Python >=3.11, the distribution/import/CLI names, existing scientific protocol v1 records, local service/desktop lifecycle, and read-only viewing of historical evidence.
- The visible workspace has independent document tabs and adjustable splits, no stage homepage or permanent explanatory paragraphs.
- Closing, minimizing and focusing a view have distinct behavior; a locked layout preserves group positions/sizes, including when new documents open or existing documents close.
- Name the global view “计算关系图”; direct parents and consumers have distinct emphasis, and unrelated objects fade slightly without becoming unreadable.
- Unified protocol v2 distinguishes view/check/interpret capability from builtin/program/model/Skill/manual execution; pictures do not count as passed checks.
- Import/parse/configure do not execute scripts or plot. “运行” submits a frozen plan; replot/check uses saved evidence and never reruns experimental side effects implicitly.
- Public tool catalog scope is independent of the host's packages; actual availability/adapter/installation state is explicit. Installation targets the project's managed drawing environment.
- Model contexts are assembled automatically from environment, registered tools, selected source and versioned evidence. UI shows the actual context/tool log, not a mandatory context-configuration checklist.
- AI candidates remain inert until explicit accept; source changes invalidate old plans/candidates. Numerical behavior is marked unverified unless a selected validation actually ran.
- Slow plotting/install/model work is cancelable and independent of UI interaction; source/data/model privacy is enforced before persistence, API delivery and model calls.
- Rendering resources ship locally; CLI, Web and desktop use the same application services; complete browser, package and Windows delivery checks before completion claims.

## Review Focus

1. Selection/late results/persisted tabs across different runs must preserve a pinned object's version; stale responses cannot replace another probe's output.
2. Locked, minimized, closed and maximized groups must restore geometry and accept new documents without triggering computation or unexpected layout changes.
3. Unknown/non-NumPy values, partial captures, missing tools and unsupported backends must retain truthful coverage and diagnostics rather than succeed with invented data.
4. Source changes during import, model tool use or code review must invalidate the affected operation, including simultaneous accepts and rollback after another edit.
5. Host-installed packages and retrieved Skill/model text must not expand the registered tool or file scope; secrets must be absent from saved contexts, artifacts, exports and responses.

---

### Task 1: Versioned analysis, probe configuration and execution planning

**Files:** Create `research/workbench/models.py`, `analysis.py`, `configuration.py`, `planning.py`, `store.py`; test `tests/research/test_workbench_planning.py`; all Python paths are under `src/contract_driven_ai_flow/`.

**Interfaces:**
- Produces `AnalysisDocument`, `SourceObject`, `Relation`, `ProbeDefinition`, `ProbeInstance`, `ProbeOutput`, `WorkbenchConfig`, `ExecutionPlan`, `TaskRecord`, `HarnessPolicy`, `CodeProposal`, exported from `research.workbench.models`.
- Produces `analyze_source(path: Path) -> AnalysisDocument`, `compile_plan(analysis, config, definitions) -> ExecutionPlan`, `ConfigurationStore.load/save(expected_revision)`, and `WorkbenchStore` CRUD for plans/tasks/outputs/proposals.
- References source objects by canonical path + qualified symbol + source digest; snapshots continue to use existing v1 IDs.

- [ ] Write tests for import without executing side effects, scope-qualified duplicate names, assignment mutation dependencies, invalid syntax, frozen probe/config/source digests, revision conflict, and non-destructive legacy configuration migration.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/research/test_workbench_planning.py -q`; expected missing-module failures, then implement the contracts/AST projection/compiler/store.
- [ ] Run the same tests plus `tests/research/test_models_store.py`; expected all pass with the script's side-effect file absent.
- [ ] Commit the independently usable analysis/configuration/plan service.

### Task 2: Unified probes, public tools and drawing jobs

**Files:** Create `research/workbench/catalog.py`, `tools.py`, `tool_worker.py`, `rendering.py`, `jobs.py`, `relations.py`; test `tests/research/test_workbench_probes.py` and `test_workbench_tools.py`; add optional `views` dependencies to `pyproject.toml`.

**Interfaces:**
- Consumes Task 1 models/store; existing `SnapshotRef`, `ProbePool` and strict JSON encoding.
- Produces `ProbeCatalog.definitions/resolve`, `relationship_output(research, snapshot_id) -> ProbeOutput`, `ToolManager.catalog/scan/install/disable/remove`, `DrawingService.render(instance, snapshot) -> ProbeOutput`, `JobManager.submit/get/list/cancel/close`.
- Builtin matrix/table/scalar/relation outputs refer to versioned evidence; program checks adapt existing v1 results. Plotting workers receive bounded sanitized JSON and return PNG, controlled self-contained HTML or Vega-Lite JSON.

- [ ] Write failing tests for view/check status separation, direct relation evidence/provenance, unknown types and partial captures, cache invalidation, worker timeout/cancel, public catalog without installed packages, metadata discovery without importing packages, and managed-environment-only installation.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/research/test_workbench_probes.py tests/research/test_workbench_tools.py -q`; expected failures for unavailable new interfaces.
- [ ] Implement the catalog, entrypoint extension contract, explicit tool availability, subprocess drawing, artifact receipts, cancellation and reuse; verify Matplotlib/Seaborn/Plotly/Altair with real optional packages in the local project environment.
- [ ] Run those tests plus `tests/research/test_probe_isolation.py`; expected all pass, valid actual plotting artifacts and no change to the analysis environment.
- [ ] Commit unified probe and tool services.

### Task 3: Staged execution and shared HTTP commands

**Files:** Create `research/workbench/service.py`, `routes.py`; modify `research/routes.py`, `research/service.py`, `application/commands.py`; test `tests/research/test_workbench_execution.py`.

**Interfaces:**
- Produces `WorkbenchService.import_source/configure/plan/execute/execute_probes/replot/task/outputs/relationships/close`, composing Tasks 1–2 and `ResearchService`.
- HTTP adapter at `/api/v1/research/workbench`: analysis, configuration, plans, task submission/control, output/artifact/relationship lookup, tools and capability discovery; shared commands invoke these same methods.
- Frozen `ExecutionPlan` owns source/config/environment versions; task records link calculation, checks and drawing. A real computation uses existing `start_analysis`; postprocessing never obscures its status.

- [ ] Write a failing end-to-end service test: parse/configure leave a side-effect counter untouched; one execute increments it once and produces real captured checks/views; replot uses that evidence and leaves the counter unchanged.
- [ ] Cover stale-source rejection, drawing failure after calculation succeeds, cancellation, reconnect/restart interruption, missing evidence and bounded wildcard probe expansion.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/research/test_workbench_execution.py -q`; expected missing workbench routes/service, then implement composition and task records.
- [ ] Run that file plus `test_workbench_api.py`, `test_lifecycle.py`, `test_command_parity.py`; expected compatible v1 endpoints and all new journeys pass.
- [ ] Commit shared execution/HTTP services.

### Task 4: Automatic task harness and model/Skill execution

**Files:** Create `research/workbench/intelligence/context.py`, `tools.py`, `harness.py`, `skills.py`; modify `settings/service.py`, workbench service/routes; test `tests/research/test_workbench_harness.py`.

**Interfaces:**
- Produces `HarnessContextBuilder.environment/assemble`, `HarnessToolRegistry.describe/call`, `HarnessService.execute(request, task_id, cancel)`, versioned role policies and tool/call/context receipts.
- Read tools include scoped source, analysis objects, snapshot description/bounded samples, direct relations, probe outputs, public tool contracts and registered Skills. Write tools propose changes or prepare plans; executing a plan requires the configured execution capability and records it.
- `ModelSettingsService.complete` accepts bounded output/request settings while preserving existing defaults; all roles reuse its provider/credential/cancel/usage path.

- [ ] Write failing fake-provider integration tests in which the model chooses a registered tool, consumes its real result, and cites it; cover unknown tools, wrong/stale IDs, exhausted input/call/step budgets, canceled calls and role capabilities.
- [ ] Add tests proving no whole-file/sibling-symbol context leak, no secrets in actual sent messages/logs, automatic environment/tool knowledge without manual context selection, and Skill/manual evidence provenance.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/research/test_workbench_harness.py -q`; expected missing interfaces; implement bounded automatic context and tool loop.
- [ ] Run that file plus `test_model_settings.py`, `test_explanation_privacy.py`; expected all pass; distinguish fixture API evidence from any real provider check.
- [ ] Commit the harness and record official-source architectural references in docs.

### Task 5: Reviewed reverse source changes and controls

**Files:** Create `research/workbench/changes.py`; modify workbench service/routes and harness tool registry; test `tests/research/test_workbench_changes.py`.

**Interfaces:**
- Produces `ScientificChangeService.propose/validate/accept/reject/rollback` returning `CodeProposal`; uses `source.replace_body` and source digest checks.
- Supports declared Python functions and stable assignment steps, plus a reviewed new analysis skeleton within the selected project. Candidate, code diff, diagnostics, behavior-validation status and affected probe bindings are separate from execution.

- [ ] Write failing tests for one scoped function/assignment update, extra definitions/signature/internal import rejection, concurrent source edits/accepts, unrelated-symbol preservation, rollback conflict, and inert candidates that neither modify nor execute code.
- [ ] Verify the model cannot apply its own proposal; source is reparsed after an explicit accept; only genuinely executed validation can be labeled behavioral evidence.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/research/test_workbench_changes.py -q`; expected missing service, then implement changes and harness proposal tools.
- [ ] Run that file plus `tests/test_cdaf_core.py`; expected all pass without regressions to the original restricted patch mechanism.
- [ ] Commit reverse changes.

### Task 6: Persisted adjustable, minimized and locked document layouts

**Files:** Create `web/src/research/workspace/layout.ts`, `WorkspaceShell.tsx`, `useWorkspace.ts`, `workspace.css`, `icons.tsx`; test `web/tests/research-layout.test.ts` and `scientific-workspace.spec.ts`.

**Interfaces:**
- Produces typed `WorkspaceLayout`, `WorkspaceDocument`, layout reducer/actions, persistence schema, `WorkspaceShell` and pane callbacks.
- Documents carry immutable run/snapshot/probe/source-version references; layout carries group dimensions, minimized groups, active tabs, focus state, locked state and named saved presets.
- When locked, new documents enter an existing active group; closing leaves its slot; temporary focusing restores geometry; resizing is blocked. Unlocked horizontal and vertical separators support pointer and keyboard adjustment.

- [ ] Write reducer tests for resize bounds, minimize/restore, locked open/close, focus/restore and incompatible persisted-layout migration; late response tests preserve pinned data.
- [ ] Run `npm run test:unit -- tests/research-layout.test.ts`; expected missing modules, then implement layout and shell.
- [ ] Add browser checks for dragging both axes, minimize without close, locked geometry with a new view, closing/restoring slots, named preset reload and keyboard focus.
- [ ] Run focused unit/browser tests; expected all pass and no script/model task submitted while restoring layout.
- [ ] Commit reusable workspace infrastructure.

### Task 7: Scientific tool workspace, relation graph and harness UI

**Files:** Refactor `web/src/research/ResearchWorkbench.tsx`; create focused `workspace/controller.ts`, `WorkbenchClient.ts`, `ProbeWorkspace.tsx`, `ProbeInspector.tsx`, `RelationGraph.tsx`, `ToolLibrary.tsx`, `IntelligencePanel.tsx`, `ChangeReview.tsx`, `TaskPanel.tsx`, `ArtifactView.tsx`; retain existing matrix/table/custom-renderer components. Modify generated schema scripts and scientific UI tests.

**Interfaces:**
- Consumes Tasks 1–6 contracts via generated `workbench` TypeScript types and shared HTTP adapter.
- Controller handles import, configuration, selected evidence, frozen execution and independent task cancellation; views use immutable document references.
- “计算关系图” builds bounded semantic relations, groups scopes, retains positions, highlights incoming/outgoing direct relations and slightly fades unrelated objects; relation probes use the same evidence.
- Plotting is loaded on demand; tools show public catalog/actual availability and managed jobs; intelligent tasks use automatic harness context with a read-only call log and a stable model-settings entry.

- [ ] Write browser journeys for import-before-run probe configuration; calculation/check/drawing output; two fixed versions side-by-side; graph adjacency/provenance; model tool loop and proposal diff/accept; tool discovery; minimize/lock/preset.
- [ ] Run focused browser tests to observe failures against the existing UI; implement modular workspace views, controller and styles using the approved tool layout.
- [ ] Run scientific browser journeys and unit tests; record graph/pane interaction latency against the existing 1000-variable fixture and demonstrate UI remains usable during a slow drawing/model task.
- [ ] Inspect desktop and narrow renders once, batch material visual fixes, confirm affected renders once; no common footer explanations or fake successful placeholders.
- [ ] Commit the integrated workspace.

### Task 8: CLI, migration, offline exports and local release

**Files:** Create `research/workbench/cli.py`; attach to `cli.py` and terminal commands. Update `research/export.py`, schema exports, examples, README/README.zh-CN.md, `docs/research.md`, release/extension docs, CI and installer manifests as needed; test CLI/package/export journeys.

**Interfaces:**
- `cdaf research import/plan/run/probes/tools/ask/changes` uses the same workbench service as HTTP; existing `observe`, legacy architecture CLI and model settings remain compatible.
- New config migration preserves `research.yaml` and v1 evidence; offline reports use stored sanitized outputs/resources. Local distribution is version 0.4.0 with built frontend and private optional plotting runtime where required.

- [ ] Write failing CLI parity, migration and offline-export tests; implement commands, docs and reproducible scientific examples including pure Python/custom-adapter data.
- [ ] Run the complete Python and frontend suites, generate schemas, build frontend/desktop/wheel, install into a fresh project environment and execute real parse/run/probe/drawing/CLI/harness-fixture journeys.
- [ ] Verify Windows application startup, operations and close/stop, publish only to the already-authorized feature/draft-PR path, and avoid a master merge or public package release.
- [ ] Run one fresh whole-change code review per executing-plans; fix material findings with reproducing tests; retain evidence and accurate unverified limits in release docs.
- [ ] Commit final delivery and leave a concrete launch path.
