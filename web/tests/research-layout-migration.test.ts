import {expect,it} from 'vitest';
import {readStoredLayout} from '../src/research/workspace/useWorkspace';

it('backs up malformed legacy bytes before a fallback can overwrite the record',()=>{
 const values=new Map([['layout','{"version":99}']]);
 const storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);}};
 const restored=readStoredLayout('layout',storage);
 expect(values.get('layout:pre-dockview-backup')).toBe('{"version":99}');
 expect(restored.version).toBe(1);
 values.set('layout','BROKEN');readStoredLayout('layout',storage);
 expect(values.get('layout:pre-dockview-backup')).toBe('{"version":99}');
});
