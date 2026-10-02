import {describe,it,expect} from 'vitest';
import {choose, selectionKey, projectGraph, objectRows, initialCollapsed, selectionBlocks} from '../src/research/workspace/selection';
const refs=Array.from({length:1000},(_,i)=>({kind:'data' as const,logical_key:'f::'+i,object_id:String(i)}));
describe('shared scientific selection',()=>{
 it('selected child marks every ancestor partial and parent selection covers descendants',()=>{
  const blocks=[{id:'file',parent_id:null},{id:'fn',parent_id:'file'},{id:'loop',parent_id:'fn'}];
  const leaf={kind:'data',logical_key:'x',block_id:'loop'};
  const child=selectionBlocks(blocks,[leaf]);expect([...child.partial].sort()).toEqual(['file','fn','loop']);expect(child.covered.size).toBe(0);
  const parent=selectionBlocks(blocks,[{kind:'function',logical_key:'f',block_id:'fn'}]);expect(parent.covered.has('loop')).toBe(true);expect(parent.partial.has('file')).toBe(true);expect(parent.covered.has('file')).toBe(false);
 });

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
 it('large flat files collapse explicitly without hiding the count or self edges',()=>{
  const graph={roots:['file'],blocks:[{id:'file',kind:'file',label:'f',members:['a','b']}],
    nodes:Array.from({length:1000},(_,i)=>({id:'n'+i,block_id:'file',kind:'operation'})),
    edges:[{id:'e',source:'n0',target:'n1',kind:'data'}]};
  const closed=initialCollapsed(graph,new Set());
  expect(closed.has('file')).toBe(true);
  const p=projectGraph(graph,closed,'structure');
  expect(p.nodes).toHaveLength(1);expect(p.omitted).toBe(1000);expect(p.edges).toHaveLength(0);
 });
 it('explicit evidence versions remain separate in a shared selection',()=>{
  const first={...refs[0],snapshot_id:'old',exact_evidence:true},second={...refs[0],snapshot_id:'new',exact_evidence:true};
  let selected=choose({targets:[],anchor:null},first,[first,second],{});
  selected=choose(selected,second,[first,second],{toggle:true});
  expect(selected.targets).toHaveLength(2);
  expect(selectionKey(first)).not.toBe(selectionKey(second));
 });
});
