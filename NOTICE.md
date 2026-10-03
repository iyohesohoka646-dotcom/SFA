# Third-party notices

The original SFA source and MIT copyright notice are retained in `src/sfa/` and `LICENSE`. Contract-Driven AI Flow is a local rearchitecture of that project.

The bundled frontend contains React/React DOM (MIT), React Flow / @xyflow/react (MIT), and elkjs (Eclipse Public License 2.0). Their source versions are locked in `web/package-lock.json`. Dependency license text is distributed under `src/contract_driven_ai_flow/static/licenses/` and included in the wheel. Source/build instructions are in `CONTRIBUTING.md`.

The optional Archify adapter consumes the user's separately installed checkout of `tt-a1i/archify` at `a07fa1d5b2a10cbea110c5a2be2817397a301cdc` (MIT). No Archify runtime code is copied into the core package.

Python dependencies retain their own licenses. The project does not rename third-party tools or claim their implementation as its own.

The desktop shell distributes Electron (MIT), Chromium and private CPython with their bundled license notices. NumPy, pandas, PyArrow, Textual and other dependencies retain distribution metadata/licenses. Desktop versions are locked in `desktop/package-lock.json`.

Client organization draws on Codex `6b4daafdb445340e5af66f067ad4057e6ed9fd81`, Kilo `dfb23a4e63e24e82a669a0eaf1e48e3c4ca21bec` and DeepSeek Harness `639ed015397290b3745d163aafe02ffee4aa3f84`. These are design references; their runtime implementations were not copied into this package.
