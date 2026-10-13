# Windows desktop shell

Electron wraps the same scientific Web UI and owns only its backend. Node integration is disabled; preload is isolated/sandboxed and navigation is restricted to the local service origin. Startup, retry and close cleanup are tested. Open Terminal focuses the shared embedded xterm.js/PTY view. Shell, Python and application CLI sessions retain their state while hidden and are cleaned up with their owner.

## Development

```powershell
npm ci --prefix desktop
$env:CDAF_DESKTOP_PYTHON = (Resolve-Path .venv\Scripts\python.exe).Path
npm start --prefix desktop -- --project .\experiment
```

## Installer

Build the frontend and wheel from a clean checkout; a reused setuptools `build/lib` can retain obsolete hashed assets. Verify the wheel before packaging. Supply a relocatable standalone Python distribution with this wheel and `[research,tables,views]` installed under `.work/desktop-python`. A normal venv is not a relocatable distribution. This candidate uses a privately copied official uv-managed CPython 3.13 runtime; the original runtime is preserved.

```powershell
npm run build --prefix web
python -m build --wheel
python scripts/verify_wheel.py
python scripts/prepare_desktop_runtime.py
npm ci --prefix desktop
npm run package --prefix desktop
```

The lockfile fixes Electron/builder versions. The NSIS installer in `dist/desktop/` carries Chromium and private Python and creates one shortcut. No global `cdaf` PATH entry is needed; use Open Terminal. Scientific code can select its own interpreter. The current installer is unsigned and is not a published GitHub release.

If binary downloads fail, builder accepts an already-verified local distribution through `--config.electronDist=ABSOLUTE_PATH_TO_ELECTRON_DIST`; retain TLS and checksum checks.

Run `npm test --prefix desktop` and `npm run test:startup --prefix desktop` (the latter requires the private runtime). Then set `CDAF_DESKTOP_TEST_EXE` to the packaged or installed executable and run `node desktop/tests/project.cjs`, `node desktop/tests/lifecycle.cjs`, `node desktop/tests/terminal.cjs`, and `node desktop/tests/shutdown.cjs`. These check a real cross-module matrix run, the header terminal action, embedded PTYs, visible exit action, owned state removal and port release. Set `CDAF_DESKTOP_ENTRY_KIND=installed` only when testing the actual installation. Startup faults cover missing Python, a crashed renderer and an unavailable service. macOS/Linux desktop installers remain unvalidated.

The default entry opens the project workspace. `--single` opens the compatible single-file workspace. After provisioning and verifying the private interpreter once, `python scripts/prepare_desktop_runtime.py --package-only` updates and byte-verifies the exact current wheel without changing scientific dependencies. `scripts/verify_wheel.py` also exercises both installed multi-file script and module entries, using Chinese paths and real exported cross-module values.

Set `CDAF_DESKTOP_TEST_SHORTCUT` to the real installed shortcut and run `node desktop/tests/installed-entry.cjs` to verify its exact target/default arguments, core version, themed header, visible exit and port cleanup. This check opens the real user workspace without executing code. Run the data inventory check before and after. `desktop/tests/project-scale.cjs` accepts `CDAF_DESKTOP_SCALE_PROJECT`, an owned pre-indexed 1,000-file fixture; it records the actual rendered count and alternating selection latency rather than claiming an API slice count was rendered.

Synthetic desktop journeys use their own `--user-data-dir` and fixture root; they must not overwrite the real application profile. The exact installed-shortcut check intentionally uses the real profile, accepts a healthy chooser or restored project, and keeps its startup screenshot private. Published project screenshots come only from synthetic fixtures.

On Windows, run installed-user-data inventory checks with the bundled private Python. Microsoft Store Python can expose a virtualized AppData directory with a different database even when the visible path is identical. Verify the live desktop service identity and compare the original native baseline; do not merge or replace these directories.
