"""Eight executable cases. Each creates a reviewable, isolated project.

python -X utf8 examples/research/cases/run_cases.py --output .work/cases
Add --provider PROFILE to use an explicitly configured model for the Skill.
Without a provider that case verifies offline scope/Skill handling, not inference.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.models import ProbeInstance
from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector
from contract_driven_ai_flow.research.workbench.scopes import source_targets
from contract_driven_ai_flow.research.workbench.data_semantics import DataSemantics, AxisSemantics, ColumnSemantics

NAMES = ('matrix', 'table', 'functions', 'controls', 'structure', 'combination', 'program', 'skill')
HERE = Path(__file__).resolve().parent


def run_case(name, root, *, failure=False, provider='offline'):
    if name not in NAMES:
        raise ValueError('Unknown case')
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    script = root / 'analysis.py'
    if script.exists():
        raise ValueError('Case destination already contains source; use a new directory')
    shutil.copyfile(HERE / (name + '.py'), script)
    if name == 'structure' and not failure:
        script.write_text('def square(x):\n return x*x\nX=square(3)\n', encoding='utf-8')
    with ResearchService(root) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        config = wb.configurations.load()
        config.script = str(script)
        config.interpreter = sys.executable
        config.arguments = ['--failure'] if failure else []
        config.capture = 'summary'
        probes = []
        expected = 'fail' if failure else 'pass'
        check = None
        if name == 'matrix':
            probes = [ProbeInstance(definition_id='view.matrix', binding='X', parameters={'show_values': True, 'precision': 2}),
                      ProbeInstance(id='case-check', definition_id='check.finite', binding='X')]
            check = 'case-check'
        elif name == 'table':
            probes = [ProbeInstance(definition_id='view.table', binding='T'),
                      ProbeInstance(id='case-check', definition_id='check.shape', binding='T', parameters={'expected': [3, 2]})]
            check = 'case-check'
        elif name == 'functions':
            probes = [ProbeInstance(id='case-check', definition_id='check.timing', binding='normalize', parameters={'maximum_ms': 0 if failure else 30000})]
            check = 'case-check'
        elif name == 'controls':
            probes = [ProbeInstance(definition_id='view.controls', selector=ScopeSelector()),
                      ProbeInstance(id='case-check', definition_id='check.range', binding='X', parameters={'min': -20, 'max': 20})]
            check = 'case-check'
        elif name == 'structure':
            file_ref = next(t for t in source_targets(analysis) if t.kind == 'file')
            probes = [ProbeInstance(id='case-check', definition_id='check.structure', binding=file_ref.logical_key)]
            check = 'case-check'
            expected = 'unknown' if failure else 'pass'
        elif name == 'combination':
            refs = [t for t in source_targets(analysis) if t.kind == 'data' and t.logical_key.endswith(('::A', '::B'))]
            roles = dict(zip(('left', 'right'), sorted(refs, key=lambda t: t.logical_key)))
            probes = [ProbeInstance(definition_id='view.compare', inputs=roles, parameters={'shared_scale': True, 'linked_zoom': True}),
                      ProbeInstance(id='case-check', definition_id='derive.matmul', inputs=roles)]
            check = 'case-check'
            expected = 'error' if failure else 'ready'
        elif name == 'program':
            shutil.copyfile(HERE / 'lab_probe.py', root / 'lab_probe.py')
            wb.resources.import_manifest({'id':'laboratory', 'label':'Laboratory checks', 'version':'1', 'source':'local', 'definitions':[
                {'id':'laboratory.input-count', 'label':'Input count', 'capability':'check', 'execution':'program', 'entrypoint':'lab_probe:evaluate',
                 'evidence':'metadata', 'parameter_schema':{'type':'object','properties':{'minimum':{'type':'integer','minimum':1}},'required':['minimum'],'additionalProperties':False}}]})
            wb.resources.enable('laboratory')
            probes = [ProbeInstance(id='case-check', definition_id='laboratory.input-count', binding='X', parameters={'minimum':2 if failure else 1})]
            check = 'case-check'
        elif name == 'skill':
            shutil.copyfile(HERE / 'interpret-data.md', root / 'interpret-data.md')
            skill = wb.harness.skills.register(root / 'interpret-data.md')
            probes = [ProbeInstance(id='case-check', definition_id='interpret.skill', binding='mean',
                      parameters={'skill_id':'missing-skill' if failure else skill['id'], 'provider_id':provider})]
            check = 'case-check'
            expected = 'error' if failure else 'unknown' if provider == 'offline' else 'ready'
        config.probes = probes
        wb.configure(config, expected_revision=config.revision)
        task = wb.jobs.wait(wb.execute(wb.plan(analysis.id).id).id, 60)
        outputs = wb.outputs(task_id=task.id)
        selected = [o for o in outputs if o['instance_id'] == check]
        verified = task.calculation_status == 'completed' and bool(selected) and all(o['status'] == expected for o in selected)
        if name in ('matrix', 'table'):
            snapshot = next(s for s in research.store.snapshots(task.run_id) if s.name == ('X' if name == 'matrix' else 'T'))
            if name == 'matrix':
                semantics = DataSemantics(logical_key=snapshot.logical_key, kind='matrix', element_meaning='Response amplitude', unit='a.u.',
                    axes=[AxisSemantics(label='Condition', labels=['rest', 'stimulus']), AxisSemantics(label='Time', unit='s', coordinates=[0,1,2])])
            else:
                semantics = DataSemantics(logical_key=snapshot.logical_key, kind='table', columns=[
                    ColumnSemantics(key='time', label='Time', unit='s'), ColumnSemantics(key='signal', label='Amplitude', unit='mV')])
            wb.semantics.save(semantics, shape=snapshot.descriptor.shape, expected_revision=0)
        return {'case':name, 'failure':failure, 'verified':verified, 'outcome':selected[0]['status'] if selected else 'missing',
                'run_id':task.run_id, 'task_id':task.id, 'output_ids':task.output_ids,
                'inference_sent':name == 'skill' and provider != 'offline', 'project':str(root)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=NAMES, action='append')
    parser.add_argument('--provider', default='offline')
    args = parser.parse_args()
    results = [run_case(name,args.output/name/variant,failure=variant=='failure',provider=args.provider)
               for name in args.case or NAMES for variant in ('success','failure')]
    print(json.dumps(results,ensure_ascii=False,indent=2))
    raise SystemExit(0 if all(r['verified'] for r in results) else 1)
