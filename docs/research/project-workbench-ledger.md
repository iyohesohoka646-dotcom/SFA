# Project workbench execution ledger

Specification: docs/superpowers/plans/2026-10-12-project-research-workbench.md and the user-approved P0-P5 plan.
Base: 2fe95ff. Execution branch: feat/project-workbench.

- P0: in progress; original checkout clean, isolated worktree created.
- Backend: DSH (already selected by user), official deepseek-flash. Codex reviews and independently verifies.
- Ruling: native worktree tool returned `Not a git repository` for this parent-directory task; native Git worktree created from the verified repository instead. The original checkout remains unchanged.
- Ruling: use one active project in the UI and explicit project IDs in every backend request; existing jobs remain owned by their original project.
- P1/P2/P3/P4/P5: pending.
- P0 RED: two frozen project-index acceptance cases fail with `Project-level service is missing`, as expected.
- Ruling: installed official DSH Flash rejected `medium` at session initialization before any model request. Use the supported `low` effort in a fresh session; the failed initialization exited and owned child termination was verified.
- P0 baseline complete: Python 783 passed / 8 platform skips in 413.56s; frontend 111 passed. Installed data inventory contains 5 run IDs and configuration hashes; inventory and logs are in .work/project-acceptance. No user run was created or changed.
- P2 runtime RED: two frozen cases fail with `Cross-module observation runner is missing`.
- P1 request 1: official deepseek-flash route verified, no scope violations; transport ended before completion. Independent frozen tests fail because root glob excludes root files. Review also found repeated AST parsing, unsanitized archives and non-atomic relationship publication. Request 2 is a bounded implementation continuation addressing these findings, not a passing delivery.
- P1 request 2 independent verification: original 17 index cases pass, but three additional frozen reproductions fail (annotated/augmented assignment, absolute import within a package, and copied root retargeting). Request 3 also addresses canonical keys, revision ownership, meaningful argument/return edges and bounded graph slices. No implementation accepted yet.
- P2a allocation: retain user-selected official DSH Flash but use supported high effort, 50 steps/600s per request (maximum 3). Import/cache/evaluation and recursive provenance semantics make this higher-risk than mechanical integration; unsupported medium will not be reused. Official reasoning IDs rechecked against API docs.
- P0 browser baseline complete: 92 passed (5.6m), actual Edge/Playwright local services; native desktop remains unverified.
- P1 request 3 independent 25 tests pass but two added acceptance cases fail: 70 files/limit20 returns71 blocks; caller module X incorrectly links to same-named function-local X. First DSH task rejected, partial workspace retained. Narrow correction task with supported high effort is warranted by reproducible semantic/performance failures; no production integration.
- P1 targeted high-effort request1 exhausted one response output budget after inspection without file changes. Request2 explicitly requires small targeted edits for the two frozen failures, followed by cooperative scan cancellation; no whole-file rewrite. Route verified official deepseek-flash; no scope violations.
- P2b application frozen acceptance: 2 failures `Project application is missing`; captured before implementation.
- P1 targeted correction independently verified: 58 tests pass, plus large72-file cross-call check. Found folder membership omission in expanded scope check; Codex applied a minimal 7-line hierarchy bookkeeping patch (delegation overhead exceeds this mechanical fix), observed RED then GREEN, reran 20 frozen/semantic cases successfully. Worker closed normally with owned_child_exited=true. Accepted allowed implementation files into isolated worktree; independent scope cases retained in CI.
