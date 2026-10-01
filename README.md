# Contract-Driven AI Flow

**Visual Flow-Based Programming for AI-Assisted Development**

Visual flow-based programming with explicit contracts, bounded AI code changes, and runtime probes.
**Design the flow. Review the contracts. Generate modules. Inspect real executions.**

[简体中文](README.zh-CN.md) · [Getting started](docs/workflow.md) · [CLI reference](docs/cli.md) · [Web/CLI coverage](docs/web-cli-delivery.md) · [Architecture](docs/architecture.md)

The local Studio is available in [draft PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1). Install the feature branch with Python 3.11+ and Git, then open the bundled Web UI:

```console
python -m pip install "git+https://github.com/iyohesohoka646-dotcom/SFA.git@feat/contract-driven-ai-flow"
python -m contract_driven_ai_flow studio
python -m contract_driven_ai_flow shortcut
```

![Local Studio showing a real completed execution with a failed quality assertion](docs/assets/studio-runtime.png)

Build a controllable, composable Python code structure. Humans define module interfaces and data dependencies; AI proposes implementations inside those boundaries. Review architecture and code separately, then inspect revision-bound execution evidence on the same canvas.

The [offline case gallery](docs/examples/index.html) contains three real examples, each with success and quality-failure evidence. Download or open the HTML files locally; they include their data and need no server. See the [data pipeline](docs/examples/data-pipeline/architecture.svg), [business flow](docs/examples/business-flow/architecture.svg), and [nested composite](docs/examples/nested-composite/architecture.svg) directly on GitHub.

## Why use it?

- **Explicit interfaces:** JSON Schema contracts and named input bindings reject missing ports, duplicate writers, cycles and illegal composite crossings before execution.
- **Bounded implementation changes:** proposals preserve the target signature and decorators, check all imports, and use LibCST to replace only its body. Source changes during review invalidate the proposal.
- **Reviewable architecture:** contracts, ports, probes and grouping are authored in `flow.yaml`. Moving a node changes its view, not program semantics. External AI agents can submit architecture proposals for review.
- **Visible evidence:** child Python processes transfer JSON values without shared references. Assertions, metrics, captures, real decisions and read-only branch observations have distinct behavior and status.
- **Local operation:** Python installs include the compiled React workbench. No Node.js, API key or cloud account is needed to try the examples.

## Quick start, without an API key

On Windows, double-click **[启动工作台.cmd](启动工作台.cmd)** in this checkout to prepare a project environment and open the independent local Web UI. It opens your project workspace, with a ready-to-run example, new-project templates and existing-folder registration. **[停止工作台.cmd](停止工作台.cmd)** stops the workspace service. See [local deployment](docs/local-deployment.md).

Requires Python 3.11+. From this checkout or an unpacked source release, in an activated virtual environment:

```console
python -m pip install .
cdaf studio
```

You can launch from an empty working directory. Studio starts in the background, waits for authenticated readiness, and opens a fresh browser session. It reuses the running service; closing the terminal or browser leaves it running. Inside an existing project it opens that project; use `cdaf studio --workspace` for all projects. A free port is selected automatically; `--port` requests a specific port. `cdaf studio --stop` stops the matching service.

After installation, `cdaf shortcut` creates native launch/stop shortcuts on your Desktop; `cdaf-studio` is the windowless application entry. `cdaf doctor` diagnoses the installation. Ordinary operation needs Python 3.11+; Node.js is only needed for frontend development or the optional Archify renderer.

For a self-checking demo, run `cdaf demo --target cdaf-demo --serve`. It executes built-in implementations twice, verifies `completed / passed` and `completed / failed`, and writes an offline HTML view. It refuses to overwrite a nonempty destination.

`cdaf demo --example business-flow --target business-demo` exercises an HTTP call against a local fixture and an actual Decision branch. `--example nested-composite` demonstrates two levels of public input/output mappings.

