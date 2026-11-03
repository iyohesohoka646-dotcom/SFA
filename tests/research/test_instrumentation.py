import json
import traceback
from pathlib import Path

import numpy as np
import pytest


def observe(source, filename="analysis.py", **options):
    from contract_driven_ai_flow.research.agent.instrument import InstrumentPolicy, instrument
    from contract_driven_ai_flow.research.agent.sdk import TraceSession
    from contract_driven_ai_flow.research.agent.transport import EventTransport

    trace = TraceSession("script", EventTransport())
    compiled = instrument(source, filename, InstrumentPolicy(**options))
    namespace = compiled.execute(trace)
    return namespace, trace.transport.drain(), compiled.coverage


def snapshots(events, name):
    return [e["payload"]["snapshot"] for e in events if e["kind"] == "value.observed" and e["payload"]["snapshot"]["name"] == name]


def test_assignment_expression_is_evaluated_once():
    source = "import numpy as np\ncalls = []\ndef draw():\n    calls.append('draw')\n    return np.arange(4)\nX = draw()\nY = (X + 1) * 2\n"
    result, events, _ = observe(source)
    assert result["calls"] == ["draw"]
    np.testing.assert_array_equal(result["Y"], [2, 4, 6, 8])
    assert snapshots(events, "Y")[-1]["parents"]
    assert snapshots(events, "Y")[-1]["provenance"] == "inferred"


def test_short_circuit_and_unpacking_keep_order():
    source = "calls = []\ndef mark(n):\n    calls.append(n)\n    return n\na, b = mark(1), mark(2)\nx = False and mark(3)\ny = True or mark(4)\n"
    result, _, _ = observe(source)
    assert result["calls"] == [1, 2]
    assert (result["a"], result["b"], result["x"], result["y"]) == (1, 2, False, True)


def test_same_name_in_functions_has_distinct_scope():
    source = "import numpy as np\nX = np.array([9])\ndef a():\n    X = np.array([1])\n    return X\ndef b():\n    X = np.array([2])\n    return X\nfirst, second = a(), b()\n"
    result, events, _ = observe(source)
    values = snapshots(events, "X")
    assert len({s["binding_id"] for s in values}) == 3
    assert sorted(s["sample"]["values"][0][0] for s in values) == [1, 2, 9]
    assert result["first"][0] == 1 and result["second"][0] == 2


def test_loops_keep_iteration_versions():
    result, events, _ = observe("import numpy as np\nX = np.array([0])\nfor i in range(4):\n    X = X + i\n")
    values = snapshots(events, "X")
    assert [s["version"] for s in values] == [1, 2, 3, 4, 5]
    assert [s["sample"]["values"][0][0] for s in values] == [0, 0, 1, 3, 6]
    operations = [e["payload"]["operation"] for e in events if e["kind"] == "operation.finished" and e["source"]["line"] == 4]
    assert [o["iteration"] for o in operations] == [1, 2, 3, 4]
    assert result["X"][0] == 6


def test_inplace_array_mutation_is_versioned():
    source = "import numpy as np\nX = np.arange(6).reshape(2, 3)\nview = X[:, 1:]\nX[0, 1] = 42\nX += 2\nX.fill(7)\n"
    result, events, _ = observe(source)
    values = snapshots(events, "X")
    assert [s["version"] for s in values] == [1, 2, 3, 4]
    assert values[0]["sample"]["values"][0] == [0, 1, 2]
    assert values[-1]["sample"]["values"] == [[7, 7, 7], [7, 7, 7]]
    assert snapshots(events, "view")[0]["sample"]["values"][0] == [1, 2]
    np.testing.assert_array_equal(result["X"], np.full((2, 3), 7))


def test_subscript_indices_and_rhs_are_not_reevaluated():
    source = "import numpy as np\ncalls = []\ndef index():\n    calls.append('i')\n    return 0\ndef rhs():\n    calls.append('v')\n    return 8\nX = np.arange(3)\nX[index()] = rhs()\n"
    result, _, _ = observe(source)
    assert result["calls"] == ["v", "i"]
    assert result["X"][0] == 8


def test_uncovered_dynamic_code_is_reported():
    result, events, coverage = observe("exec('dynamic = 3')\nvalue = eval('dynamic + 2')\n")
    assert result["value"] == 5
    assert any(item["status"] == "unsupported" and item["kind"] == "dynamic-code" for item in coverage.entries)
    assert any(e["kind"] == "coverage.report" for e in events)


