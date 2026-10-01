# Scientific Dataflow Inspector 0.3.0 candidate

The scientific workbench replaces the default architecture-first screen with source, observed values, local computations, probes and recorded evidence. Web, Windows desktop, interactive terminal and batch CLI share the same research services and project model settings. `contract-driven-ai-flow`, `contract_driven_ai_flow`, `cdaf` and `sfa` remain the distribution/import/command names; the GitHub repository remains SFA. [Draft PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1) is the review surface. No default-branch merge, repository rename, PyPI release or online hosting is part of this candidate.

The new protocol has independent data-adapter, probe, runner and renderer registrations. NumPy and pandas are initial built-ins; an independent point-cloud adapter and Canvas renderer exercise the extension path. GPU, sparse, distributed and other-language built-ins are not implemented. See the [extension contract](research/adapter-api.md), [probe contract](research/probe-api.md), [coverage limits](research/limitations.md) and [read-only legacy migration](research/migration.md).

## Acceptance evidence

The [scientific receipt](assets/research-validation.json) aggregates successful local runs, installed wheel/source checks, exact source-manifest and installer digests. [Package receipt](assets/validation.json) lists every browser case and verifies that all packaged Python/schema/UI bytes match this checkout. These records are only regenerated from passing checks; earlier 0.2.0 review/CI receipts remain historical evidence and are not proof of 0.3.0 cross-platform acceptance.

| Path | What is exercised |
| --- | --- |
| Python | Complete repository suite, including independent interpreter capture, mutation/version handling, bounded probes, privacy, cancellation, process failure and local authorization regressions |
| Browser | Full Playwright suite against actual compiled assets: large history, Chinese labels, keyboard navigation, stale requests, matrices, point cloud, model settings, probes, offline export and owned-tab lifetime |
| Own-script journey | Open an ordinary NumPy/pandas script, inspect `Z`, locate NaN at its source, preview/save a probe, inspect explanation scope, export redacted offline HTML and preserve original source |
| Wheel | Separate environment without system packages or Node: scientific success, quality failure and dimension-error cases; an independent standard-library-only analysis environment; old no-key demos and installed Web/CLI launchers |
| Source archive | Isolated `uv tool`/bin directories, the same scientific cases, bundled UI, workspace startup and native shortcut creation |
| Windows desktop | Installed executable with private Python containing the same 0.3.0 core; own-script matrix/probe/context/export journey, shared CLI history, real window close and actual port release |
| Interactive terminal | Real Windows ConPTY journey: open/run/inspect, choose offline model, cancel live analysis, exit and restore terminal state; [receipt](assets/research-terminal-validation.json) |
| Cross-platform Python | Nine configured Windows/macOS/Linux × Python 3.11–3.13 jobs; current-head results must come from [PR checks](https://github.com/iyohesohoka646-dotcom/SFA/pull/1/checks), not older receipts |

The Windows NSIS installer is a local unsigned candidate. Its actual filename and SHA-256 are recorded in the scientific receipt. macOS/Linux native packaging and window lifetime remain unverified. External provider protocols are tested with local synthetic servers; no paid model inference or real provider credential was used. Connection/model discovery and inference remain distinct controls.

## Performance

[Measurement details](research/performance.md) distinguish computation overhead, input-to-paint response, selected-detail fetch, live observation-to-paint latency and heap retention. A real ten-minute 10 Hz matrix run follows the earlier run that exposed retained historical preview arrays. Historical indexes now store metadata; details are fetched for the selected version. The two-minute heap medians near the end decreased from 59.08 to 13.57 MiB on this host. This is evidence of reduced retention in the measured run, not an indefinite memory-stability guarantee.

The 1000-value/10000-event fixture limits the canvas to 80 visible nodes and checks p95 input response ≤100 ms and detail fetch ≤250 ms. Live-stream acceptance separately measures observation timestamps to painted selected details at target 10 Hz. SDK and selected automatic-capture measurements use repeatable CPU-bound computations with equal output digests. None of these fixtures certifies arbitrary code, backend, graph density or hardware performance.

## Reproduce

```console
python -m pip install -e ".[dev,research,tables,telemetry]"
python -X utf8 -m pytest -q --junitxml=.work/python-tests.xml
python scripts/export_schema.py
npm ci --prefix web
npm run build --prefix web
npm run test:unit --prefix web
python scripts/profile_research_workbench.py
npm test --prefix web
node scripts/measure_research_stream.cjs 60
python -m build
python scripts/verify_wheel.py
python scripts/verify_source_install.py
python scripts/record_release.py
python scripts/record_research_release.py
```

Browser checks use the repository `.venv`, Edge on Windows and Playwright Chromium elsewhere. The Playwright configuration creates a private per-run fixture session. Windows live-stream/RSS measurements currently use Edge and Windows APIs. For desktop building, private-runtime preparation, installation and the native journey, follow [desktop/README.md](../desktop/README.md); the installed executable must be supplied to acceptance. Node is a developer/build dependency. Python wheel users receive compiled assets, schemas and third-party license notices.

Source archives include frontend and desktop sources/lockfiles, tests, examples, documentation and build scripts. The final source archive can be rebuilt after recording documentation receipts; rerun source-install acceptance on that archive. Runtime data and private bundled environments are excluded from source/wheel releases.

Local Python subprocesses and explicitly enabled plugins retain the operator's filesystem/network permissions. Capture limits and immutable evidence do not provide an OS sandbox. Replay reads saved evidence; it does not repeat side effects. Full materialization and sending redacted samples to a configured model require explicit choices. Heuristic redaction does not recognize every possible secret.
