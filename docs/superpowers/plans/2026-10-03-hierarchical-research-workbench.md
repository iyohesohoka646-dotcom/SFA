# Hierarchical Research Workbench Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline. Steps use checkbox syntax to track progress.

**Goal:** Deliver the approved hierarchical, probe-governed scientific workbench with real terminal and verifiable effects.
**Architecture:** Modular local application; semantic graph and evidence services distinct from AI permissions. Frozen invocation plans and immutable artifact references feed shared CLI/web/desktop.
**Tech Stack:** Python/Pydantic/FastAPI/AST, React/TypeScript/React Flow/ELK Worker/Dockview/xterm.js, ConPTY/POSIX PTY.
**Spec:** `docs/superpowers/specs/2026-10-03-hierarchical-research-workbench-design.md`

## Global Constraints

Retain current feature checkout, legacy evidence and project data. Never widen AI context from display graph relations. No dead folder/cross-file controls. Observe RED→GREEN for new behavior, appropriate focused task gate, final whole-suite and actual UI/native effects. Record deviations in the execution ledger. Finish every task; user implementation approval supersedes another design gate. Existing push/draft-PR authorization applies; no merge/publish.

## Review Focus

- Python truth/iterator/finally side effects and recursion; tests need actual evaluation-count contrasts, not AST shape alone.
- Snapshot identity versus logical binding, stale selections and changed catalog versions; persisted deletion and frozen inputs must survive restart.
- Exact full artifact access and coordinate provenance, redaction and retention; previews cannot silently become joint inputs.
- Dockview lock/minimize/restore and resizing under narrow viewport; browser effects and native lifecycle differ.
- Local WebSocket authorization/Origin, terminal process tree ownership and bounded control/terminal storage under interruption.

### Task 1: Semantic identities, scopes and versioned contracts

Files: workbench/models.py, analysis.py, new semantics.py, tests/test_semantic_graph.py, protocol schema generators.
Interfaces: Produces `SemanticGraph`, typed blocks/nodes/edges/ports, `TargetRef`, `ScopeSelector`, graph coverage and logical object keys. Existing source objects remain patch/context targets.
- [x] Add failing tests for same-line identity, lexical shadowing, branch merge, loop backedges and nested function/call/return; expected: current graph/identity behavior fails.
- [x] Implement versioned graph and scope compilation, fixture BlockProvider interfaces; regenerate types. Expected: graph has no dangling endpoints; permissions retain only authorized data dependencies.
- [x] Run `.venv/Scripts/python.exe -X utf8 -m pytest tests/test_semantic_graph.py tests/test_workbench_analysis.py -q`; expected all pass (locate actual existing analysis test file before gate).
- [x] Commit implementation and ledger gate.

### Task 2: Bounded semantics-preserving control collection

Files: agent/instrument.py, runner.py, transport/store; new control.py; tests/test_control_observation.py.
Interfaces: Consumes graph/source identity; produces per-activation cumulative `ControlSummary`, final completeness receipts and bounded details.
- [x] Write/run contrasting original vs instrumented truth/short-circuit/loop/finally/recursion/zero/exception tests and long-loop bound test; expected missing collection failures.
- [x] Add suite-entry branch markers and loop context collection without changing test/iterator; store bounded summaries/details. Expected exact behavior parity, interruption partial counts.
- [x] Run focused control/instrument/agent tests, commit, ledger gate.

### Task 3: Probe resources, target bindings and default presentation

Files: workbench/catalog.py, configuration.py, planning.py, service.py, rendering.py, models.py; tests/test_probe_binding.py.
Interfaces: Consumes TargetRef/ScopeSelector; produces resource manifests, persistent target selectors/default overrides and frozen resolved invocations.
- [x] Write/run tests for deleted defaults, local disable over new versions, scope dedup/freeze and changed catalog after plan; expected missing contracts failures.
- [x] Implement three-axis catalog, resources/import/schema diagnostics, binding resolver and frozen plan execution; migration backups retain IDs and explicit deletion. Expected no automatic hidden view descriptor.
- [x] Run probe binding and existing workbench tests, commit, ledger gate.

### Task 4: Semantics, full capture and immutable joint derivation

Files: models.py, agent artifacts/capture, new workbench/derivation.py and data_semantics.py, planning/service/routes; tests/test_joint_probes.py.
Interfaces: Consumes frozen input refs; produces validated semantics, complete coordinate metadata, derived evidence with parent refs and protected retention.
- [x] Write/run matrix/elementwise/broadcast/correlation/join/error/expired/preview-only/immutability tests; expected missing joint execution.
- [x] Implement targeted capture requirements, artifact access and budgets, joint role validation/derivation and reusable view semantics; no sampled full conclusions. Expected independently re-probeable derived objects.
- [x] Run focused joint/artifact tests, commit, ledger gate.

