import {expect,test} from 'vitest';
import {numericCell,displayCell,planeAxes,cellColor} from '../src/research/matrix-renderer';
import {explainOperation} from '../src/research/explanation-templates';
import {RendererRegistry} from '../src/research/renderer-registry';

test('complex and nonfinite cells preserve their scientific meaning',()=>{
  const complex={type:'complex',real:3,imag:4};
  expect(numericCell(complex,'real')).toBe(3);
  expect(numericCell(complex,'imag')).toBe(4);
  expect(numericCell(complex,'magnitude')).toBe(5);
  expect(Number.isNaN(numericCell({type:'nonfinite',value:'nan'},'real'))).toBe(true);
  expect(numericCell({type:'unavailable',type_name:'lazy.Tensor'},'real')).toBeNull();
  expect(displayCell(null)).toBe('缺失');
  expect(displayCell(complex)).toBe('3 + 4i');
  expect(planeAxes([2,3,4,5])).toEqual({fixed:[0,1],plane:[2,3]});
  expect(planeAxes([])).toEqual({fixed:[],plane:[]});
});

test('heatmap separates close large values and labels constant and missing data distinctly',()=>{
  expect(cellColor(1000,1000,1001)).not.toBe(cellColor(1001,1000,1001));
  expect(cellColor(1000,1000,1001)).toBe(cellColor(0,0,1));
  expect(cellColor(5,5,5)).toBe(cellColor(0,0,0));
  expect(cellColor(null,0,1)).not.toBe(cellColor(NaN,0,1));
});

test('rules explain mathematical facts without inventing domain or units',()=>{
  const operation={id:'o',run_id:'r',label:'mu = X.mean(axis=0)',kind:'reduce',source:null,scope_id:'main',iteration:1,input_snapshots:['x'],output_snapshots:['y'],status:'completed',duration_ms:2,parameters:{},provenance:'inferred' as const};
  const explanation=explainOperation(operation,[{schema_version:1 as const,kind:'tensor',backend:'third-party',type_name:'T',shape:[4,8],dtype:'float32',nbytes:null,device:null,axes:[],unit:null,capabilities:['preview'],metadata:{}}]);
  expect(explanation.text).toContain('axis=0');
  expect(explanation.text).not.toContain('特征');
  expect(explanation.origin).toBe('rule');
  expect(explanation.uncertainty.join(' ')).toContain('单位');
});

test('independent renderer plugin is selected by extensible backend capability',()=>{
  const registry=new RendererRegistry();
  registry.register({protocolVersion:1,id:'example.points',supports:(d)=>d.backend==='example.pointcloud'&&d.capabilities.includes('preview'),Component:()=>null});
  const descriptor={schema_version:1 as const,kind:'point-cloud',backend:'example.pointcloud',type_name:'Points',shape:[2,2],dtype:null,nbytes:null,device:null,axes:[],unit:null,capabilities:['preview'],metadata:{}};
  expect(registry.resolve(descriptor)?.id).toBe('example.points');
  expect(registry.resolve({...descriptor,backend:'unregistered'})).toBeUndefined();
  expect(()=>registry.register({protocolVersion:2,id:'v2',supports:()=>true,Component:()=>null})).toThrow(/v1/);
});
