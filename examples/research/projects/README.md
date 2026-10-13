# Multifile research examples

Two dependency-free fixtures (`flat-lab`, `src-lab`) and one NumPy matrix example (`matrix-lab`) exercise real cross-file observations. They require no keys, network or model. The matrix example requires NumPy in the selected scientific interpreter.

The 0.6 project workbench opens these folders directly. The preserved installed 0.5.4 does not gain project features until upgraded. See the [project guide](../../../docs/research/projects.md).

For `matrix-lab`, save a Script entry `main.py`, run, and inspect `prepare.build_dataset.X` and `compute.covariance.C`. Bind `check.finite` to C and run with `--nan` to demonstrate completed computation with failed numerical quality. Each default automatic view, additional table and heatmap is a separate effective probe view.

## Layout

```
flat-lab/                 script entry
  main.py                 authored entry, argparse, prints str(score)
  prepare.py              deterministic random.Random(seed) dataset
  compute.py              named calculation with a branch and a loop
  checks.py               small numeric verification
src-lab/                  src-layout package, module entry
  pyproject.toml          setuptools build system, no external dependencies
  src/research_lab/
    __init__.py           import-marker counter (no side-effect files)
    main.py               python -m research_lab.main
    compute.py            dataset + calculation
```

`flat-lab` is run as a **script** (`main.py`); `src-lab` is run as a **module**
(`research_lab.main`). Both share the same shape: a prepared dataset, a named
calculation, a small check, and a final numeric `score`.

## Cross-file variables and scopes

`X` is deliberately reused. In `flat-lab/prepare.py` it is a local inside
`build_dataset`; in `flat-lab/compute.py` it is a separate local inside
`summarize`. The same holds in `src-lab/compute.py`. Reusing a name in two files
is normal Python: each binding lives in its own lexical scope, and a project run
keeps them as two distinct snapshots (different source file, different scope)
rather than one overwritten value.

## Success and failure

* Normal path: `main.py` prints `str(score)`; the observed `score` snapshot and
  the native stdout agree exactly. `score` is a real integer.
* Failure path: `--fail` makes `compute.summarize` raise a genuine `ValueError`
  *after* the dataset variable was captured. The native process exits non-zero,
  the run is marked failed, and the `compute.py` frame it reached is still
  published. This is a real exception, not an assertion planted by an observer.

## Native commands

Run the examples exactly as authored (no absolute machine paths, no install):

```powershell
# script entry
python -X utf8 examples/research/projects/flat-lab/main.py
python -X utf8 examples/research/projects/flat-lab/main.py --fail

# module entry: this project is NOT installed, so an explicit PYTHONPATH is required
$env:PYTHONPATH = (Resolve-Path examples/research/projects/src-lab/src)
python -X utf8 -m research_lab.main
```

`python -m research_lab.main` needs the `research_lab` package on the import
path. That path is an **actual authored environment value** (an explicit
`PYTHONPATH`, or a real installed package). Indexing detects a `src` layout and
derives module *names* for planning, but the parser's `source_roots` setting
does not silently rewrite `sys.path`: imports still resolve only through the
environment you authored.

## Public application API

Freeze an authored entry, execute the real program, wait for the submitted task, and
read the observed snapshots. Symbolic references (`interpreter_ref`,
`environment`) stay in repo config; their private values live in the host state
directory, never in the repository.

```python
from pathlib import Path
from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.workbench.models import RunConfiguration

host = Path('host-state')                                  # private env/interpreter refs
root = Path('examples/research/projects/flat-lab')
app = ProjectApplication(host)
try:
    project = app.open(root)                               # register metadata without executing project source
    revision = app.index(project.id)                       # never imports user code
    config = app.configuration(project.id)
    app.save_entries(                                       # freeze the authored entry
        project.id,
        [RunConfiguration(id='main', name='Main', kind='script', target='main.py')],
        expected_revision=config.revision,
    )
    plan = app.plan(project.id, 'main', revision_id=revision.id)
    task = app.execute(project.id, plan.id)                # real launch
    done = app.workbench(project.id).jobs.wait(task.id, 30)  # wait for this task
    run = app.research(project.id).store.run(done.run_id)
    snapshots = app.research(project.id).store.snapshots(done.run_id, limit=1000)
finally:
    app.close()
```

For `src-lab`, use `kind='module'`, `target='research_lab.main'`, and set
`environment=['PYTHONPATH']` on the `RunConfiguration`. The private value that
`PYTHONPATH` resolves to is written once into the host state, not the repo.

## What a run does and does not observe

* **Source-inert open/index.** Opening saves registry and workbench metadata; indexing saves parsed
  files and relationships. Neither imports or runs project source. Only the one entry you saved and planned is executed.
* **Capture boundaries.** Only indexed, in-root modules loaded through the
  standard source loader are traced. Stdlib, third-party code, non-standard
  loaders and subprocesses are reported as explicit coverage gaps instead of
  being silently instrumented.
* **Execution vs quality.** A completed run means the program ran to completion;
  it does not certify that the numbers are scientifically correct. Quality is a
  separate, explicit check (see `checks.verify`).
* **Frozen history.** A computation freezes a content-addressed manifest and
  verifies digests immediately before launching. Changing source requires a new computation plan; archived evidence remains
  bound to the original revision and is never replaced with current source.
* **Models are not needed.** These examples make no model calls. Any inference
  is an explicitly configured, separate concern.

## Acceptance

`tests/research/test_project_examples.py` copies each fixture into an isolated
temporary directory (the originals are never run in place or written to),
compares native stdout with the observed snapshots, checks the real failure
path, and confirms cross-file provenance. Each source fixture stays small
(<= 100 lines per file).
