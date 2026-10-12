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
