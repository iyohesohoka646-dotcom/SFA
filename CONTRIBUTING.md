# Contributing to Scientific Dataflow Inspector

The implementation is a modular Python application with thin CLI/HTTP adapters and a React workbench. Keep authored semantics separate from presentation and execution evidence. Make capability claims only after running the relevant acceptance path.

## Local development

Use Python 3.11+ and Node.js 22.12+ (Node is only needed to develop/build Studio).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,research,tables,telemetry]"
.venv\Scripts\python.exe scripts/export_schema.py
cd web
npm ci
npm run build
npm test
cd ..
.venv\Scripts\python.exe -X utf8 -m pytest -q
```

On macOS/Linux, use `.venv/bin/python`. Playwright uses installed Edge on Windows; elsewhere run `npx playwright install --with-deps chromium` before browser tests. The test server creates a private temporary example and never opens a user's project.

`npm run dev` uses the Vite development server and proxies `/api` to port 8765. Start `cdaf studio --no-open` separately; use its session hash in the development page. The production wheel serves precompiled assets directly and needs no frontend toolchain.

## Verification and generated files

Python models generate JSON Schema with `scripts/export_schema.py`; `npm run types` generates TypeScript from that schema. Include schemas, generated types and production static assets in a source release. Keep the npm lockfile. Do not commit `.cdaf/`, virtual environments, logs or node_modules.

Run focused regressions for compiler boundaries, patch scope, privacy, interruption and actual worker behavior when those mechanisms change. Run the full suite, production build, browser acceptance and clean-wheel smoke test before a release. `scripts/build_examples.py` regenerates evidence only for unchanged reference models/source; it refuses to overwrite edited examples. `scripts/benchmark.py` measures capture and event costs. Test counts and host limits are recorded in `docs/release.md`.

## Code and review

Use concise comments for intent that the code cannot explain. Avoid speculative frameworks and silent fallbacks. A compiler diagnostic must identify the affected module or binding. Candidate code must remain inert until reviewed acceptance; architecture and view revisions must not be mixed. Probes observe values without modifying scheduling state themselves.

Module sources are user code with ordinary OS permissions. The patch checker constrains accepted changes, and does not make arbitrary project code a sandbox. Do not send credentials or fixture secrets to providers; keep provider configuration in process environment variables.

The original `src/sfa/` package and `examples/pipeline/` support migration and compatibility tests. New features belong in `src/contract_driven_ai_flow/`; do not silently strengthen claims about the legacy executor.

Scientific adapters/probes/runners/renderers follow the documented version-1 interfaces. Keep unknown types safe, history bounded and fidelity visible. Run `npm run test:unit --prefix web` as well as browser checks. Desktop development and installed-window verification are in [desktop/README.md](desktop/README.md).
