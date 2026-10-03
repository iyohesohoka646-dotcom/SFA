# SDD ledger — plan: docs/superpowers/plans/2026-10-02-unified-scientific-workbench.md

Spec: docs/superpowers/specs/2026-10-02-unified-probe-workbench-design.md revision 3. Implementation starts at 2889954 on feat/contract-driven-ai-flow.

Ruling: Execute inline in the current feature checkout without another approval gate — the user explicitly requested all approved changes and is continuing this project — cost if wrong: commits can be reverted; no master merge or public release is authorized.

Baseline: Python 507 passed, 1 failed with Windows GBK UnicodeDecodeError; the failed case passes under -X utf8. Frontend 10/10 passed. Use Python -X utf8 for all subsequent commands; this is an environment setting, not a product fix.

Pre-flight interfaces:
- Tasks 1→2: v2 ProbeInstance/ProbeOutput reference v1 SnapshotRef IDs; separate capability and execution fields avoid changing old ProbeSpec semantics. Compatible.
- Tasks 1–2→3: immutable plans/config revision and task records compose existing ResearchService; output statuses remain separate from run status. Compatible.
- Tasks 1–3→4: harness consumes scoped objects, versioned evidence and registered service tools; model configuration uses existing credential service. Compatible.
- Tasks 1/4→5: source object digest and scoped fragment validator produce inert proposals, acceptance is separate. Compatible.
- Tasks 1–5→7: generated v2 schema is separate from v1 wire types; HTTP clients consume services while layout has no execution semantics. Compatible.
- Tasks 6→7: document IDs retain immutable references; geometry lock preserves empty slots and new documents use tabs. Compatible.
- Tasks 1–7→8: CLI/Web/desktop share application services; existing v1 records and command names remain. Compatible.

Tasks 1–8: pending. No implementation commits yet.

Task 6: reducer infrastructure passes 6 unit cases; shell browser gate waits for Task 7 integration.
Task 6: Ruling: Run the shell's browser gate with Task 7's real default workbench integration — Task 6's planned browser test consumes a mount point only introduced by Task 7; a temporary product/test route would add unnecessary surface — cost if wrong: layout browser defects are discovered one task later, before release.
Task 1: complete (commits e193447..7986736, tests: .venv/Scripts/python.exe -X utf8 -m pytest tests/research/test_workbench_planning.py tests/research/test_models_store.py -q → 12 passed in 2.74s)
Task 2: complete (commits 7986736..1532d21, tests: .venv/Scripts/python.exe -X utf8 -m pytest tests/research/test_workbench_probes.py tests/research/test_workbench_tools.py tests/research/test_probe_isolation.py -q → 20 passed in 22.23s)
Task 3: complete (commits 1532d21..7274982, tests: .venv/Scripts/python.exe -X utf8 -m pytest tests/research/test_workbench_execution.py tests/research/test_workbench_api.py tests/research/test_lifecycle.py tests/research/test_command_parity.py -q → 17 passed in 30.18s)
Task 4: complete (commits 7274982..fe16a53, tests: .venv/Scripts/python.exe -X utf8 -m pytest tests/research/test_workbench_harness.py tests/research/test_workbench_privacy_performance.py tests/research/test_model_settings.py tests/research/test_explanation_privacy.py -q → 25 passed in 9.77s)
Task 5: complete (commits fe16a53..6f9caed, tests: .venv/Scripts/python.exe -X utf8 -m pytest tests/research/test_workbench_changes.py tests/test_cdaf_core.py -q → 39 passed in 4.24s)
Task 6: Ruling: Locked views use their existing designated groups rather than forcing every new view into the currently active group — the approved spec preserves slots and opening rules; this keeps graph detail beside the graph — cost if wrong: a view opens in its designated existing group instead of the focused tab group.
Task 6: complete (commits 6f9caed..fc99054, tests: bash -c 'cd web && npm run test:unit' →    Duration  249ms (transform 66%, tests 17%, import 13%, worker 4%))
Task 7: complete (commits f88d79d..fc99054, tests: bash -c 'cd web && npm test -- tests/scientific-unified-journey.spec.ts tests/scientific-workspace.spec.ts' →   8 passed (1.0m))

