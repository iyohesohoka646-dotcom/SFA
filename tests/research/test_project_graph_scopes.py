from contract_driven_ai_flow.research.projects.application import ProjectApplication
from contract_driven_ai_flow.research.projects.queries import ProjectQueryService
from contract_driven_ai_flow.research.projects.resolver import _id

def lab(tmp_path):
 root=tmp_path/'lab';root.mkdir()
 (root/'calc.py').write_text('def double(value):\n    Y=value*2\n    return Y\n',encoding='utf-8')
 (root/'main.py').write_text('from calc import double\nX=7\nY=double(X)\n',encoding='utf-8')
 (root/'large.py').write_text(''.join(f'V{i}={i}\n' for i in range(450)),encoding='utf-8')
 app=ProjectApplication(tmp_path/'host');p=app.open(root);r=app.index(p.id)
 files={f.relative_path:f for f in app.projects.files(p.id,r.id).items}
 return app,p,r,files

def test_overview_preserves_real_cross_file_calls(tmp_path):
 app,p,r,f=lab(tmp_path)
 try:
  q=ProjectQueryService(app.projects,app);g=q.graph(p.id,r.id,view='code').graph
  a,b=_id('file',f['main.py'].id),_id('file',f['calc.py'].id)
  calls=[e for e in g.edges if e.source==a and e.target==b and e.kind=='call']
  assert calls,'File folding must preserve actual calls'
  assert all(e.original_ids for e in calls),'Summary edges need exact original relation references'
 finally:app.close()

def test_file_graph_identity_focuses_before_project_size_limit(tmp_path):
 app,p,r,f=lab(tmp_path)
 try:
  q=ProjectQueryService(app.projects,app);fid=f['calc.py'].id;scope=_id('file',fid)
  g=q.graph(p.id,r.id,scope_id=scope,view='code').graph
  assert any(b.kind=='function' and b.source and b.source.file_id==fid for b in g.blocks),'Other large files must not erase focused file detail'
  assert g.nodes,'Focused small file must include its computations'
 finally:app.close()

def test_function_graph_focuses_before_global_aggregation(tmp_path):
 app,p,r,f=lab(tmp_path)
 try:
  q=ProjectQueryService(app.projects,app);fid=f['calc.py'].id
  doc=app.projects.analysis(p.id,fid,r.id)
  b=next(b for b in doc.graph.blocks if b.kind=='function')
  scope=_id('block',fid,b.id)
  g=q.graph(p.id,r.id,scope_id=scope,view='code').graph
  assert scope in g.roots and any(n.block_id==scope for n in g.nodes)
 finally:app.close()



import pytest
from pathlib import Path
from contract_driven_ai_flow.research.projects.store import ProjectStore


def test_folder_graph_id_roots_folder_scope(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'pkg').mkdir()
    (root / 'pkg' / 'a.py').write_text('def one():\n    return 1\n', encoding='utf-8')
    (root / 'pkg' / 'b.py').write_text('def two():\n    return 2\n', encoding='utf-8')
    (root / 'main.py').write_text('X=1\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    p = app.open(root)
    r = app.index(p.id)
    try:
        scope = _id('folder', p.id, 'pkg')
        g = ProjectQueryService(app.projects, app).graph(
            p.id, r.id, scope_id=scope, view='code'
        ).graph
        assert scope in g.roots
        labels = sorted(b.label for b in g.blocks if b.kind == 'file')
        assert labels == ['pkg/a.py', 'pkg/b.py']
    finally:
        app.close()


def test_unknown_graph_scope_raises_keyerror(tmp_path):
    app, p, r, f = lab(tmp_path)
    try:
        with pytest.raises(KeyError):
            ProjectQueryService(app.projects, app).graph(
                p.id, r.id, scope_id='no::such::scope', view='code'
            )
    finally:
        app.close()


def test_block_scope_picks_only_its_own_file(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'one.py').write_text('def helper():\n    return 1\n', encoding='utf-8')
    (root / 'two.py').write_text('def helper():\n    return 2\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    p = app.open(root)
    r = app.index(p.id)
    files = {x.relative_path: x for x in app.projects.files(p.id, r.id).items}
    try:
        doc = app.projects.analysis(p.id, files['one.py'].id, r.id)
        b = next(x for x in doc.graph.blocks if x.kind == 'function')
        scope = _id('block', files['one.py'].id, b.id)
        g = ProjectQueryService(app.projects, app).graph(
            p.id, r.id, scope_id=scope, view='code'
        ).graph
        assert scope in g.roots
        functions = [x for x in g.blocks if x.kind == 'function']
        assert functions
        assert all(x.source and x.source.file_id == files['one.py'].id for x in functions)
    finally:
        app.close()


def test_large_function_scope_bounded_keeps_root(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    body = ''.join(f'    V{i}=X+{i}\n' for i in range(400))
    (root / 'big.py').write_text('X=0\ndef huge():\n' + body + '    return X\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    p = app.open(root)
    r = app.index(p.id)
    fid = app.projects.files(p.id, r.id).items[0].id
    try:
        doc = app.projects.analysis(p.id, fid, r.id)
        b = next(x for x in doc.graph.blocks if x.kind == 'function')
        scope = _id('block', fid, b.id)
        sl = ProjectQueryService(app.projects, app).graph(
            p.id, r.id, scope_id=scope, view='code', limit=350
        )
        g = sl.graph
        assert scope in g.roots
        assert any(n.block_id == scope for n in g.nodes)
        assert len(g.blocks) + len(g.nodes) <= 350
        ids = {x.id for x in g.blocks}
        assert all(x.parent_id is None or x.parent_id in ids for x in g.blocks)
        assert sl.omitted_count > 0
    finally:
        app.close()


def test_block_scope_resolves_from_archived_new_revision(tmp_path):
    app, p, r, f = lab(tmp_path)
    fid = f['calc.py'].id
    try:
        root = Path(p.root)
        (root / 'calc.py').write_text(
            'def double(value):\n    Y=value*2\n    return Y\n\ndef triple(v):\n    return v*3\n',
            encoding='utf-8',
        )
        r2 = app.index(p.id)
        doc = app.projects.analysis(p.id, fid, r2.id)
        functions = [x for x in doc.graph.blocks if x.kind == 'function']
        assert len(functions) >= 2
        b = functions[-1]
        scope = _id('block', fid, b.id)
        g = ProjectQueryService(app.projects, app).graph(
            p.id, r2.id, scope_id=scope, view='code'
        ).graph
        assert scope in g.roots
        assert any(n.block_id == scope for n in g.nodes)
    finally:
        app.close()


def test_file_scope_validates_only_selected_file(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir()
    for i in range(70):
        (root / f'm{i:03d}.py').write_text('def f(a):\n    return a+1\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    p = app.open(root)
    r = app.index(p.id)
    files = {x.relative_path: x for x in app.projects.files(p.id, r.id).items}
    selected = files['m000.py']
    seen = []
    original = ProjectStore.get_analysis

    def spy(self, analysis_id):
        seen.append(analysis_id)
        return original(self, analysis_id)

    ProjectStore.get_analysis = spy
    try:
        expected = {
            row['analysis_id']
            for row in ProjectStore(Path(p.root)).revision_files(r.id)
            if row['file_id'] == selected.id
        }
        ProjectQueryService(app.projects, app).graph(
            p.id, r.id, scope_id=_id('file', selected.id), view='code'
        )
        assert set(seen) == expected
    finally:
        ProjectStore.get_analysis = original
        app.close()