### Task 5: Unified selection and hierarchical computation workspace

Files: web/src/research/ResearchWorkbench.tsx, new object tree/selection, RelationGraph.tsx, graph projection and layout worker; unit/e2e tests.
Interfaces: Consumes SemanticGraph/TargetRef; produces shared selection/scope with explicit navigation and type-safe graph projections.
- [x] Write/run selection reducer and browser effect regressions (click no navigation, range/select-all, scoped tree, collapse endpoints, dim toggle); expected current effects fail.
- [x] Implement object browser/tree filters, keyboard/context/box selection, nested operation/control plates, three projections/edge toggles and worker layout. Expected selections do not trigger camera/layout changes.
- [x] Run relevant units/e2e/build, commit, ledger gate.

### Task 6: Probe library, governed views and combination interaction

Files: ProbeWorkspace.tsx, ProbeInspector.tsx, ToolLibrary.tsx, ArtifactView.tsx, MatrixView/TableView, derived/comparison views.
Interfaces: Consumes manifests/frozen targets/semantics/outputs; produces schema forms/templates and separate instance-specific documents.
- [x] Write/run browser tests for default stop/delete, visible inheritance/local exceptions, multi-view, numeric/labels, joint success/failure and metadata-only; expected bypass rendering fails.
- [x] Implement classified library vs instance use, target-first forms, parameter templates, governed lazy rendering and compare/derive. Expected disabling auto changes actual view across reload/new run.
- [x] Run relevant unit/e2e/build, commit, ledger gate.

### Task 7: Dockview layout, settings and result management

Files: WorkspaceShell/useWorkspace/layout, workbench.css, new Settings, TaskPanel/RunTimeline, configuration service.
Interfaces: Consumes document refs/settings/targets; produces persisted Dockview layout and settings inheritance, task/result/event grouping.
- [x] Write/run actual bounding-box tests at four widths, minimize release/restore/lock/new-slot and settings/results filters; expected current narrow geometry fails.
- [x] Implement Dockview adapter/migration, compact mode and unified settings/tasks/events. Expected run/mode/scope controls align and layout buttons visibly work.
- [x] Run browser dimensions and unit/build tests, commit, ledger gate.

### Task 8: Authenticated real terminal and lifecycle

Files: new workbench/terminal.py, routes/service lifecycle, xterm pane, desktop lifecycle/preload; dependencies; tests/test_terminal.py and browser/native checks.
Interfaces: Produces TerminalSession with cursor-based bounded replay and authenticated WebSocket input/output/resize/close.
- [x] Write/run real PTY tests for commands/Unicode/resize/Ctrl+C/reconnect/cleanup/start error/auth; expected no terminal service.
- [x] Implement ConPTY/POSIX shared sessions and xterm, visible errors and owning process cleanup; no terminal auto AI ingestion. Expected actual shell/Python/CLI responses.
- [x] Run terminal API/browser and actual Windows desktop terminal; commit, ledger gate.

### Task 9: Shared CLI, migrations and complete case library

Files: workbench/cli/routes, docs/examples and tests/migration/protocol/CLI.
Interfaces: Consumes all shared services; produces usable same-semantic CLI, backup-preserving migrations, success/failure examples and extension documentation.
- [x] Write/run CLI/migration/example checks (legacy default deletion/binding/layout/coordinates); expected new commands/migration absent.
- [x] Implement commands/settings/resources/scopes/joint, folder/stream provider fixtures and eight complete cases. Expected honest capability documentation and no inactive UI controls.
- [x] Run CLI/protocol/migration/case gates, commit, ledger gate.

### Task 10: Performance, native package and release verification

Files: benchmark/acceptance scripts, release docs, package metadata/build assets.
Interfaces: Consumes completed workbench; produces reproducible 0.5 candidate, performance/actual-effect evidence and updated existing draft PR.
- [x] Add and run thousand-object/long-loop/cancel/stale-result/effect checks; expected identified regressions fail until corrected.
- [x] Run full Python/frontend/browser suites and build/install current package; verify native effects, terminal, original data retained. Expected verified paths recorded separately from unavailable host checks.
- [x] Do one fresh final review, one RED→GREEN material-fix pass; save ledger to durable review document. Expected final suite green.
- [ ] Commit, push authorized feature branch, update/attach existing draft PR and inspect cross-platform CI; preserve exact verification limits. Delete only this plan scratch after durable ledger commit.