Task 8: Ruling: Review the frozen source commit while independent installer/source-install checks finish — the source implementation and complete Python/browser suites are ready, and the plan includes review in Task 8; publication still waits for all delivery gates — cost if wrong: final delivery metadata is checked by the executor after the source review.

Final review: fresh GPT-6 Astra review of 2889954..ccc8851 and c2647fa; 10 Important findings, no Critical. Regraded ignored chart kind from Minor to Important because a successful wrong chart changes scientific interpretation. One fix pass includes these 11 findings plus the user's matrix legend/range amendment.
Final: Ruling: Real remote model quality and performance remain unverified — actual HTTP tool-loop fixtures and offline behavior are exercised without claiming a paid-provider result — cost if wrong: provider-specific latency and response failures may need further work.
Final: Ruling: Native binary acceptance remains the executor's release gate — the fresh reviewer assessed source; current installer and real close/port receipts must pass before delivery claims — cost if wrong: this lacks an independent binary audit.
Final: Ruling: Bokeh/PyVista/HoloViews and arbitrary graph wire editing remain documented extension candidates — four actual plotting adapters and a read-only provenance graph satisfy this release's concrete scope — cost if wrong: additional libraries or visual semantic editing need extension work.
Final: Ruling: Older runtime paths retain their prior reviews and full regression coverage — this fresh review deliberately covered the new workbench boundaries — cost if wrong: an unexercised legacy edge case could remain.
Final: minor (deferred): Source object code is capped at 16 KiB without an explicit per-object truncation flag; a large symbol's line range may exceed the returned excerpt.
Final: minor (deferred): Invalid CLI ask roles produce an unhandled StopIteration instead of a friendly argument error; documented roles work.
Final: reproductions: 12 backend regressions failed (23 unrelated passed), plus independent X* and historical-source cases; 4 browser regressions failed at wrong run ID, empty pinned graph, missing resume, missing legend. Heatmap unit failed on identical endpoint colors.
Final: reproduction correction: fixed the automatic-snapshot fixture's missing envelope ID, then observed it fail against the pre-fix source-scope behavior (sibling read accepted until budget exhaustion); restored the scoped implementation. Corrected Plotly trace inspection to exclude embedded default template definitions. Neither fixture defect counts as a fixed product finding.
Final: preliminary focused backend GREEN 36/36; frontend units 20/20. Final whole suites and delivery receipts pending.
Final: additional native reproduction: toolbar replot incorrectly filtered the selected Z snapshot while a newly configured plot targeted X; SQLite frozen plan and outputs confirm the mismatch. Browser toolbar-replot regression RED→fix passes all snapshots; data-view actions retain immutable focus.
Final: full browser run exposed two completed-task/live-status mismatches (41 passed). Deterministic late/stale bootstrap at the final cursor reproduces running after completion. Reconcile with the actual task's calculation receipt; no invented execution event or timeout increase.
Final: whole Python suite GREEN 573/573 (270.16 s) after backend fixes; browser final completion pending.
Final: distribution byte verification RED: pip --upgrade kept an older same-version 0.4 package in the private desktop runtime (studio.py mismatch), despite matching version metadata. Force reinstall the exact candidate wheel without dependency churn, then compare every installed package resource before writing a passed receipt. Final installer must be rebuilt from these verified bytes.
Final: fixed all 11 material review findings plus matrix legend/range, toolbar scope, terminal status reconciliation and Windows state sharing — observed backend/browser/byte reproductions RED→GREEN; whole Python suite 573/573, frontend units 20/20, browser suite 45/45.
Final: delivery GREEN: fresh isolated wheel and updated source archive install journeys passed; exact wheel/private-runtime/source files 221/221 matched; rebuilt native 0.4 executable passed actual own-script/drawing/harness/CLI/report/window-close/port checks. NSIS built but its wizard was not executed. No remote provider inference or macOS/Linux native installer claim.
Task 8: complete (commits fc99054..465fabc, tests: .venv/Scripts/python.exe -X utf8 -m pytest -q → 573 passed in 263.24s (0:04:23))

Final acceptance: task-done reran the final tree: 573 passed in 263.24 s; all eight planned tasks are complete. Actual unpacked Windows 0.4 desktop was opened against the persistent scientific-workspace example; its owned backend responded HTTP 200 on port 8765. Publication is the previously authorized feature-branch push and draft PR update, with no base-branch merge or package-index release.
