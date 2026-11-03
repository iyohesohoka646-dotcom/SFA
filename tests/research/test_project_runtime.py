"""P2a project runtime contract tests (own tests; frozen acceptance untouched)."""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from contract_driven_ai_flow.research.agent.sdk import TraceSession
from contract_driven_ai_flow.research.agent.transport import EventTransport


def run_project():
    from contract_driven_ai_flow.research.agent.project_runner import run_project as runner

    return runner


def build_manifest(root):
    return {
        str(p.resolve()): {
            'file_id': p.relative_to(root).as_posix(),
            'digest': hashlib.sha256(p.read_bytes()).hexdigest(),
            'project_id': 'project-test',
            'project_revision_id': 'revision-test',
        }
        for p in root.rglob('*.py')
    }


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def execute(root, kind='script', target='main.py', arguments=(), sink=None, manifest=None, cwd=None):
    events = sink if sink is not None else []
    session = TraceSession('project', EventTransport(sink=events))
    status = run_project()(
        root,
        {'kind': kind, 'target': target},
        session=session,
        manifest=build_manifest(root) if manifest is None else manifest,
        arguments=arguments,
        cwd=cwd,
    )
    return status, events


def snapshots(events, name=None):
    values = [e['payload']['snapshot'] for e in events if e['kind'] == 'value.observed']
    return [s for s in values if name is None or s['name'] == name]


def ancestry(events, snapshot):
    by_id = {s['id']: s for s in snapshots(events)}
    seen, pending = set(), list(snapshot['parents'])
    while pending:
        key = pending.pop()
        if key in seen or key not in by_id:
            continue
        seen.add(key)
        pending.extend(by_id[key]['parents'])
    return [by_id[key] for key in seen]


