# 0.2.0 release candidate

This is a reviewable release candidate in `feat/contract-driven-ai-flow`, based on SFA `c9a745e851d155b4c5fdede2d6cd2758c530e3c0`, now available in [draft PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1). Product names, README, Python distribution/import/CLI and executable examples are updated. The remote remains SFA; [prepared repository metadata](repository-metadata.json) records the proposed name, About text and topics. The feature branch was pushed with explicit user authorization. Repository rename, default-branch merge, PyPI publication and online hosting have not been performed.

## Verification record

Validation is performed on Windows with Python 3.11.9 and Node.js 24.16.0. The original baseline was 256 tests. The final [machine-readable receipt](assets/validation.json) records counts, case names, package/source digests, isolated-install dependencies and performance measurements. [Whole-branch review](review.md) records the ten findings and regression fixes. Local acceptance is recorded separately from [the nine passing Python CI combinations](assets/ci-python.json). The latest browser and package checks are available in [PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1/checks).

| Delivery path | Evidence |
|---|---|
| Original baseline | 256 passed |
| Python regression | 352 passed, zero failures/errors/skips; includes six independent-background-service lifecycle checks and eight entry-point regressions |
| Production frontend / generated types | Build passed; dedicated ELK Worker fixed and bundled |
| Browser acceptance | Ten passed: the six graph/history/review cases plus first-use workspace → new contract → reviewed generation → execution, mobile/keyboard/focus, project tools/probe editing and session recovery; current duration is in the receipt |
| Reference cases | Three real success runs and three completed quality-failure runs; [source-linked receipts](examples/validation.json) |
| Optional Archify | Pinned reference rendered, validated and checked; geometry checks passed |
| OpenTelemetry | OTLP links/attempts and an in-memory SDK SpanExporter test passed; no collector transmission |
| Clean wheel install | Separate venv without system packages: all three no-key demos, `cdaf`/`sfa`, HTTP startup/reuse/shutdown, empty-directory workspace, native shortcuts and a fresh `cdaf-studio` GUI launch passed; bundled Python/schema/UI files match source bytes |
| GitHub installation | [Immutable feature-commit archive](assets/github-install.json) installed through isolated tool/bin directories: CLI, no-key example, workspace, bundled Studio and shortcuts passed without Git or Node |
| Source installation | `uv tool install` of the source archive in isolated tool/bin directories passed CLI, example success/failure, bundled Studio, first-use workspace and native shortcut checks |
| Local deployment | Windows double-click start/stop launchers, detached service, authenticated readiness, user project catalogue, log/state files, safe reuse, coordinated automatic ports and breakpoint cancellation; [deployment guide](local-deployment.md) |
| macOS/Linux | [Nine CI combinations passed](assets/ci-python.json): Python 3.11–3.13 on Windows, macOS and Linux, including built-wheel installation |
| Paid LLM providers | Adapters available; live provider calls not tested |

[Browser measurements](assets/large-graph-performance.json) record 630 semantic modules, 30 collapsed groups, load/layout time and search interaction. The fixture is a large disconnected grouped graph, not a dense production graph benchmark. [Capture measurements](assets/capture-performance.json) separate serialization, sanitization/capture and SQLite event cost. Timings describe this host; they are not a universal latency guarantee. Normal four-node measurements are in [browser-performance.json](assets/browser-performance.json).

## Reproduce

```console
python -m pip install -e ".[dev,telemetry]"
python -X utf8 -m pytest -q --junitxml=.work/python-tests.xml
python scripts/export_schema.py
cd web
npm ci
npm run build
npm test
cd ..
python scripts/build_examples.py
python scripts/benchmark.py
python -m build
python scripts/verify_wheel.py
python scripts/verify_source_install.py
python scripts/record_release.py
```

Browser tests require the repository's `.venv` interpreter and installed Edge on Windows, or Playwright Chromium elsewhere. The clean wheel check creates a separate venv without system packages, installs the wheel, verifies bundled assets, runs all three no-key demos and exercises both CLI names. It retains its local receipt under `.work/wheel-validation.json`; `record_release.py` verifies its wheel digest and exact source/asset equality before publishing the portable receipt. That record excludes the temporary environment path and local username. The optional Archify adapter uses the setup in [the CLI reference](cli.md); without its local validation receipt, a reproduced aggregate marks that adapter as not run. The final source archive should be rebuilt after collecting documentation receipts (`python -m build --sdist`).

Python wheels include compiled UI and third-party license texts. Source releases also include frontend sources/lockfile, Python schemas, build scripts, tests, source examples, screenshots and offline evidence. Ordinary users need only Python. Node.js is required for rebuilding Studio and for the optional pinned Archify adapter.

The installed entry-point follow-up implements the [Web/CLI coverage matrix](web-cli-delivery.md), TTY/JSON output, stdin, shared capability discovery, source/plan tools, migration and storage tools, provider readiness and connection recovery. A second independent review reproduced six defects. The implementer added failing regressions, corrected them and reran the complete acceptance paths; [review.md](review.md) records the boundaries and fixes. A real in-app browser also executed the default workspace example and displayed completed/passed with 27 events.

The connection-refused report was reproduced with no listener on port 8765. The local deployment follow-up adds an independent background lifecycle and verifies it after the launcher exits. Windows venv redirectors have a different PID from the actual Python server, so readiness uses a launch identifier and authenticated server identity. Five regressions cover persistence/reuse, occupied ports, stale PID safety, authenticated shutdown and cancellation of a paused breakpoint run. A live in-app browser loaded the actual project graph and history. The 630-module browser test also exposed repeated YAML loads in the proposal-list endpoint; one architecture load per list request restored passing acceptance without relaxing its timeout. Two failed browser receipts are retained locally before the fix.

## Scope gates

Current delivery supports local Python DAGs, explicit interfaces, reviewable code/architecture changes, bounded JSON process transport, deterministic decisions, observational probes and offline sharing. Process isolation inherits OS permissions. Contracts are verified conservatively; unknown relationships require an explicit dynamic boundary. Static checks do not prove candidate business behavior. Compatibility/migration preserves authored legacy files and marks old evidence as old-format/unknown-version.

Cross-platform Python CI has passed. Actual external-model behavior and publication remain separate release gates. Multi-language execution, distributed scheduling, real-time collaboration, cyclic graphs, automatic class instance construction and an OS sandbox remain outside this version. Export receipts and browser tests cover recorded fixtures; they do not certify every possible authored graph's readability.
