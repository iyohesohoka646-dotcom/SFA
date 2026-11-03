"""P2b own tests: real project runs, freezing, ownership and compact plans.

These exercise the public ProjectApplication contract. They launch real
subprocesses (bounded) and never rely on a private worker API.
"""

from pathlib import Path

import pytest

from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.service import ExecutionBudget
from contract_driven_ai_flow.research.workbench.models import RunConfiguration


def example(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'calc.py').write_text(
        'X = 100\ndef double(value):\n    result = value * 2\n    return result\n',
        encoding='utf-8',
    )
    (root / 'main.py').write_text(
        'from calc import double\nX = 7\nY = double(X)\nprint(Y)\n',
        encoding='utf-8',
    )


def prepare(app, root, *, entry=('script', 'main.py')):
    kind, target = entry
    project = app.open(root)
    revision = app.index(project.id)
    config = app.configuration(project.id)
    app.save_entries(
        project.id,
        [RunConfiguration(id='main', name='Main', kind=kind, target=target)],
        expected_revision=config.revision,
    )
    plan = app.plan(project.id, 'main', revision_id=revision.id)
    return project, revision, plan



def test_real_run_cross_file_snapshots_and_outputs(tmp_path):
    root = tmp_path / 'lab'
    example(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision, plan = prepare(app, root)
        assert plan.project_id == project.id
        assert plan.project_revision_id == revision.id
        assert plan.manifest_id
        task = app.execute(project.id, plan.id)
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(task.id, timeout=45)
        assert done.status == 'completed', (done.status, done.message)
        snapshots = app.research(project.id).store.snapshots(done.run_id, limit=1000)
        assert any(s.name == 'result' and s.source.path.endswith('calc.py') for s in snapshots)
        y = next(s for s in reversed(snapshots) if s.name == 'Y')
        assert y.sample['value'] == 14
        assert y.source.project_id == project.id and y.source.file_id
        assert workbench.outputs(run_id=done.run_id)
        # A completed run releases its global computation permit.
        for _ in range(4):
            assert app.budget.acquire() is True
        for _ in range(4):
            app.budget.release()
    finally:
        app.close()


def test_package_module_entry_with_relative_imports(tmp_path):
    root = tmp_path / 'lab'
    (root / 'pkg').mkdir(parents=True)
    (root / 'pkg/__init__.py').write_text('', encoding='utf-8')
    (root / 'pkg/helper.py').write_text(
        'def scale(v):\n    doubled = v * 2\n    return doubled\n', encoding='utf-8'
    )
    (root / 'pkg/main.py').write_text(
        'from .helper import scale\nX = 5\nY = scale(X)\n', encoding='utf-8'
    )
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, _revision, plan = prepare(app, root, entry=('module', 'pkg.main'))
        assert plan.entry['kind'] == 'module'
        task = app.execute(project.id, plan.id)
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(task.id, timeout=45)
        assert done.status == 'completed', (done.status, done.message)
        snapshots = app.research(project.id).store.snapshots(done.run_id, limit=1000)
        y = next(s for s in reversed(snapshots) if s.name == 'Y')
        assert y.sample['value'] == 10
        doubled = next(s for s in snapshots if s.name == 'doubled')
        assert doubled.sample['value'] == 10
        assert doubled.source.path.endswith('helper.py')
    finally:
        app.close()


def test_same_named_variables_keep_distinct_scopes(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'main.py').write_text(
        'X = 1\ndef f():\n    X = 9\n    return X\nZ = f()\n', encoding='utf-8'
    )
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, _revision, plan = prepare(app, root)
        task = app.execute(project.id, plan.id)
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(task.id, timeout=45)
        assert done.status == 'completed', (done.status, done.message)
        snapshots = app.research(project.id).store.snapshots(done.run_id, limit=1000)
        xs = [s for s in snapshots if s.name == 'X']
        assert len({s.scope_id for s in xs}) == 2
        assert next(s for s in snapshots if s.name == 'Z').sample['value'] == 9
    finally:
        app.close()


def test_dependency_change_and_historical_source(tmp_path):
    left = tmp_path / 'left'
    right = tmp_path / 'right'
    example(left)
    example(right)
    app = ProjectApplication(tmp_path / 'host')
    try:
        p1, r1, plan = prepare(app, left)
        p2, _r2, _ = prepare(app, right)
        with pytest.raises((ValueError, LookupError)):
            app.execute(p2.id, plan.id)
        (left / 'calc.py').write_text(
            'def double(value):\n    return value * 3\n', encoding='utf-8'
        )
        with pytest.raises((ValueError, RuntimeError)):
            app.execute(p1.id, plan.id)
        unit = next(
            u for u in app.projects.files(p1.id, r1.id).items
            if u.relative_path == 'calc.py'
        )
        assert 'value * 2' in app.projects.source(p1.id, unit.id, r1.id)['code']
    finally:
        app.close()


def test_frozen_config_and_disabled_template(tmp_path):
    root = tmp_path / 'lab'
    example(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision, plan = prepare(app, root)
        frozen = app.workbench(project.id).store.get('plans', plan.id)['config_digest']
        config = app.configuration(project.id)
        disabled = config.model_copy(deep=True)
        for probe in disabled.probes:
            probe.enabled = False
        app.workbench(project.id).configure(disabled, expected_revision=config.revision)
        assert app.workbench(project.id).store.get('plans', plan.id)['config_digest'] == frozen
        next_plan = app.plan(project.id, 'main', revision_id=revision.id)
        task = app.execute(project.id, next_plan.id)
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(task.id, timeout=45)
        assert done.status == 'completed'
        assert not workbench.outputs(run_id=done.run_id)
    finally:
        app.close()


def test_unused_syntax_error_allows_valid_entry(tmp_path):
    root = tmp_path / 'lab'
    example(root)
    (root / 'broken.py').write_text('def broken(:\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, _revision, plan = prepare(app, root)
        task = app.execute(project.id, plan.id)
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(task.id, timeout=45)
        assert done.status == 'completed', (done.status, done.message)
    finally:
        app.close()


def test_imported_syntax_error_fails_visibly(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'main.py').write_text('import broken\nX = 1\n', encoding='utf-8')
    (root / 'broken.py').write_text('def broken(:\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, _revision, plan = prepare(app, root)
        task = app.execute(project.id, plan.id)
        done = app.workbench(project.id).jobs.wait(task.id, timeout=45)
        assert done.status == 'failed'
        assert done.message and 'failed' in done.message.lower()
    finally:
        app.close()


def test_cancellation_releases_permit(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'main.py').write_text('import time\nX = 1\ntime.sleep(30)\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, _revision, plan = prepare(app, root)
        task = app.execute(project.id, plan.id)
        workbench = app.workbench(project.id)
        workbench.jobs.cancel(task.id)
        done = workbench.jobs.wait(task.id, timeout=20)
        assert done.status == 'cancelled'
        for _ in range(4):
            assert app.budget.acquire() is True
        for _ in range(4):
            app.budget.release()
    finally:
        app.close()


def test_entry_candidates_and_compact_plan(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    for number in range(200):
        (root / f'module_{number:03}.py').write_text(
            f'X{number} = {number}\nY{number} = X{number} + 1\n', encoding='utf-8'
        )
    (root / 'main.py').write_text('RUN = 1\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    try:
        project = app.open(root)
        revision = app.index(project.id)
        candidates = app.entry_candidates(project.id, revision.id)
        assert any(c.target == 'main.py' for c in candidates)
        config = app.configuration(project.id)
        app.save_entries(
            project.id,
            [RunConfiguration(id='main', name='Main', kind='script', target='main.py')],
            expected_revision=config.revision,
        )
        plan = app.plan(project.id, 'main', revision_id=revision.id)
        encoded = plan.model_dump_json()
        # The plan freezes a manifest pointer, never 200 file object graphs.
        assert plan.manifest_id
        assert len(encoded) < 65536, len(encoded)
        assert 'module_199' not in encoded
    finally:
        app.close()


def test_execution_budget_is_application_scoped(tmp_path):
    budget = ExecutionBudget(4)
    assert all(budget.acquire() for _ in range(4))
    assert budget.acquire() is False
    budget.release()
    assert budget.acquire() is True

def _calc_result_target(app, project_id, revision_id):
    from contract_driven_ai_flow.research.workbench.semantic_models import TargetRef

    unit = next(
        u for u in app.projects.files(project_id, revision_id).items
        if u.relative_path == 'calc.py'
    )
    analysis = app.projects.analysis(project_id, unit.id, revision_id)
    obj = next(o for o in analysis.objects if o.name == 'result')
    return unit, analysis, obj, TargetRef(
        kind='data',
        logical_key=obj.logical_key,
        object_id=obj.id,
        block_id=obj.block_id,
        analysis_id=analysis.id,
        project_id=project_id,
        file_id=unit.id,
        project_revision_id=revision_id,
    )


def test_selection_scope_presents_imported_variable_only(tmp_path):
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector

    root = tmp_path / 'lab'
    example(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision, _ = prepare(app, root)
        _unit, _analysis, obj, target = _calc_result_target(app, project.id, revision.id)
        plan = app.plan(
            project.id, 'main', revision_id=revision.id,
            target_scope=ScopeSelector(mode='selection', targets=[target]),
        )
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(app.execute(project.id, plan.id).id, 45)
        assert done.status == 'completed', (done.status, done.message)
        outputs = workbench.outputs(run_id=done.run_id)
        data = [t for output in outputs for t in output.get('targets', []) if t.get('kind') == 'data']
        assert data
        assert all(t.get('logical_key') == obj.logical_key for t in data), data
    finally:
        app.close()


def test_file_scope_keeps_outputs_inside_that_file(tmp_path):
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector, TargetRef

    root = tmp_path / 'lab'
    example(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision, _ = prepare(app, root)
        unit, analysis, _obj, _target = _calc_result_target(app, project.id, revision.id)
        block = next(b for b in analysis.graph.blocks if b.kind == 'file')
        target = TargetRef(
            kind='file', logical_key=block.logical_key, block_id=block.id,
            analysis_id=analysis.id, project_id=project.id, file_id=unit.id,
            project_revision_id=revision.id,
        )
        plan = app.plan(
            project.id, 'main', revision_id=revision.id,
            target_scope=ScopeSelector(mode='selection', targets=[target]),
        )
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(app.execute(project.id, plan.id).id, 45)
        assert done.status == 'completed', (done.status, done.message)
        outputs = workbench.outputs(run_id=done.run_id)
        data = [t for output in outputs for t in output.get('targets', []) if t.get('kind') == 'data']
        assert data
        assert {t.get('file_id') for t in data} == {unit.id}, data
        main = next(
            u for u in app.projects.files(project.id, revision.id).items
            if u.relative_path == 'main.py'
        )
        assert all(t.get('file_id') != main.id for t in data)
    finally:
        app.close()


def test_late_configuration_change_is_rejected(tmp_path):
    root = tmp_path / 'lab'
    example(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision, plan = prepare(app, root)
        config = app.configuration(project.id)
        disabled = config.model_copy(deep=True)
        for probe in disabled.probes:
            probe.enabled = False
        app.workbench(project.id).configure(disabled, expected_revision=config.revision)
        with pytest.raises((ValueError, RuntimeError)) as error:
            app.execute(project.id, plan.id)
        assert any(
            word in str(error.value).lower()
            for word in ('config', 'revision', 'changed', 'stale')
        ), str(error.value)
    finally:
        app.close()


def test_replot_reuses_existing_run_and_rejects_other_revision(tmp_path):
    root = tmp_path / 'lab'
    example(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision, plan = prepare(app, root)
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(app.execute(project.id, plan.id).id, 45)
        assert done.status == 'completed', (done.status, done.message)
        before = len(workbench.outputs(run_id=done.run_id))
        replot = app.plan(
            project.id, 'main', revision_id=revision.id,
            scope='replot', run_id=done.run_id,
        )
        assert replot.scope == 'replot'
        again = workbench.jobs.wait(app.execute(project.id, replot.id).id, 45)
        assert again.status == 'completed', (again.status, again.message)
        assert again.run_id == done.run_id
        assert len(workbench.outputs(run_id=done.run_id)) >= before
        (root / 'calc.py').write_text('def double(value):\n    return value * 4\n', encoding='utf-8')
        moved = app.index(project.id)
        with pytest.raises((ValueError, RuntimeError)):
            app.plan(
                project.id, 'main', revision_id=moved.id,
                scope='replot', run_id=done.run_id,
            )
    finally:
        app.close()


def test_compact_plan_for_thousand_files(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    for number in range(1000):
        (root / f'module_{number:04}.py').write_text(
            f'A{number} = {number}\nB{number} = A{number} + 1\nC{number} = B{number} * 2\n',
            encoding='utf-8',
        )
    (root / 'main.py').write_text('RUN = 1\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    try:
        project = app.open(root)
        revision = app.index(project.id)
        config = app.configuration(project.id)
        app.save_entries(
            project.id,
            [RunConfiguration(id='main', name='Main', kind='script', target='main.py')],
            expected_revision=config.revision,
        )
        plan = app.plan(project.id, 'main', revision_id=revision.id)
        encoded = plan.model_dump_json()
        assert plan.manifest_id
        assert len(encoded) < 65536, len(encoded)
        assert 'module_0999' not in encoded
        assert not plan.invocations
    finally:
        app.close()


def test_workbench_shared_instance_and_models(tmp_path):
    """The project research service must own the same single workbench."""
    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'main.py').write_text('x = 1\n', encoding='utf-8')
    models = object()
    app = ProjectApplication(tmp_path / 'host', models=models)
    try:
        project = app.open(root)
        assert app.research(project.id)._workbench is app.workbench(project.id)
        assert app.workbench(project.id).models is models
    finally:
        app.close()


def test_package_entry_executes_main_and_hides_interpreter(tmp_path):
    root = tmp_path / 'lab'
    package = root / 'demo'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('INIT = 1\n', encoding='utf-8')
    (package / '__main__.py').write_text('RESULT = 7\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    try:
        project = app.open(root)
        revision = app.index(project.id)
        config = app.configuration(project.id)
        app.save_entries(
            project.id,
            [RunConfiguration(id='main', name='Main', kind='module', target='demo')],
            expected_revision=config.revision,
        )
        plan = app.plan(project.id, 'main', revision_id=revision.id)
        unit = next(
            u for u in app.projects.files(project.id, revision.id).items
            if u.relative_path == 'demo/__main__.py'
        )
        assert plan.entry['relative'] == 'demo/__main__.py'
        assert plan.entry['file_id'] == unit.id
        assert plan.source_digest == unit.digest
        assert not plan.config.interpreter
    finally:
        app.close()


def test_indexed_reads_presenters_and_historical_replot(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'main.py').write_text('from calc import double\nY = double(7)\n', encoding='utf-8')
    (root / 'calc.py').write_text(
        'def double(v):\n    result = v * 2\n    return result\n', encoding='utf-8'
    )
    app = ProjectApplication(tmp_path / 'host')
    try:
        project = app.open(root)
        revision = app.index(project.id)
        config = app.configuration(project.id)
        app.save_entries(
            project.id,
            [RunConfiguration(id='main', name='Main', kind='script', target='main.py')],
            expected_revision=config.revision,
        )
        workbench = app.workbench(project.id)
        plan = app.plan(project.id, 'main', revision_id=revision.id)
        done = workbench.jobs.wait(app.execute(project.id, plan.id).id, 45)
        assert done.status == 'completed', done.message
        unit = next(
            u for u in app.projects.files(project.id, revision.id).items
            if u.relative_path == 'calc.py'
        )
        assert workbench.analysis(unit.analysis_id).source_digest == unit.digest
        snapshot = next(
            s for s in app.research(project.id).store.snapshots(done.run_id, limit=1000)
            if s.name == 'result'
        )
        assert workbench.presenters(snapshot.id)
        assert workbench.analysis_source(unit.analysis_id)['code'].find('v * 2') >= 0
        # Edit the on-disk file without re-indexing: a historical replot must
        # still render from the archived evidence.
        (root / 'calc.py').write_text('USER = 42\n', encoding='utf-8')
        result = workbench.jobs.wait(
            workbench.execute_probes(done.run_id, snapshot_ids=[snapshot.id]).id, 45
        )
        assert result.status == 'completed', result.message
        assert 'v * 2' in app.projects.source(project.id, unit.id, revision.id)['code']
    finally:
        app.close()


def _folder_fixture(root: Path) -> None:
    pkg = root / 'pkg'
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'calc.py').write_text(
        'def double(v):\n    result = v * 2\n    return result\n', encoding='utf-8'
    )
    (root / 'main.py').write_text(
        'from pkg.calc import double\nX = 7\nY = double(X)\n', encoding='utf-8'
    )


def _open_main(app, root):
    project = app.open(root)
    revision = app.index(project.id)
    config = app.configuration(project.id)
    app.save_entries(
        project.id,
        [RunConfiguration(id='main', name='Main', kind='script', target='main.py')],
        expected_revision=config.revision,
    )
    return project, revision


def test_folder_selection_runs_only_its_members(tmp_path):
    from contract_driven_ai_flow.research.workbench.semantic_models import (
        ScopeSelector,
        TargetRef,
    )

    root = tmp_path / 'lab'
    _folder_fixture(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision = _open_main(app, root)
        folder = next(
            b for b in app.projects.graph(project.id, revision.id).graph.blocks
            if b.kind == 'folder'
        )
        target = TargetRef(
            kind='folder', logical_key=folder.logical_key, block_id=folder.id,
            project_id=project.id, project_revision_id=revision.id,
        )
        plan = app.plan(
            project.id, 'main', revision_id=revision.id,
            target_scope=ScopeSelector(mode='selection', targets=[target]),
        )
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(app.execute(project.id, plan.id).id, 45)
        assert done.status == 'completed', (done.status, done.message)
        outputs = workbench.outputs(run_id=done.run_id)
        assert outputs
        calc = next(
            u for u in app.projects.files(project.id, revision.id).items
            if u.relative_path == 'pkg/calc.py'
        )
        main = next(
            u for u in app.projects.files(project.id, revision.id).items
            if u.relative_path == 'main.py'
        )
        data = [
            t for output in outputs for t in output.get('targets', [])
            if t.get('kind') == 'data'
        ]
        assert data
        assert all(t.get('file_id') == calc.id for t in data), data
        assert all(
            t.get('project_id') == project.id
            and t.get('project_revision_id') == revision.id
            for t in data
        ), data
        assert all(t.get('file_id') != main.id for t in data), data
    finally:
        app.close()


def test_project_and_folder_selection_dedup(tmp_path):
    from contract_driven_ai_flow.research.workbench.semantic_models import (
        ScopeSelector,
        TargetRef,
    )

    root = tmp_path / 'lab'
    _folder_fixture(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision = _open_main(app, root)
        blocks = app.projects.graph(project.id, revision.id).graph.blocks
        project_block = next(b for b in blocks if b.kind == 'project')
        folder = next(b for b in blocks if b.kind == 'folder')
        targets = [
            TargetRef(
                kind='project', logical_key=project_block.logical_key,
                block_id=project_block.id, project_id=project.id,
                project_revision_id=revision.id,
            ),
            TargetRef(
                kind='folder', logical_key=folder.logical_key, block_id=folder.id,
                project_id=project.id, project_revision_id=revision.id,
            ),
        ]
        plan = app.plan(
            project.id, 'main', revision_id=revision.id,
            target_scope=ScopeSelector(mode='selection', targets=targets),
        )
        workbench = app.workbench(project.id)
        done = workbench.jobs.wait(app.execute(project.id, plan.id).id, 45)
        assert done.status == 'completed', (done.status, done.message)
        outputs = workbench.outputs(run_id=done.run_id)
        data = [
            t for output in outputs for t in output.get('targets', [])
            if t.get('kind') == 'data'
        ]
        assert data
        keys = [t.get('logical_key') for t in data]
        assert len(keys) == len(set(keys)), keys
    finally:
        app.close()


def test_foreign_project_folder_target_is_rejected(tmp_path):
    from contract_driven_ai_flow.research.workbench.semantic_models import (
        ScopeSelector,
        TargetRef,
    )

    root = tmp_path / 'lab'
    _folder_fixture(root)
    app = ProjectApplication(tmp_path / 'host')
    try:
        project, revision = _open_main(app, root)
        folder = next(
            b for b in app.projects.graph(project.id, revision.id).graph.blocks
            if b.kind == 'folder'
        )
        foreign = TargetRef(
            kind='folder', logical_key='someoneelse::folder::pkg',
            block_id=folder.id, project_id='someoneelse',
            project_revision_id=revision.id,
        )
        with pytest.raises(ValueError):
            app.plan(
                project.id, 'main', revision_id=revision.id,
                target_scope=ScopeSelector(mode='selection', targets=[foreign]),
            )
        wrong_revision = TargetRef(
            kind='folder', logical_key=folder.logical_key, block_id=folder.id,
            project_id=project.id, project_revision_id='not-this-revision',
        )
        with pytest.raises(ValueError):
            app.plan(
                project.id, 'main', revision_id=revision.id,
                target_scope=ScopeSelector(mode='selection', targets=[wrong_revision]),
            )
    finally:
        app.close()


def test_index_forwards_progress(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    for number in range(5):
        (root / f'module_{number}.py').write_text(
            f'X{number} = {number}\n', encoding='utf-8'
        )
    app = ProjectApplication(tmp_path / 'host')
    events = []
    try:
        project = app.open(root)
        revision = app.index(project.id, progress=events.append)
        assert revision.files_count == 5
        parse_events = [e for e in events if isinstance(e, dict)]
        assert parse_events
        last = parse_events[-1]
        assert last['stage'] == 'parse'
        assert last['parsed'] == 5 and last['total'] == 5
        assert last['completed'] == 5
    finally:
        app.close()


def test_index_progress_cancel_before_publish(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    for number in range(3):
        (root / f'module_{number}.py').write_text(
            f'Y{number} = {number}\n', encoding='utf-8'
        )
    app = ProjectApplication(tmp_path / 'host')
    try:
        project = app.open(root)

        class _Cancel:
            def __init__(self):
                self.flag = False

            def is_set(self):
                return self.flag

        token = _Cancel()

        def progress(event):
            if isinstance(event, dict) and event.get('stage') == 'parse':
                token.flag = True

        with pytest.raises(InterruptedError):
            app.index(project.id, cancel=token, progress=progress)
        assert not app.projects.project(project.id).latest_revision_id
    finally:
        app.close()