def test_traceback_keeps_original_line():
    from contract_driven_ai_flow.research.agent.instrument import InstrumentPolicy, instrument
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    code = instrument("import numpy as np\nX = np.zeros((2, 3))\nY = np.ones((4, 5))\nZ = X @ Y\n", "original-analysis.py", InstrumentPolicy())
    trace = TraceSession("failure")
    with pytest.raises(ValueError) as error:
        code.execute(trace)
    frames = [f for f in traceback.extract_tb(error.value.__traceback__) if f.filename == "original-analysis.py"]
    assert frames[-1].lineno == 4
    assert any(e["kind"] == "operation.finished" and e["payload"]["operation"]["status"] == "failed" for e in trace.transport.drain())


def test_numpy_random_stream_and_dataframe_results_equal_plain_execution():
    source = "import numpy as np\nimport pandas as pd\nnp.random.seed(77)\nX = np.random.normal(size=(20, 4))\nframe = pd.DataFrame(X)\nY = frame.groupby(frame.index % 2).mean()\nZ = np.random.random(3)\n"
    baseline = {}
    exec(compile(source, "baseline.py", "exec"), baseline)
    result, _, _ = observe(source)
    np.testing.assert_array_equal(result["X"], baseline["X"])
    np.testing.assert_array_equal(result["Z"], baseline["Z"])
    assert result["Y"].equals(baseline["Y"])


def test_docstrings_future_annotations_and_shadowed_builtins_survive():
    source = '"module doc"\nfrom __future__ import annotations\nlocals = 42\ndef f(x: Missing) -> Missing:\n    "function doc"\n    globals = 99\n    y = x + 1\n    return y\nvalue = f(2)\n'
    result, _, _ = observe(source)
    assert result["__doc__"] == "module doc"
    assert result["f"].__doc__ == "function doc"
    assert result["f"].__annotations__ == {"x": "Missing", "return": "Missing"}
    assert result["value"] == 3


def test_generator_scope_is_not_held_across_yield():
    source = "def gen():\n    inner = 1\n    yield inner\nit = gen()\nfirst = next(it)\nouter = 5\n"
    result, events, coverage = observe(source)
    assert snapshots(events, "outer")[-1]["scope_id"] == "main"
    assert any(item["kind"] == "generator" and item["status"] == "unsupported" for item in coverage.entries)
    assert result["first"] == 1


def test_selected_names_and_lines_limit_observation():
    source = "import numpy as np\nX = np.ones((2, 2))\nY = X + 2\nZ = Y + 3\n"
    _, events, _ = observe(source, watched_names=("Z",), watched_lines=(4,))
    assert snapshots(events, "Z")
    assert not snapshots(events, "X")


def test_files_outside_allowlist_execute_without_instrumentation():
    result, events, coverage = observe("X = 7\n", filename="outside.py", allowed_files=("selected.py",))
    assert result["X"] == 7 and not snapshots(events, "X")
    assert any(item["kind"] == "file" and item["status"] == "unsupported" for item in coverage.entries)


def test_local_input_does_not_reuse_different_global_value():
    source = "import numpy as np\nX = np.array([100])\ndef f(X):\n    Y = X + 1\n    return Y\nresult = f(np.array([2]))\n"
    result, events, _ = observe(source)
    output = snapshots(events, "Y")[-1]
    inputs = {s["id"]: s for s in snapshots(events, "X")}
    assert inputs[output["parents"][0]]["sample"]["values"] == [[2]]
    assert result["result"][0] == 3


def test_script_runner_preserves_arguments_file_and_source(tmp_path):
    from contract_driven_ai_flow.research.agent.instrument import InstrumentPolicy
    from contract_driven_ai_flow.research.agent.runner import run_script
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    path = tmp_path / "analysis.py"
    path.write_text("import sys, json\nfrom pathlib import Path\nX = 3\nPath(sys.argv[1]).write_text(json.dumps({'args': sys.argv[2:], 'file': __file__}))\n", encoding="utf-8")
    original = path.read_bytes()
    output = tmp_path / "result.json"
    trace = TraceSession("runner")
    assert run_script(path, arguments=[str(output), "中文", "42"], session=trace, policy=InstrumentPolicy()) == 0
    observed = json.loads(output.read_text())
    assert observed["args"] == ["中文", "42"] and Path(observed["file"]) == path
    assert path.read_bytes() == original