def plain_output(root, name='main.py'):
    return subprocess.run(
        [sys.executable, '-B', name], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


CALC = (
    'FACTOR = 3\n'
    'def double(value):\n'
    '    result = value * 2\n'
    '    result += FACTOR\n'
    '    return result\n'
)


def test_parameter_and_return_ancestry_cross_module(tmp_path):
    write(tmp_path, 'calc.py', CALC)
    write(tmp_path, 'main.py', 'import calc\nX = 7\nY = calc.double(X)\nprint(Y)\n')
    expected = plain_output(tmp_path)
    status, events = execute(tmp_path)
    assert status == 0
    y = snapshots(events, 'Y')[-1]
    assert str(y['sample']['value']) == expected == '17'
    names = {s['name']: s for s in ancestry(events, y)}
    result = names['result']
    assert Path(result['source']['path']).name == 'calc.py'
    assert result['binding_id'].startswith('double:')
    sources = {s['name']: s for s in ancestry(events, result)}
    assert sources['value']['source']['path'].endswith('calc.py')
    assert sources['value']['binding_id'].startswith('double:')
    upstream = {s['name']: s for s in ancestry(events, sources['value'])}
    assert upstream['X']['binding_id'] == 'main:X'
    module_global = names['FACTOR']
    # The module global keeps its own logical module owner. Its SourceRef points
    # at the original definition site (module level, empty qualname) and must not
    # be rewritten to the read-site function name.
    assert module_global['binding_id'].startswith('<module>:')
    assert module_global['logical_key'].endswith('::<module>::FACTOR')
    assert Path(module_global['source']['path']).name == 'calc.py'
    assert module_global['source']['qualname'] == ''


def test_module_entry_preserves_spec_argv_cwd_and_relative_import(tmp_path):
    write(tmp_path, 'labpkg/__init__.py', '')
    write(tmp_path, 'labpkg/calc.py', 'def double(x):\n    y = x * 2\n    return y\n')
    write(
        tmp_path,
        'labpkg/__main__.py',
        'import json\n'
        'import sys\n'
        'from pathlib import Path\n'
        'from .calc import double\n'
        'X = 3\n'
        'Y = double(X)\n'
        "Path('entry.json').write_text(json.dumps({'spec': __spec__.name, 'package': __package__,\n"
        "    'file': Path(__file__).name, 'argv': sys.argv[1:], 'cwd': str(Path.cwd()), 'y': Y}))\n",
    )
    status, events = execute(tmp_path, kind='module', target='labpkg', arguments=('--flag', '7'))
    assert status == 0
    record = json.loads((tmp_path / 'entry.json').read_text(encoding='utf-8'))
    assert record['spec'] == 'labpkg.__main__'
    assert record['package'] == 'labpkg'
    assert record['file'] == '__main__.py'
    assert record['argv'] == ['--flag', '7']
    assert Path(record['cwd']).resolve() == tmp_path.resolve()
    assert record['y'] == 6
    assert snapshots(events, 'y')[-1]['source']['path'].endswith('calc.py')


def test_package_init_and_import_cache_run_once(tmp_path):
    marker = tmp_path / 'init.txt'
    write(tmp_path, 'labpkg/__init__.py', "from pathlib import Path\nPath('init.txt').write_text(Path('init.txt').read_text() + 'x' if Path('init.txt').exists() else 'x')\n")
    write(tmp_path, 'labpkg/calc.py', 'def double(x):\n    return x * 2\n')
    write(tmp_path, 'main.py', 'import labpkg\nimport labpkg.calc\nimport labpkg\nY = labpkg.calc.double(4)\nprint(Y)\n')
    status, _ = execute(tmp_path)
    assert status == 0
    assert marker.read_text(encoding='utf-8') == 'x'


def test_runtime_logical_keys_match_project_index(tmp_path):
    from contract_driven_ai_flow.research.projects.service import ProjectService

    write(tmp_path, 'calc.py', 'def double(value):\n    result = value * 2\n    return result\n')
    write(tmp_path, 'main.py', 'import calc\nX = 7\nY = calc.double(X)\n')
    service = ProjectService(tmp_path.parent / (tmp_path.name + '-host'))
    try:
        project = service.open(tmp_path)
        revision = service.index(project.id)
        units = {u.relative_path: u for u in service.files(project.id).items}
        manifest = {
            str((tmp_path / rel).resolve()): {
                'file_id': unit.id,
                'digest': unit.digest,
                'project_id': project.id,
                'project_revision_id': revision.id,
            }
            for rel, unit in units.items()
        }
        status, events = execute(tmp_path, manifest=manifest)
        assert status == 0
        document = service.analysis(project.id, units['main.py'].id)
        indexed = {obj.logical_key for obj in document.objects if obj.name in {'X', 'Y'}}
        runtime = {
            s['logical_key']
            for s in snapshots(events)
            if s['name'] in {'X', 'Y'} and s['source'].get('file_id') == units['main.py'].id
        }
        assert runtime, 'Cross-module runtime keys were not stamped with project identity'
        assert runtime <= indexed
        assert all(s['source']['project_id'] == project.id for s in snapshots(events))
    finally:
        service.close()


def test_same_named_module_globals_keep_distinct_scopes(tmp_path):
    write(tmp_path, 'one.py', 'X = 1\n')
    write(tmp_path, 'two.py', 'X = 2\n')
    write(tmp_path, 'main.py', 'import one\nimport two\nY = one.X + two.X\n')
    status, events = execute(tmp_path)
    assert status == 0
    xs = snapshots(events, 'X')
    assert len({s['binding_id'] for s in xs}) == 2
    assert len({s['source']['file_id'] for s in xs}) == 2
    assert all(s['logical_key'].endswith('::<module>::X') for s in xs)
    assert snapshots(events, 'Y')[-1]['sample']['value'] == 3


def test_recursion_keyword_arguments_and_activation_scopes(tmp_path):
    write(
        tmp_path,
        'ops.py',
        'def total(n, step=1, *, scale=1):\n'
        '    if n <= 0:\n'
        '        return 0\n'
        '    return total(n - step, step=step, scale=scale) + step * scale\n',
    )
    write(tmp_path, 'main.py', 'import ops\nY = ops.total(4, step=1, scale=2)\nprint(Y)\n')
    expected = plain_output(tmp_path)
    status, events = execute(tmp_path)
    assert status == 0
    y = snapshots(events, 'Y')[-1]
    assert str(y['sample']['value']) == expected == '8'
    parameters = snapshots(events, 'n')
    assert len({s['binding_id'] for s in parameters}) >= 4
    assert all(s['source']['path'].endswith('ops.py') for s in parameters)


def test_finally_override_changes_native_result_and_provenance(tmp_path):
    write(
        tmp_path,
        'ops.py',
        'def pick():\n'
        '    try:\n'
        '        return 1\n'
        '    finally:\n'
        '        return 2\n',
    )
    write(tmp_path, 'main.py', 'import ops\nY = ops.pick()\nprint(Y)\n')
    expected = plain_output(tmp_path)
    status, events = execute(tmp_path)
    assert status == 0
    y = snapshots(events, 'Y')[-1]
    assert str(y['sample']['value']) == expected == '2'
    returned = snapshots(events, '<return>')
    assert returned and all(s['sample']['value'] != 1 for s in returned)
    assert 'return 2' in returned[-1]['source']['code']


def test_exception_in_finally_discards_return_candidate(tmp_path):
    write(
        tmp_path,
        'ops.py',
        'def explode():\n'
        '    try:\n'
        '        return 1\n'
        '    finally:\n'
        "        raise RuntimeError('after return')\n",
    )
    write(tmp_path, 'main.py', 'import ops\nY = ops.explode()\n')
    status, events = execute(tmp_path)
    assert status == 1
    assert not snapshots(events, '<return>')
    assert not snapshots(events, 'Y')
    error = next(e for e in events if e['kind'] == 'analysis.error')
    assert error['payload']['error_type'] == 'RuntimeError'
    assert any(frame['path'].endswith('ops.py') for frame in error['payload']['frames'])
    finished = next(e for e in events if e['kind'] == 'run.finished')
    assert finished['payload']['status'] == 'failed'


def test_sibling_statement_returns_do_not_leak(tmp_path):
    write(
        tmp_path,
        'ops.py',
        'def first():\n'
        '    first_value = 1\n'
        '    return first_value\n'
        '\n'
        'def second():\n'
        '    second_value = 2\n'
        '    return second_value\n',
    )
    write(tmp_path, 'main.py', 'import ops\nx = ops.first()\ny = ops.second()\n')
    status, events = execute(tmp_path)
    assert status == 0
    y = snapshots(events, 'y')[-1]
    names = {s['name'] for s in ancestry(events, y)}
    assert 'second_value' in names
    assert 'first_value' not in names


def test_changed_source_is_rejected_before_compile(tmp_path):
    write(tmp_path, 'calc.py', 'def value(x):\n    return x * 2\n')
    write(tmp_path, 'main.py', 'import calc\nY = calc.value(3)\n')
    manifest = build_manifest(tmp_path)
    write(tmp_path, 'calc.py', 'def value(x):\n    return x * 3\n')
    status, events = execute(tmp_path, manifest=manifest)
    assert status != 0
    error = next(e for e in events if e['kind'] == 'analysis.error')
    assert 'changed' in error['payload']['message'].lower()
    assert not snapshots(events, 'Y')


def test_entry_outside_manifest_is_reported(tmp_path):
    write(tmp_path, 'main.py', 'Y = 1\n')
    status, events = execute(tmp_path, manifest={})
    assert status != 0
    assert any(e['kind'] == 'analysis.error' for e in events)


def test_environment_hooks_and_imported_modules_are_restored(tmp_path):
    write(tmp_path, 'nspkg/helper.py', 'def value(x):\n    return x + 1\n')
    write(
        tmp_path,
        'main.py',
        'import sys\n'
        'from nspkg import helper\n'
        "sys.path.append('temporary-entry')\n"
        'Y = helper.value(1)\n',
    )
    loader = importlib.machinery.SourceFileLoader
    before = {
        'cwd': os.getcwd(),
        'path': list(sys.path),
        'argv': list(sys.argv),
        'main': sys.modules.get('__main__'),
        'exec_module': loader.exec_module,
        'modules': set(sys.modules),
    }
    status, _ = execute(tmp_path)
    assert status == 0
    assert os.getcwd() == before['cwd']
    assert sys.path == before['path']
    assert sys.argv == before['argv']
    assert sys.modules.get('__main__') is before['main']
    assert loader.exec_module is before['exec_module']
    assert 'nspkg' not in sys.modules
    assert 'nspkg.helper' not in sys.modules
    assert not (set(sys.modules) - before['modules'])


def test_custom_loader_subclass_is_untouched_with_coverage(tmp_path):
    write(tmp_path, 'custmod.py', 'VALUE = 5\n')
    write(tmp_path, 'main.py', 'import custmod\nY = custmod.VALUE\n')

    class CustomLoader(importlib.machinery.SourceFileLoader):
        executed = False

        def exec_module(self, module):
            CustomLoader.executed = True
            return super().exec_module(module)

    origin = str((tmp_path / 'custmod.py').resolve())

    class Finder:
        def find_spec(self, name, path=None, target=None):
            if name == 'custmod':
                return importlib.util.spec_from_file_location('custmod', origin, loader=CustomLoader('custmod', origin))
            return None

    finder = Finder()
    sys.meta_path.insert(0, finder)
    try:
        status, events = execute(tmp_path)
    finally:
        sys.meta_path.remove(finder)
    assert status == 0
    assert CustomLoader.executed is True
    assert snapshots(events, 'Y')[-1]['sample']['value'] == 5
    assert not [s for s in snapshots(events) if s['source']['path'] == origin]
    entries = [item for e in events if e['kind'] == 'coverage.report' for item in e['payload']['entries']]
    assert any(item['kind'] == 'custom-loader' and item['status'] == 'unsupported' for item in entries)


def test_generator_and_async_functions_keep_explicit_partial_coverage(tmp_path):
    write(
        tmp_path,
        'main.py',
        'import asyncio\n'
        'def gen():\n'
        '    yield 1\n'
        'async def compute():\n'
        '    return 4\n'
        'items = list(gen())\n'
        'Y = asyncio.run(compute())\n'
        'print(items, Y)\n',
    )
    expected = plain_output(tmp_path)
    status, events = execute(tmp_path)
    assert status == 0 and expected == '[1] 4'
    assert snapshots(events, 'items')
    assert snapshots(events, 'Y')[-1]['sample']['value'] == 4
    entries = [item for e in events if e['kind'] == 'coverage.report' for item in e['payload']['entries']]
    kinds = {(item['kind'], item['status']) for item in entries}
    assert ('generator', 'unsupported') in kinds
    assert ('async-function', 'unsupported') in kinds


def test_imported_function_controls_finalize_once_at_run_end(tmp_path):
    write(
        tmp_path,
        'calc.py',
        'def classify(value):\n'
        '    if value > 0:\n'
        "        return 'positive'\n"
        "    return 'other'\n",
    )
    write(tmp_path, 'main.py', 'import calc\nY = calc.classify(3)\n')
    status, events = execute(tmp_path)
    assert status == 0
    finished = [e for e in events if e['kind'] == 'control.finished']
    assert len(finished) == 1 and finished[0]['payload']['complete'] is True
    chunks = [e for e in events if e['kind'] == 'control.summary']
    for chunk in chunks:
        for summary in chunk['payload']['summaries']:
            if summary['complete']:
                assert chunk['payload']['final'] is True
    callee = [
        s
        for chunk in chunks
        for s in chunk['payload']['summaries']
        if s['complete'] and s['source']['path'].endswith('calc.py') and s['kind'] == 'function'
    ]
    assert callee
    observed = {s['id']: s for s in snapshots(events)}
    y = snapshots(events, 'Y')[-1]
    assert all(key in observed for key in y['parents'])


def test_failed_run_reports_incomplete_controls(tmp_path):
    write(
        tmp_path,
        'calc.py',
        'def boom():\n'
        '    for i in range(3):\n'
        '        pass\n'
        "    raise ValueError('user failure')\n",
    )
    write(tmp_path, 'main.py', 'import calc\ncalc.boom()\n')
    status, events = execute(tmp_path)
    assert status == 1
    finished = [e for e in events if e['kind'] == 'control.finished']
    assert len(finished) == 1
    assert finished[0]['payload']['complete'] is False
    assert all(
        summary['complete'] is False
        for chunk in events
        if chunk['kind'] == 'control.summary'
        for summary in chunk['payload']['summaries']
    )
    error = next(e for e in events if e['kind'] == 'analysis.error')
    assert any(frame['path'].endswith('calc.py') for frame in error['payload']['frames'])


def test_control_detail_and_node_budget_is_shared_across_modules(tmp_path):
    from contract_driven_ai_flow.research.agent.budget import CapturePolicy

    for name in ('left.py', 'right.py'):
        write(tmp_path, name, 'for i in range(6):\n    x = i + 1\n')
    write(tmp_path, 'main.py', 'import left\nimport right\n')
    events = []
    session = TraceSession(
        'budget', EventTransport(sink=events), CapturePolicy(max_control_details=7)
    )
    status = run_project()(
        tmp_path,
        {'kind': 'script', 'target': 'main.py'},
        session=session,
        manifest=build_manifest(tmp_path),
    )
    assert status == 0
    details = [
        detail
        for event in events
        if event['kind'] == 'control.details'
        for detail in event['payload']['details']
    ]
    # 6 loop iterations + 1 loop exit per module: 14 attempts against a 7 limit.
    assert len(details) <= 7, f'Per-module budgets multiplied to {len(details)} details'
    receipts = [event['payload'] for event in events if event['kind'] == 'control.finished']
    assert len(receipts) == 1
    assert receipts[0]['omitted'] == 14 - len(details)
    assert receipts[0]['omitted'] >= 7
    final = {}
    for event in events:
        if event['kind'] == 'control.summary' and event['payload']['final']:
            for summary in event['payload']['summaries']:
                final[summary['node_id']] = summary
    assert {Path(s['source']['path']).name for s in final.values()} == {'left.py', 'right.py'}
    assert receipts[0]['node_count'] == len(final)
