# SFA — Semantic Flow Architecture

[![GitHub](https://img.shields.io/badge/GitHub-iyohesohoka646--dotcom%2FSFA-blue?logo=github)](https://github.com/iyohesohoka646-dotcom/SFA)

**SFA is a programming paradigm that first defines the structure, then lets AI fill in the code.** Engineers predefine each module’s input/output contracts and data flow directions. AI then generates implementations module by module under the constraints of these contracts. At runtime, input and output snapshots are automatically recorded at every module boundary.

The core difference from conversational AI programming (Cursor, Copilot, etc.): system structure is persisted as machine‑readable metadata in the `.sfa/` directory, not scattered across chat logs and source code. When a module is modified, AI never touches module boundaries or data flows—those are decided by humans alone.

```
Engineer → defines modules + contracts + data flow topology
AI      → generates implementations module by module within contracts (never crosses boundaries)
Runtime → automatically snapshots every module boundary; locate problems via data summaries, not by reading code
```

## What Problem It Solves

Conversational AI programming has three structural issues:

1. **System structure is invisible.** Dependencies between modules exist only in the developer’s mind; AI neither knows nor maintains them. Every change requires the developer to rebuild structural awareness from the code text.
2. **AI context is uncontrolled.** AI can read the entire project; a single change may affect unrelated modules or even modify the interface contracts between modules arbitrarily.
3. **Debugging relies on reading code.** When something goes wrong, you can only ask AI to explain the logic or read line by line—there is no module‑level input/output view.

SFA addresses these by:

- **Explicitly** representing module boundaries and interface contracts as JSON Schema, stored in `.sfa/modules/{name}/contract.json`
- Defining the data flow (module → pipe → module) as a directed graph, stored in `.sfa/pipeline.yml`
- When generating code, AI only sees the contract of the current module + upstream module information according to visibility levels; it **cannot see downstream**
- After each run, automatically saving input/output/duration snapshots at every module boundary, so problems can be pinpointed directly to a module

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Module** | A computational unit, corresponding to a piece of Python code. Can be atomic (single source file) or composite (nested sub‑modules and sub‑pipes). |
| **Contract** | The interface specification of a module: Input Schema, Output Schema (JSON Schema format), and a natural language summary. Modules do not share memory; they communicate only through the data formats defined by contracts. |
| **Pipe** | A directed edge connecting two modules, indicating that data flows from the upstream module’s output to the downstream module’s input. |
| **Snapshot** | The actual input/output data, duration, and status automatically recorded at module boundaries after each run. Stored in `.sfa/snapshots/{run_id}/{module}.json`. |
| **Probe** | A non‑intrusive observer attached to a pipe. Two types: Router (conditional branch recording) and Assertion (assertion validation). Does not modify the data flow. |
| **Visibility Levels (L1–L4)** | Parameters on a pipe that control how much upstream information AI can see when generating a downstream module. L1: schema only, L4: full source code. Default is L2. |

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/iyohesohoka646-dotcom/SFA.git
cd SFA
pip install .
```

After installation, the `sfa` command becomes available in your current environment.

For development installation (editable mode + test tools):

```bash
pip install -e ".[dev]"
```

To enable LLM integration (requires an API key; replaces the built‑in mock provider):

```bash
pip install ".[ai]"
```

The built‑in mock provider requires no API key and is suitable for offline demos and testing.

## Quick Start

Run the following commands in your working directory. The final output will be a completed pipeline with its snapshots, no API key required.

```bash
# 1. Initialize the project, create .sfa/ directory and sfa.yml config file
sfa init

# 2. Edit source_dir in sfa.yml to point to your code directory, then extract code elements
sfa extract

# 3. Define modules from the extracted elements (contracts are auto‑inferred from function signatures)
sfa module add --name loader --entry load_data
sfa module add --name scorer --entry score

# 4. Connect pipes to define data flow directions
sfa pipe add loader scorer

# 5. Let AI generate module implementations (mock mode outputs function skeletons; can be connected to a real LLM)
sfa generate scorer

# 6. Execute the pipeline in topological order, with automatic snapshots at every module boundary
sfa run --input input.json

# 7. Observe the results—without reading code, just data summaries
sfa observe          # status lights for all modules + input/output summaries
sfa observe scorer   # detailed snapshot of a single module

# 8. Index and visualise
sfa list             # table: module name, type, last run status, one‑line input/output summary
sfa graph            # ASCII data flow graph
sfa graph scorer     # neighbourhood subgraph around the scorer module
```

Sample `sfa list` output:

```
ID          Name        Type     Status  Input                                           Output
----------  ----------  ------  ----    ----------------------------------------------  ----
loader      loader      Atomic  OK      {"seed": 42}                                    {"rows": [...], "n": 2}
scorer      scorer      Atomic  OK      {"features": [43.0, 85.0]}                      {"score": 0.64}
```

Sample `sfa graph` output:

```
Top‑level data flow graph (3 modules, 2 pipes):

  [loader] --> [scorer]
  [scorer]
```

## Visibility Levels

The visibility level on a pipe controls how much upstream context AI can see when generating a downstream module. This is the core mechanism by which SFA limits the scope of AI behaviour.

| Level | Upstream information visible to AI |
|-------|------------------------------------|
| L1    | Upstream module’s Output Schema only |
| L2    | L1 + upstream module’s natural‑language summary + input/output examples (default) |
| L3    | L2 + upstream module’s function signatures |
| L4    | L3 + full source code of the upstream module |

Information about **downstream modules is never visible to AI**—generation is strictly local.

## Command Reference

All commands accept `--project/-p` to specify the project root (defaults to the current directory).

### Project Management

| Command | Description |
|---------|-------------|
| `sfa init [--target DIR] [--force]` | Create `.sfa/` metadata and `sfa.yml` in the target directory |
| `sfa status [--project DIR]` | Project overview: configuration, counts of elements/modules/pipes/probes, last run status |
| `sfa clean [--project DIR] [--yes]` | Clear generated data in `.sfa/`, keeping `sfa.yml` |

### Code Extraction

| Command | Description |
|---------|-------------|
| `sfa extract [--project DIR]` | Parse Python files in `source_dir` using tree‑sitter, generate `.sfa/elements.json` |

### Modules & Pipes

| Command | Description |
|---------|-------------|
| `sfa module add -n NAME -e ENTRY [--validation strict\|lenient\|none]` | Create a module with auto‑inferred contract (idempotent) |
| `sfa module remove ID` | Delete a module |
| `sfa module list` | List all modules |
| `sfa pipe add SRC TGT [--visibility L1–L4]` | Connect a pipe (idempotent) |
| `sfa pipe remove ID` | Delete a pipe |
| `sfa pipe list` | List all pipes |
| `sfa group IDS… -n NAME` | Bundle several modules into a composite module |
| `sfa ungroup ID` | Unpack a composite module |
| `sfa drill ID` | Drill into the internal view of a composite module |

### AI Generation

| Command | Description |
|---------|-------------|
| `sfa generate ID [--yes]` | Generate an implementation for the module (shown as a diff; written after human confirmation) |
| `sfa rollback ID [--version V]` | Roll back module code to a historical version |

### Execution & Observation

| Command | Description |
|---------|-------------|
| `sfa run [--input FILE]` | Execute the pipeline in topological order, snapshots at every module boundary |
| `sfa observe [ID] [--run RUN_ID]` | Show run summary or detailed snapshot for a specified module |
| `sfa list` | Tabular display of all modules (name, type, status, input/output summary) |
| `sfa graph [ID] [--hops N]` | ASCII data flow graph / neighbourhood subgraph of a specified module |

### Probes

| Command | Description |
|---------|-------------|
| `sfa probe add router PIPE -c EXPR --on-true T --on-false F -n NAME` | Create a router probe on a pipe |
| `sfa probe add assertion PIPE -c EXPR -n NAME` | Create an assertion probe on a pipe |
| `sfa probe list` | List all probes |
| `sfa probe remove ID` | Remove a probe |

Probe expressions use a restricted DSL: `$output.field`, subscript `$output[0]`, comparisons/arithmetic/booleans, constants. Field paths are statically validated at definition time and must exist in the upstream module’s Output Schema.

```
sfa probe add assertion pipe_scorer_positive -c '$output.score >= 0.5' -n score_threshold
```

## Example

[`examples/pipeline/`](./examples/pipeline) contains a complete 5‑module data processing pipeline with assertion and router probes. Run it with one command:

```bash
cd examples/pipeline
python demo.py
```

The script sequentially executes `init → extract → module add ×5 → pipe add ×4 → probe add ×2 → run → observe → list → graph`—no API key required. It can be run repeatedly.

Sample `sfa observe` output:

```
Run f25582be... (success)
OK  loader       Input={"seed": 42}   Output={"rows": [...], "n": 2}  0ms
OK  featurizer   Input={"rows": [...], "n": 2}   Output={"features": [43.0, 85.0]}  0ms
OK  scorer       Input={"features": [43.0, 85.0]}   Output={"score": 0.64}  0ms
OK  positive     Input={"score": 0.64}   Output={"label": "positive", "score": 0.64}  0ms
OK  negative     Input={"score": 0.64}   Output={"label": "negative", "score": 0.64}  0ms

Probes (2):
  [PASS] score_threshold         → $output.score >= 0.5
  [ROUTE] high_confidence_router → condition false, branch=on_false/negative
```

## Design Documents

Three Chinese design documents are available in the project root, describing SFA’s design intent from different perspectives:

- [`total.md`](./total.md) — Project vision: why SFA, core philosophy
- [`architecture.md`](./architecture.md) — System architecture: domain model, layered design, data storage specifications
- [`road.md`](./road.md) — Development roadmap: M1–M6 milestones and completion criteria

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[MIT](./LICENSE)