@pytest.mark.parametrize("failure,expected", [("", "completed"), ("constant", "completed"), ("nan", "completed"), ("dimension", "failed")])
def test_pca_example_covers_success_and_real_failures(tmp_path, failure, expected):
    from contract_driven_ai_flow.research.agent.instrument import InstrumentPolicy
    from contract_driven_ai_flow.research.agent.runner import run_script
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    path = Path(__file__).parents[2] / "src/contract_driven_ai_flow/templates/research-analysis/analysis.py"
    trace = TraceSession("PCA")
    status = run_script(path, arguments=["--failure", failure or "none"], session=trace, policy=InstrumentPolicy())
    events = trace.transport.drain()
    terminal = next(e for e in events if e["kind"] == "run.finished")
    assert terminal["payload"]["status"] == expected
    assert status == (1 if expected == "failed" else 0)
    assert snapshots(events, "X")
    if failure in ("constant", "nan"):
        assert snapshots(events, "Z")[-1]["statistics"]["nan_count"] > 0


def test_visible_mutation_refreshes_known_numpy_alias():
    _, events, _ = observe("import numpy as np\nX = np.arange(6).reshape(2, 3)\nview = X[:, 1:]\nX[0, 1] = 42\n")
    view = snapshots(events, "view")
    assert len(view) == 2
    assert view[0]["sample"]["values"][0] == [1, 2]
    assert view[1]["sample"]["values"][0] == [42, 2]
    assert view[1]["coverage"]["alias_update"] == "observed"


def test_global_and_active_nonlocal_bindings_keep_their_owner_scope():
    source = "import numpy as np\nX = np.array([0])\ndef f():\n    global X\n    X = X + 1\ndef outer():\n    inner_value = np.array([2])\n    def inner():\n        nonlocal inner_value\n        inner_value = inner_value + 1\n    inner()\n    return inner_value\nf()\nresult = outer()\n"
    result, events, _ = observe(source)
    global_values = snapshots(events, "X")
    assert {s["scope_id"] for s in global_values} == {"main"}
    assert [s["version"] for s in global_values] == [1, 2]
    local_values = snapshots(events, "inner_value")
    assert len({s["scope_id"] for s in local_values}) == 1
    assert [s["version"] for s in local_values] == [1, 2]
    assert result["result"][0] == 3


def test_function_input_capture_is_not_a_caller_output():
    _, events, _ = observe("import numpy as np\ndef f(X):\n    Y = X + 1\n    return Y\nresult = f(np.ones(3))\n")
    caller = next(e["payload"]["operation"] for e in events if e["kind"] == "operation.finished" and e["source"]["line"] == 5)
    observed = {e["snapshot_id"]: e["payload"]["snapshot"]["name"] for e in events if e["kind"] == "value.observed"}
    assert [observed[s] for s in caller["output_snapshots"]] == ["result"]


def test_finished_function_scopes_do_not_accumulate_live_capture_state():
    from contract_driven_ai_flow.research.agent.instrument import instrument, InstrumentPolicy
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    trace = TraceSession("scope budget")
    code = instrument("import numpy as np\ndef f(i):\n    X = np.ones(2) * i\n    return X\nfor i in range(100):\n    result = f(i)\n", "loop.py", InstrumentPolicy())
    code.execute(trace)
    assert all(name.startswith("main:") for name in trace._latest)


def test_runner_main_module_is_the_actual_script_namespace(tmp_path):
    from contract_driven_ai_flow.research.agent.runner import run_script
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    script = tmp_path / "main_module.py"
    script.write_text("X = 7\nimport __main__\nassert __main__.X == X\n", encoding="utf-8")
    assert run_script(script, session=TraceSession("module")) == 0


def test_reflective_script_uses_unmodified_namespace_with_coverage_notice():
    source = "X = 7\nkeys = sorted(name for name in globals() if not name.startswith('__'))\n"
    plain = {"__name__": "__main__", "__file__": "reflection.py"}
    exec(source, plain)
    observed, events, coverage = observe(source, filename="reflection.py")
    assert observed["keys"] == plain["keys"]
    assert any(item["kind"] == "reflection" and item["status"] == "unsupported" for item in coverage.entries)
    assert not snapshots(events, "X")
