# CLI reference

The primary command is `cdaf`. Project commands accept `--project PATH` (`-p`); omitted paths resolve from the current directory's `flow.yaml`. `studio` can also launch a user workspace from any empty directory. Help is available with `-h` or `--help`. Terminal output is readable; piped output is JSON. Put global `--json`, `--human` or `--no-color` before the command. JSON file input is UTF-8 and `-` reads stdin where supported.

| Command | Purpose / important options |
|---|---|
| `cdaf --version` | Print package version |
| `cdaf capabilities` | Shared Web/CLI feature catalogue |
| `cdaf doctor -p PATH` | Installation, shipped UI, project compilation and provider readiness; no secret values |
| `cdaf shortcut --directory PATH` | Native launch/stop shortcuts; defaults to Desktop; optional `-p PATH` binds a project |
| `cdaf projects list` | List registered directories and availability |
| `cdaf projects create --name NAME --template data-pipeline` | Blank/data-pipeline/business-flow/nested-composite; optional `--target` empty directory |
| `cdaf projects add PATH` | Register an existing flow.yaml directory |
| `cdaf projects remove ID` | Unlink catalogue entry; files remain on disk |
| `cdaf init --target PATH` | Create an empty contract-first project without overwriting `flow.yaml` |
| `cdaf demo --target PATH --example data-pipeline --serve` | Create an empty-destination example, verify success/failure, optionally launch Studio |
| `cdaf check -p PATH` | Validate model, graph, bindings, interfaces and probes; exit 1 if invalid |
| `cdaf plan -p PATH` | Inspect flat order, dependencies, public boundary maps and diagnostics |
| `cdaf run -p PATH --input INPUT.json` | New execution: exit 0 completed/passed, 2 quality failure, 1 execution failure |
| `cdaf studio -p PATH --port 8765 --no-open` | Session-protected loopback service with bundled UI |
| `cdaf studio --workspace` | User workspace regardless of cwd; `--home PATH` or `CDAF_HOME` chooses data directory |
| `cdaf studio --status` | Inspect the matching managed service without starting it |
| `cdaf studio --foreground` | Terminal-attached mode; Ctrl+C stops it |
| `cdaf studio -p PATH --background` | Start/reuse an independent background Web UI; return after authenticated readiness |
| `cdaf studio -p PATH --stop` | Graceful authenticated shutdown of this project's managed background service |
| `cdaf scan -p PATH --source-dir src` | File-qualified symbol candidates; topology remains authored |
| `cdaf runs -p PATH` | List run history |
| `cdaf runs ID -p PATH --events --after SEQUENCE` | Inspect paginated evidence; omit `--events` for run details |
| `cdaf runs ID -p PATH --action pause` | Pause/resume/cancel a live local run |
| `cdaf view -p PATH` | Inspect view JSON and view revision |
| `cdaf view -p PATH --input VIEW.json --base-revision REVISION` | Save view preferences independently of execution semantics |
| `cdaf context MODULE -p PATH --level L2` | Inspect actual sanitized context and effective binding visibility |
| `cdaf generate MODULE -p PATH --candidate FUNCTION.py` | Static-validated code proposal from a local candidate |
| `cdaf generate MODULE -p PATH --provider mock` | Fixture-specific offline candidate; default provider |
| `cdaf generate MODULE --provider openai --model MODEL -p PATH` | Optional provider with explicit model/environment credentials |
| `cdaf propose SPEC.json -p PATH --title TITLE` | Architecture JSON proposal from a human or external AI agent |
| `cdaf review -p PATH` | List proposals |
| `cdaf review ID -p PATH` | Inspect stored proposal |
| `cdaf review ID -p PATH --accept` | Explicit acceptance with current/base revision and source recheck |
| `cdaf review ID -p PATH --reject` | Reject pending/invalid proposal |
| `cdaf review ID -p PATH --rollback` | Create inverse code proposal; acceptance remains separate |
| `cdaf probe 'EXPRESSION' SAMPLE.json` | Strict-Boolean sample preflight; `--input-boundary` evaluates input |
| `cdaf export -p PATH --format html --output view.html --run ID` | Sanitized historical evidence; formats html/svg/png/mermaid/json |
| `cdaf export -p PATH --format html --output design.html --current` | Current reviewed architecture, without historic execution events |
| `cdaf export -p PATH --format otel --output trace.json` | OTLP/JSON evidence for an observed run |
| `cdaf export -p PATH --format archify-json --output design.json` | Typed Archify design IR |
| `cdaf export -p PATH --format archify --archify-checkout PATH --output design.html` | Optional fixed-commit Node renderer plus receipt |
| `cdaf migrate OLD --destination NEW --resolutions bindings.json` | Preview legacy migration; add `--apply` for a separate empty destination |
| `cdaf clean -p PATH` | Cache only; `--runs-before ISO_TIMESTAMP` explicitly prunes completed evidence |

In PowerShell use single quotes around expressions containing `$input` or `$output`; otherwise PowerShell expands those variables before CDAF receives them. For candidate files, submit one function with the exact signature/decorators of the target. Full-file replacements and arbitrary extra imports are rejected.

History cutoffs compare actual timestamps, including timezone offsets. A cutoff without an offset is interpreted as UTC. Queued, running and paused runs are preserved. Run controls use the shared project event database, so another authenticated local Studio for the same project can resume or cancel its active run.

Windows checkout users can double-click `启动工作台.cmd` / `停止工作台.cmd`. [Local deployment](local-deployment.md) describes lifecycle, logs, project and port selection. Studio defaults to background operation and selects a free port in 8765–8785. An explicit occupied port is rejected. `--foreground` opts into terminal ownership. Native shortcuts use the installed interpreter; regenerate them after moving or removing that environment. `cdaf-studio` opens the workspace without a console on Windows.

`sfa` aliases the new CLI during the compatibility period. Old CLI commands use `sfa legacy ...` or `python -m sfa ...`. `python -m contract_driven_ai_flow ...` is equivalent to `cdaf ...` and works without adding a virtual environment's Scripts directory to PATH.
