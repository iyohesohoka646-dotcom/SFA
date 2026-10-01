# Whole-branch review and fixes

One independent, read-only review covered the original tracked diff, new Python core, Studio, packaging and acceptance records on 2026-10-01. It reported one Critical and nine Important findings. The implementer retained those findings, reproduced them and applied one fix pass. The reviewer did not rerun the full suite or independently re-review the fixes.

| Finding | Change and regression evidence |
|---|---|
| Critical: capture Pointer loses sensitive field name | Sanitize before selection; runtime, metric/capture and preview share the policy, and results carry redacted paths |
| Check endpoint returns restored secret literals | Compile originals, sanitize the returned execution plan |
| Plan endpoint compiles masked data | Preserve original compilation, diagnostics and semantic revision |
| CLI dumps complete source files and literals | CLI/HTTP share public ChangeSet and plan representations; local application records retain exact source |
| L1 context leaks narrative credentials | Sanitize descriptions and schema data annotations in every visibility preset |
| Initializing/queued runs bypass admission and cannot cancel | Atomically reserve one of four slots; persist/query/cancel queued runs; release on completion or initialization failure |
| Composite guard does not control children | Propagate decision dependencies and evaluate ancestor guards before descendant execution |
| Paused scheduler starts new modules | Shared pause barrier prevents dispatch; generation-based resume releases waiting boundaries |
| Runtime ignores declared symbol digest | Verify nonempty symbol digest before dispatch, retaining the worker's whole-file check |
| Architecture export silently selects an old run | Explicit current-architecture and historical-run selectors; Studio chooses by mode |

`tests/test_cdaf_release_regressions.py` initially reproduced ten failing tests. All ten passed after the fixes. Additional checks cover sensitive schema constants, literal provenance after composite expansion, quoted credentials containing spaces and history beyond the 10,000-event page limit; the latter three reproduced failures before fixes. Two further regressions reproduced package-relative import failures for a module re-exported by its parent package and for a package initializer used as the entry. The worker now uses normal package import semantics while compiling the verified entry bytes. The final regression file has sixteen tests. A genuine browser workflow also caught a stale-success display during new-run submission; Studio now clears the prior result before submitting and avoids switching modes when an asynchronous response arrives. Full-suite verification caught a Windows pipe-close race, which is now consistently recorded as WorkerExit.

Fresh full-suite, browser, example and installed-wheel results are in [release.md](release.md). Untested platforms, live external-model calls and remote publication remain separate gates; passing this fix pass does not imply those have occurred.

Browser verification also reproduced a stale runtime overlay after accepting a changed contract. Probes now displays observations only when the selected run matches the current graph revision and there is no unreviewed draft. Runs always retains the graph recorded with that run; Review uses design state without runtime badges. The browser contract-edit test covers this transition.

The subsequent local deployment fix has five separate regressions in `tests/test_cdaf_studio.py`. They first reproduced missing background/stop interfaces, then a Windows venv launcher/server PID mismatch and breakpoint cancellation delayed until lifespan shutdown. Background readiness now verifies the launch identifier and authenticated server, and shutdown cancels active runners before waiting for connections. A 630-module browser test also timed out because proposal listing repeatedly loaded the entire YAML architecture. Reading one architecture snapshot per list request restored the original test without increasing timeouts. These follow-up fixes were validated by the implementer, separately from the original independent review.

## Installed Web/CLI entry-point review

A second independent read-only review reproduced one Critical and five Important findings with temporary projects, independent TestClients and real background services. The reviewer changed no source and did not run paid providers. The implementer reproduced seven failing and one already-passing case in `tests/test_cdaf_entry_regressions.py`, applied the fixes, then verified all eight cases and the full 351-test suite.

| Finding | Fix / observed behavior |
| --- | --- |
| Critical: timezone cutoff deletes evidence outside the requested scope | Convert cutoff to UTC; SQLite compares instants including stored offsets; naive input means UTC. Active runs remain preserved. |
| CLI capture preview returns a sensitive pointer's raw value | Apply the default CapturePolicy before pointer selection, matching the Web preview. |
| A second service cannot control a shared paused run | Validate actual stored status/owner and enqueue SQLite controls; real cancel and resume reach the first service's runner. Finished-run controls return conflict. |
| Migration preview exposes narrative credentials | Reports use the shared safe project representation, preserving schema names. Migrated authored definitions and the legacy backup retain their original content. |
| Concurrent auto-launches choose the same port | Hold a user-wide launch lock through authenticated readiness; two different projects acquire distinct available ports. |
| One invalid YAML definition blocks the project catalogue and startup | Convert YAML parse failures to a readable project error and mark the catalogue entry unavailable; healthy projects and workspace startup continue. |

The earlier sixteen whole-branch cases remain intact. `tests/test_cdaf_studio.py` now has six lifecycle cases, including concurrent launches of the same project. The ten browser tasks additionally verify empty-directory onboarding, mobile overflow, keyboard tabs, focus-return dialogs, probe editing and session recovery. Isolated installed-wheel and source-install results are recorded separately in the release evidence. The reviewer did not independently re-review the fix pass.
