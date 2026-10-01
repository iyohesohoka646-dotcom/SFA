# Implementation record

Baseline: SFA `c9a745e851d155b4c5fdede2d6cd2758c530e3c0`. Reference: Archify `a07fa1d5b2a10cbea110c5a2be2817397a301cdc`. Started 2026-09-14. Branch: `feat/contract-driven-ai-flow`.

The approved scope is a local Python workbench with explicit contracts, reviewed architecture/code changes, process execution, runtime probes and a React Flow editor. The upstream `sfa` package remains available for migration; new development uses `contract_driven_ai_flow`.

| Phase | Status | Evidence / remaining work |
|---|---|---|
| P0 baseline, naming, usable demo | implemented and locally verified | Original baseline: 256 tests; new distribution, bilingual README and three executable no-key demos |
| P1 models, compiler, storage, migration | implemented and locally verified | Explicit bindings, composite interfaces, conservative compatibility, atomic journal, SQLite and non-destructive migration regressions |
| P2 changes, context, workers, probes | implemented and locally verified | Reviewed body patches/inverse rollback, bounded contexts, package-relative imports, process execution, privacy, pause/cancel and branch regressions; 351 Python tests passed |
| P3 editor, runtime inspection, review, export | implemented and locally verified | Ten browser cases passed, including workspace → contract → generation → review → execution, contract/binding/probe edits, rollback, session recovery, mobile/keyboard and a 630-module folded graph |
| P4 examples, documentation, CI, packaging | local release candidate verified; external gates remain | Three cases each have real success/quality-failure evidence; bilingual docs, screenshots, built UI/licenses and isolated wheel acceptance. Cross-platform CI, live paid-model calls and publication remain pending |

Acceptance must use actual execution and browser evidence. Planned features and untested platforms must not be presented as verified. Local subprocesses inherit user filesystem/network permissions and are not a security sandbox. Remote rename/publication is recorded separately from local implementation.

Resumed 2026-10-01. Existing implementation was retained and verified again. One whole-branch review found ten concrete defects; a single fix pass added failing-then-passing regressions. Final acceptance and source/package digests are in [docs/release.md](docs/release.md) and [docs/assets/validation.json](docs/assets/validation.json). The Archify reference remains pinned to the recorded commit. Work is local on the feature branch; the upstream repository has not been renamed or published.

The local deployment follow-up adds `studio --background` / `--stop` and Windows double-click launchers. A process independent of the invoking terminal serves the compiled Web UI; readiness and shutdown are authenticated. Five lifecycle regressions and a real browser check cover the previously refused localhost connection. The proposal list now reads its architecture once per request, removing the large-graph startup timeout found during fresh browser acceptance.

The installed workbench follow-up provides an empty-directory workspace, three executable templates, project registration, native Desktop shortcuts, the windowless `cdaf-studio` entry, shared Web/CLI operations and a capability catalogue. Automatic launches coordinate port allocation across projects, malformed project definitions do not block the catalogue, and different services can control a shared active run through SQLite. A second independent review found six issues; all were reproduced and corrected. Fresh acceptance: 351 Python tests, ten browser tasks, isolated wheel installation including real GUI startup, and isolated `uv tool install` from the source archive. Windows Desktop launch/stop shortcuts were created locally. No remote publication or paid-model call is implied.
