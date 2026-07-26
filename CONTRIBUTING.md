# Contributing to SFA

Thanks for your interest in contributing to **Semantic Flow Architecture**.
SFA is a structure-centric programming paradigm where engineers design the
data-flow graph and AI fills in module implementations. This guide will get
you set up and productive.

## Development setup

SFA is a CLI tool: install it once and the `sfa` command is available
globally — you do not need a virtualenv per project. A venv is still
recommended for development to keep dependencies isolated.

```bash
# clone/copy the repo, then from the repo root:
python -m venv .venv          # optional but recommended for dev
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"       # editable install: `sfa` command + pytest
```

The `dev` extra installs `pytest`. The `ai` extra (`pip install -e ".[ai]"`)
adds the OpenAI and Anthropic SDKs if you want to exercise real LLM
generation; the built-in `mock` provider needs no extra dependencies.

## Running tests

```bash
pytest tests/ -v
```

Tests use `typer.testing.CliRunner` and the `tmp_path` fixture so they are
isolated and offline. Every CLI command has at least one smoke test; engine
modules (`contract`, `execute`, `probe`, …) have dedicated unit tests.

## Code style

- **No comments in source code.** The codebase deliberately keeps `src/sfa/`
  comment-free; intent lives in docstrings (module + function level) and in
  the design documents at the repo root.
- Follow the existing module pattern: one engine per file
  (`topology.py`, `contract.py`, `execute.py`, …) with a pure functional
  core and thin Typer wiring in `cli.py`.
- Error messages always include the offending module name, the relevant file
  path, and an actionable hint — see `SFAError` usages throughout.
- Target Python 3.11+.

## Project layout

```
src/sfa/        the package (engines + cli)
tests/          pytest suite
examples/       runnable demo projects
architecture.md system architecture (中文, for AI executors)
total.md        project vision (中文)
road.md         milestone roadmap (中文)
```

The three `*.md` design documents at the repo root are written in Chinese
and addressed to AI executors; they are the source of truth for design
intent. Read them before making non-trivial architectural changes.

## Pull requests

- Keep PRs focused: one feature or fix per PR.
- Include or update tests for any behavior change.
- Ensure `pytest tests/` passes before requesting review.
- Do not commit the `.sfa/` metadata directory (it is gitignored) — except
  generated artifacts belong to whoever runs the tool.

## License

By contributing you agree your contributions are licensed under the project's
[MIT license](./LICENSE).
