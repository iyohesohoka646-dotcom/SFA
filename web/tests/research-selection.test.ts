import {describe,it,expect} from 'vitest';
import {choose, selectionKey, projectGraph, objectRows} from '../src/research/workspace/selection';
const refs=Array.from({length:1000},(_,i)=>({kind:'data' as const,logical_key:'f::'+i,object_id:String(i)}));
describe('shared scientific selection',()=>{
 it('range and all include offscreen rows without navigation',()=>{
  let state={targets:[],anchor:null};
  state=choose(state,refs[3],refs,{});
  state=choose(state,refs[20],refs,{shift:true});
  expect(state.targets).toHaveLength(18);
  state=choose(state,refs[0],refs,{all:true});
  expect(state.targets).toHaveLength(1000);
  expect(Object.keys(state).sort()).toEqual(['anchor','targets']);
 });
 it('ctrl toggles and preserves independent targets',()=>{
  let s=choose({targets:[],anchor:null},refs[0],refs,{});
  s=choose(s,refs[4],refs,{toggle:true});
  expect(s.targets.map(selectionKey)).toEqual([selectionKey(refs[0]),selectionKey(refs[4])]);
  expect(choose(s,refs[0],refs,{toggle:true}).targets).toEqual([refs[4]]);
 });
 it('collapsed compound graph retains original relationships without dangling ends',()=>{
  const graph={roots:['file'],blocks:[{id:'file',kind:'file',label:'f'},{id:'fn',parent:'file',kind:'function',label:'fun'}],
    nodes:[{id:'a',block_id:'fn',kind:'operation',ports:[]},{id:'b',block_id:'file',kind:'operation',ports:[]}],
    edges:[{id:'e',source:'a',target:'b',kind:'data'}]};
  const p=projectGraph(graph,new Set(['fn']),'structure');
  expect(p.edges[0].source).toBe('fn');
  expect(p.edges[0].original_ids).toContain('e');
  expect(p.nodes.some(n=>n.id==='a')).toBe(false);
  expect(p.edges.every(e=>p.nodes.some(n=>n.id===e.source)&&p.nodes.some(n=>n.id===e.target))).toBe(true);
 });
});
