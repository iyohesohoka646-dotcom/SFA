"""User defaults and project overrides with provenance and revision checks."""
from __future__ import annotations
import json
import os
import threading
from pathlib import Path
from jsonschema import validate, ValidationError
from ...storage import atomic_write_private
DEFAULTS={'workspace':{'theme':'light','explorer_width':218,'compact':False},'graph':{'view':'structure','dim_unrelated':False,'direction':'RIGHT'},
 'probes':{'concurrency':4,'precision':3},'capture':{'level':'summary','max_artifact_bytes':64*1024*1024,'max_run_bytes':256*1024*1024,'max_control_details':512},
 'intelligence':{'include_samples':False,'input_tokens':12000},'terminal':{'profile':'shell','buffer_chars':262144},'storage':{'retention_days':14}}
SCHEMA={'type':'object','additionalProperties':False,'properties':{name:{'type':'object','additionalProperties':False,'properties':{key:({'type':'boolean'} if isinstance(value,bool) else {'type':'integer','minimum':1,'maximum':1073741824} if isinstance(value,int) else {'type':'string','enum':['light','dark']} if key=='theme' else {'type':'string','enum':['metadata','summary','sample','full']} if key=='level' else {'type':'string','enum':['structure','data','execution']} if key=='view' else {'type':'string','enum':['RIGHT','DOWN']} if key=='direction' else {'type':'string','enum':['shell','python','cli']}) for key,value in values.items()}} for name,values in DEFAULTS.items()}}
SCHEMA['properties']['probes']['properties']['precision']={'type':'integer','minimum':0,'maximum':12}
SCHEMA['properties']['capture']['properties']['max_artifact_bytes']['maximum']=64*1024*1024
SCHEMA['properties']['capture']['properties']['max_run_bytes']['maximum']=256*1024*1024
SCHEMA['properties']['capture']['properties']['max_control_details']['maximum']=512
SCHEMA['properties']['probes']['properties']['concurrency']['maximum']=16
_locks={};_guard=threading.Lock()
class PreferenceService:
 def __init__(self,root,user_path=None):
  self.project=Path(root)/'.cdaf'/'preferences.json'
  self.user=Path(user_path) if user_path else Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.config')/'ScientificDataflowInspector'/'preferences.json'
 def _read(self,path):
  if not path.exists():return {'revision':0,'values':{}}
  result=json.loads(path.read_text(encoding='utf-8'));validate(result['values'],SCHEMA);return result
 def load(self):
  user,project=self._read(self.user),self._read(self.project)
  values=json.loads(json.dumps(DEFAULTS));sources={g+'.'+k:'default' for g,v in DEFAULTS.items() for k in v}
  for name,raw in [('user',user),('project',project)]:
   for group,fields in raw['values'].items():
    values[group].update(fields)
    for key in fields:sources[group+'.'+key]=name
  return {'values':values,'sources':sources,'user_revision':user['revision'],'project_revision':project['revision']}
 def save(self,scope,values,*,expected_revision):
  if scope not in ('user','project'):raise ValueError('Unknown settings scope')
  try:validate(values,SCHEMA)
  except ValidationError as e:raise ValueError('Invalid setting '+'.'.join(map(str,e.path))+': '+e.message) from e
  path=self.user if scope=='user' else self.project
  with _guard:lock=_locks.setdefault(str(path),threading.RLock())
  with lock:
   current=self._read(path)
   if current['revision']!=expected_revision:raise ValueError('Settings revision conflict')
   merged=current['values']
   for group,fields in values.items():merged[group]={**merged.get(group,{}),**fields}
   atomic_write_private(path,json.dumps({'revision':expected_revision+1,'values':merged},ensure_ascii=False))
  return self.load()
 def reset(self,scope,group,*,expected_revision):
  if scope not in ('user','project') or group not in DEFAULTS:raise ValueError('Unknown settings group')
  path=self.user if scope=='user' else self.project
  with _guard:lock=_locks.setdefault(str(path),threading.RLock())
  with lock:
   raw=self._read(path)
   if raw['revision']!=expected_revision:raise ValueError('Settings revision conflict')
   raw['values'].pop(group,None);raw['revision']+=1;atomic_write_private(path,json.dumps(raw,ensure_ascii=False))
  return self.load()
