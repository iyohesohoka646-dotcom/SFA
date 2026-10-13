const {test}=require('node:test');
const assert=require('node:assert/strict');
const {BackendController}=require('../src/controller.cjs');
test('closing during pending startup cleans its child and suppresses readiness',async()=>{
 let complete;let stopped=0;const states=[];
 const host={start:()=>new Promise(resolve=>complete=resolve),stop:async()=>{stopped++;complete?.();}};
 const owner=new BackendController(()=>host,state=>states.push(state));
 const starting=owner.start();await new Promise(resolve=>setImmediate(resolve));
 await owner.close();await starting;
 assert.equal(stopped,1);assert.ok(!states.includes('ready'));
});
test('failed startup retries after cleanup and repeated starts share readiness',async()=>{
 let attempts=0;let stopped=0;
 const owner=new BackendController(()=>({start:async()=>{if(++attempts===1)throw Error('fixture');return {port:1234};},stop:async()=>{stopped++;}}),()=>{});
 await assert.rejects(owner.start());assert.equal(owner.state,'error');
 const one=await owner.start();assert.equal(one.port,1234);assert.equal((await owner.start()).port,1234);
 await owner.close();assert.equal(attempts,2);assert.equal(stopped,2);
});
