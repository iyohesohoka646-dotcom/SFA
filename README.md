# SFA (Semantic Flow Architecture)

Structure-centric, AI-as-executor programming paradigm. Engineers design the
data-flow graph; AI fills in module implementations under strict contracts.

SFA flips the prevailing conversational-coding model: instead of the system
structure living implicitly in chat and code text, the **topology is fixed
first** (modules, contracts, pipes) and persisted as machine-readable
metadata in `.sfa/`. AI is then confined to generating the implementation
*inside* a single module's contract — it never decides data flow, module
boundaries, or system structure.


## Install

SFA is a regular Python CLI tool: install it once and the `sfa` command is
available everywhere — no per-project virtualenv required.

```bash
# clone/copy the repo, then from the repo root:
pip install -e ".[dev]"         # developers: `sfa` command + pytest (editable)
# or, for end users:
pipx install .                  # isolated install exposing `sfa` globally
```

Optional AI providers (real LLM generation):

```bash
pip install -e ".[ai]"          # OpenAI + Anthropic SDKs
# with pipx: pipx install ".[ai]"  or  pipx inject sfa openai anthropic
```

The built-in `mock` LLM provider works with no API key and no extra deps —
handy for offline demos and tests.

## Quick start

```bash
# 1. Scaffold .sfa/ metadata + sfa.yml
sfa init

# 1b. Check project health/overview at any time
sfa status

# 2. Point source_dir at your code (edit sfa.yml), then extract elements
sfa extract

# 3. Define modules from extracted elements (contracts auto-inferred)
sfa module add --name "预处理" --entry "preprocess"
sfa module add --name "推理"   --entry "infer"

# 4. Connect the data-flow pipe (visibility L1-L4 gates upstream context)
sfa pipe add 预处理 推理 --visibility L2

# 5. Generate implementation under contract (diff for human approval)
sfa generate 推理            # review the diff, accept or reject
#    or skip the prompt: sfa generate 推理 --yes

# 6. Run the whole pipeline topologically, snapshotting every boundary
sfa run --input input.json

# 7. Observe results without reading code
sfa observe                 # run summary (status lights + I/O)
sfa observe 推理            # detailed snapshot for one module

# 8. Index & visualize
sfa list                    # all modules: type, status light, I/O one-liner
sfa graph                   # full top-level data-flow diagram
sfa graph 推理              # 1-2 hop neighborhood around a module
```

## Visibility levels

Pipe visibility controls how much upstream context the AI sees when
generating a module — a core SFA mechanism for containing intent:

| Level | Upstream context included |
|-------|---------------------------|
| L1    | Output schema only |
| L2    | L1 + natural-language summary + I/O samples (default) |
| L3    | L2 + upstream function signatures |
| L4    | L3 + full upstream source code |

Downstream modules are **never** included — generation is strictly local.

## Command reference

| Command | Description |
|---------|-------------|
| `sfa init [--target DIR] [--force]` | Create `.sfa/` metadata + `sfa.yml` |
| `sfa status [--project DIR]` | Project overview: config, elements, module/pipe/probe counts, last run |
| `sfa clean [--project DIR] [--yes]` | Reset `.sfa/` metadata (keep `sfa.yml`) |
| `sfa extract [--project DIR]` | Tree-sitter parse → `.sfa/elements.json` |
| `sfa module add -n NAME -e ENTRY [--validation strict\|lenient\|none] [--force]` | Create module + infer contract (idempotent; `--force` rebuilds) |
| `sfa module remove ID` / `sfa module list` | Manage modules |
| `sfa pipe add SRC TGT [--visibility L1-L4] [--force]` | Connect a data-flow pipe (idempotent; `--force` rebuilds) |
| `sfa pipe remove ID` / `sfa pipe list` | Manage pipes |
| `sfa group IDS… -n NAME` | Pack modules into a composite |
| `sfa ungroup ID` / `sfa drill ID` | Unpack / inspect a composite's interior |
| `sfa generate ID [--yes]` | AI-generate implementation under contract (diff) |
| `sfa rollback ID [--version V]` | Restore a prior code version |
| `sfa run [--input FILE]` | Execute pipeline topologically + snapshot boundaries |
| `sfa observe [ID] [--run RUN_ID]` | View run summary / module snapshot |
| `sfa probe add router PIPE -c EXPR --on-true T --on-false F -n NAME` | Routing probe |
| `sfa probe add assertion PIPE -c EXPR -n NAME` | Assertion probe |
| `sfa probe list` / `sfa probe remove ID` | Manage probes |
| `sfa list` | Table: modules, type, recent-run status light, I/O one-liner |
| `sfa graph [ID] [--hops N]` | ASCII data-flow diagram / neighborhood |

All commands accept `--project/-p` to target a project root other than the
current directory.

## Probes

Probes attach to pipes and observe data **without** altering flow:

- **Router** — evaluates a condition on the source module's output and records
  which branch (`on_true`/`on_false`) was selected. (MVP routing is
  observation-only; it records the decision rather than re-routing data.)
- **Assertion** — evaluates a condition; failure records a warning with an
  expected-vs-actual comparison.

The probe DSL is a restricted expression subset: `$output.field`, subscripts
(`$output[0]`, `$output[-1]`), comparisons, arithmetic, booleans, and
constants. Field paths are statically validated against the upstream output
schema at definition time.

```
sfa probe add assertion pipe_评分_正向预测 -c '$output.score >= 0.5' -n "分数阈值"
```

## Example

A complete, runnable demo lives in [`examples/pipeline/`](./examples/pipeline):
a 5-module data-processing pipeline with a router probe and an assertion
probe. Run it with one command:

```bash
cd examples/pipeline
python demo.py
```

This builds the `.sfa/` metadata from scratch, runs the pipeline, and prints
the `observe` / `list` / `graph` output. See the example's own README for a
step-by-step walkthrough.

## Design documents

The repo root holds three design documents (in Chinese, addressed to AI
executors):

- [`total.md`](./total.md) — project vision and core philosophy
- [`architecture.md`](./architecture.md) — system architecture and domain model
- [`road.md`](./road.md) — milestone roadmap (M1–M6)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup, test
conventions, and PR guidelines.

## License

MIT — see [LICENSE](./LICENSE). Copyright (c) 2026 SFA Contributors.
