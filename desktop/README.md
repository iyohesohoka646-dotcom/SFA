# Windows desktop shell

Electron wraps the same scientific Web UI and owns only its backend. Node integration is disabled; preload is isolated/sandboxed and navigation is restricted to the local service origin. Startup, retry and close cleanup are tested. Open Terminal uses a fixed PowerShell file with structured arguments.

## Development

```powershell
npm ci --prefix desktop
$env:CDAF_DESKTOP_PYTHON = (Resolve-Path .venv\Scripts\python.exe).Path
npm start --prefix desktop -- --project .\experiment
```

## Installer

Build the frontend and wheel first. Supply a relocatable standalone Python distribution with this wheel and `[research,tables]` installed under `.work/desktop-python`. A normal venv is not a relocatable distribution. This candidate uses a privately copied official uv-managed CPython 3.13 runtime; the original runtime is preserved.

```powershell
npm run build --prefix web
python -m build --wheel
npm ci --prefix desktop
npm run package --prefix desktop
```

The lockfile fixes Electron/builder versions. The NSIS installer in `dist/desktop/` carries Chromium and private Python and creates one shortcut. No global `cdaf` PATH entry is needed; use Open Terminal. Scientific code can select its own interpreter. The current installer is unsigned and is not a published GitHub release.

If binary downloads fail, builder accepts an already-verified local distribution through `--config.electronDist=ABSOLUTE_PATH_TO_ELECTRON_DIST`; retain TLS and checksum checks.

Run `npm test --prefix desktop`, then set `CDAF_DESKTOP_TEST_EXE` to the installed executable and run `node desktop/tests/lifecycle.cjs`. This opens the native window and verifies owned state removal and port release. macOS/Linux desktop installers remain unvalidated.