This is a local **0.2.0 release candidate**. The current remote is still named [SFA](https://github.com/iyohesohoka646-dotcom/SFA); the Python distribution is `contract-driven-ai-flow`, the import is `contract_driven_ai_flow`, and the command is `cdaf`. PyPI publication and remote rename are separate release actions. [Release status and validation](docs/release.md) distinguish tested behavior from pending platform checks.

## One complete edit and debug cycle

1. Open **Architecture**, select `Summarize`, and edit its contract or explicit input binding. **Validate** displays compiler diagnostics; **Review & save** creates an architecture proposal.
2. In **Review**, inspect the diff and diagnostics, then accept the change. New Python modules receive a skeleton that still requires implementation.
3. Submit a candidate function from **Context → Candidate**, or create one with `cdaf generate ingest --project cdaf-demo`. Generation only proposes a change; acceptance is explicit.
4. Choose **Runs → Success fixture → Run with this input**. Nodes and transfers reflect recorded events. The failure fixture demonstrates that a module can complete while its quality assertion fails.
5. In **Probes**, preview a strict Boolean rule such as `$output.mean <= 5`, choose `continue`, `block`, `pause` or `breakpoint`, then review the architecture change. Inspect input/output summaries and the timeline; export sanitized evidence when needed.

The offline generator implements only reviewed contract fixtures and rejects other inputs. It is useful for exercising the proposal/review loop, and makes no claim to generalize. The built-in demos use real general-purpose Python implementations. Optional OpenAI/Anthropic adapters use explicit models and environment credentials; live provider calls are outside the offline acceptance suite.

## Core concepts

| Concept | Behavior |
|---|---|
| `ProjectSpec → ExecutionPlan → RunEvent` | One versioned model feeds the CLI, compiler, HTTP API and Studio. |
| Module / Contract | A file-qualified Python symbol, a composite public interface, or a deterministic Decision; contracts include concrete fixtures. |
| PortBinding | An input comes from a project JSON Pointer, upstream output, or literal/default. Multiple writers require a merge module. |
| Composite | Public inputs and outputs map to an internal graph. Declared interfaces are checked before flattening and whole-object contracts are checked at runtime. |
| Probe / Control | Observers return `pass / fail / error / skipped`; scheduling policies handle block, pause and resume independently. |
| Context L1–L4 | Schema, fixtures, identity, then authorized symbol source. A request cannot exceed a binding's visibility cap. |
| ChangeSet | A staged architecture or implementation diff tied to a base revision; accepted code can be rolled back through an inverse proposal. |
| Evidence / View | `.cdaf/` contains SQLite events and bounded artifacts; `flow/views.json` stores position/theme separately from executable semantics. |

## Capabilities and limits

Studio has a persistent project workspace plus Architecture, Runs, Probes and Review views, explicit binding forms, contract/group editors, undo/redo, search, path focus, collapsible composites, keyboard interaction, themes and responsive panels. Project tools expose plan/source inspection, architecture import, integration exports, migration, storage, installation diagnosis and the shared command catalogue. Run replay uses historical models and events; it never automatically reruns external side effects. HTML, SVG, PNG, Mermaid and JSON exports work offline; optional exporters provide OTLP/JSON and a pinned Archify design view.

CLI output is readable in a terminal and JSON when piped; `cdaf --json …` explicitly selects JSON, and `--human` selects readable output. `cdaf run --input -` reads JSON from stdin. See [the coverage matrix and design sources](docs/web-cli-delivery.md).

The first version executes local Python DAGs, serially by default, with bounded concurrency, deadlines, cancellation, and opt-in idempotent retries. It validates actual data when a schema relation is explicitly declared dynamic. The conservative compiler returns “unknown” for schema constraints it cannot prove. Local processes inherit the user's file/network permissions; this is process isolation, not an OS security sandbox. Full capture is opt-in, bounded and retained for a configured period; default capture is a sanitized summary. See [privacy and execution](docs/architecture.md#execution-and-evidence).

Port names and interface schemas are authored explicitly. Existing-code scanning lists candidates, and does not silently promote inferred calls to execution edges. Class instance construction, cyclic execution, multi-language runtimes, collaboration and distributed scheduling are not implemented. Probe expressions are a bounded version-1 language; they are not CEL itself.

## Related work

[Archify](https://github.com/tt-a1i/archify) informs typed diagram exports and validation receipts; [LikeC4](https://github.com/likec4/likec4) informs multiple views of one model; [Apache Hamilton](https://github.com/apache/hamilton) and [NoFlo](https://github.com/noflo/noflo) provide useful Python dataflow and public-port patterns. [Node-RED](https://nodered.org/docs/user-guide/editor/sidebar/debug) informs debug filtering, [OpenTelemetry](https://opentelemetry.io/docs/concepts/signals/traces/) supplies standard span/link export, and [OpenSpec](https://github.com/Fission-AI/OpenSpec) demonstrates reviewable specification changes. [Detailed comparison and design decisions](docs/research.md) describe the overlap without claiming unsupported differences.

## Documentation and contribution

[Workflow](docs/workflow.md) · [CLI](docs/cli.md) · [Architecture/API](docs/architecture.md) · [Migration](docs/migration.md) · [Examples and evidence](docs/examples/index.html) · [Release validation](docs/release.md) · [Contributing](CONTRIBUTING.md)

`cdaf` is the primary interface. `sfa` aliases it for one major version; legacy commands are explicitly available as `sfa legacy …` or `python -m sfa …`. Migration preserves originals and reports ambiguous bindings. `clean` clears caches by default and preserves architecture definitions.

MIT. Built on the original SFA codebase; third-party notices are in [NOTICE.md](NOTICE.md).
