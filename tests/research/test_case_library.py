from pathlib import Path
import importlib.util
import pytest

CASES=Path(__file__).resolve().parents[2]/'examples'/'research'/'cases'

@pytest.mark.parametrize('name',['matrix','table','functions','controls','structure','combination','program','skill'])
def test_case_library_contains_executed_success_and_failure_paths(tmp_path,name):
    path=CASES/'run_cases.py'
    assert path.is_file(), 'Complete case runner is required'
    spec=importlib.util.spec_from_file_location('research_cases',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    results=[module.run_case(name,tmp_path/variant,failure=variant=='failure') for variant in ('success','failure')]
    assert all(r['verified'] for r in results),results
    assert all(r['run_id'] and r['output_ids'] for r in results)
    assert results[0]['outcome']!=results[1]['outcome']
