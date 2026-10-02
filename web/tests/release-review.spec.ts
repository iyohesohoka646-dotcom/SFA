import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
import {session} from './session';
test.use({baseURL:'http://127.0.0.1:8879'});
const deferred=()=>{let resolve!:()=>void;const promise=new Promise<void>(done=>resolve=done);return {promise,resolve};};
const value=(id:string,name:string,version=1)=>({schema_version:1,id,run_id:'review',name,binding_id:'main:'+name,scope_id:'main',version,
 descriptor:{schema_version:1,kind:'tensor',backend:'numpy',type_name:'ndarray',shape:[2,100,100],dtype:'int64',axes:[],capabilities:['preview','slice'],metadata:{}},
 parents:[],observed_at:'',source:null,operation_id:null,provenance:'observed',fidelity:'sampled',artifact_ref:null,
 sample:{values:[[0,3],[300,303]],row_indices:[0,3],column_indices:[0,3],fixed_axes:{0:0}},statistics:{},coverage:{},redacted:[],truncation:[]});
async function fixture(page:Page,delays:{history?:ReturnType<typeof deferred>;slice?:ReturnType<typeof deferred>}={}){
 const entered=deferred(),x=value('x2','X',2),y=value('y1','Y'),old=value('x1','X');
 const run={id:'review',name:'Review fixture',script:'analysis.py',interpreter:'python',source_digest:'a',status:'completed',summary:{},environment:{},finished:'',started:'',owner:1};
 await page.route('**/api/v1/research/**',async route=>{
  const path=new URL(route.request().url()).pathname;let json:unknown={};
  if(path.includes('/workbench')){await route.continue();return;}
  if(path.endsWith('/info'))json={root:'.',interpreter:'python',examples:[]};
  else if(path.endsWith('/experiment'))json=null;
  else if(path.endsWith('/runs'))json=[run];
  else if(path.endsWith('/bootstrap'))json={run,cursor:4,binding_count:2,parent_bindings:{},snapshots:[x,y],operations:[],probe_events:[{schema_version:1,run_id:'review',sequence:1,kind:'capture.marker',timestamp:'',snapshot_id:'x1',payload:{}}]};
  else if(path.endsWith('/source'))json={path:'analysis.py',digest:'a',code:'X = data\nY = X+1'};
  else if(path.endsWith('/probe-types'))json=[];
  else if(path.endsWith('/history'))json=[x,old];
  else if(path.endsWith('/slice')){const axis=route.request().postDataJSON().selectors[0].index;entered.resolve();if(delays.slice)await delays.slice.promise;json={available:true,values:[[axis*10000,axis*10000+1],[axis*10000+100,axis*10000+101]],shape:[2,2]};}
  else if(path.includes('/snapshots/')){if(path.endsWith('/x1')&&delays.history){entered.resolve();await delays.history.promise;}json=path.endsWith('/y1')?y:path.endsWith('/x1')?old:x;}
  await route.fulfill({json}).catch(()=>{});
 });
 await page.goto(`/#session=${session}`);
 await expect(page.getByRole('img',{name:'矩阵热图'})).toBeVisible();
 return entered;
}

test('review: delayed timeline selection cannot override a newer variable',async({page})=>{
 const pending=deferred(),entered=await fixture(page,{history:pending});
 await page.getByRole('button',{name:'查看变量历史'}).click();
 await page.getByRole('button',{name:'版本 1',exact:true}).click();await entered.promise;
 await page.getByRole('button',{name:/^Y ·/}).click();await expect(page.getByTestId('current-variable')).toHaveText('Y');
 pending.resolve();await page.waitForTimeout(250);await expect(page.getByTestId('current-variable')).toHaveText('Y');
});

test('review: exact slice coordinates replace sampled preview coordinates',async({page})=>{
 await fixture(page);await page.getByLabel('固定 axis 0').fill('1');
 await page.getByRole('button',{name:'读取此版本切片',exact:true}).click();
 await expect(page.getByTestId('slice-result')).toContainText('已读取');
 await page.getByRole('img',{name:'矩阵热图'}).focus();await page.keyboard.press('ArrowRight');
 await expect(page.getByTestId('matrix-cell-value')).toHaveText('[0, 1] = 10001');
});

test('review: changing fixed axis invalidates pending exact slice',async({page})=>{
 const pending=deferred(),entered=await fixture(page,{slice:pending});
 await page.getByLabel('固定 axis 0').fill('1');await page.getByRole('button',{name:'读取此版本切片',exact:true}).click();await entered.promise;
 await page.getByLabel('固定 axis 0').fill('0');pending.resolve();await page.waitForTimeout(250);
 await expect(page.getByTestId('matrix-cell-value')).toHaveText('[0, 0] = 0');
 await expect(page.locator('.wb-evidence-bar').first()).toContainText('sampled');
});

test('review: legacy run selection discards delayed older responses',async({page})=>{
 await page.goto(`http://127.0.0.1:8877/?legacy=1#session=${session}`);
 const headers={Authorization:'Bearer '+session};
 const project=await (await page.request.get('http://127.0.0.1:8877/api/v1/project',{headers})).json();
 const created=await page.request.post('http://127.0.0.1:8877/api/v1/runs',{headers,data:{input:project.project.metadata.inputs.failure,base_revision:project.revision}});expect(created.status()).toBe(202);
 await page.reload();
 await page.getByRole('tab',{name:'Runs',exact:true}).click();
 const selection=page.getByLabel('Select run'),ids=await selection.locator('option').evaluateAll(options=>options.map(o=>(o as HTMLOptionElement).value).filter(Boolean));
 expect(ids.length).toBeGreaterThanOrEqual(3);const old=ids[1],next=ids[2],pending=deferred(),entered=deferred(),delivered=deferred();
 await expect(selection).toHaveValue(ids[0]);await page.waitForTimeout(150);
 await page.route('**/api/v1/runs/'+old,async route=>{const response=await route.fetch();entered.resolve();await pending.promise;await route.fulfill({response}).catch(()=>{});delivered.resolve();});
 await selection.selectOption(old);await entered.promise;await selection.selectOption(next);
 await expect(selection).toHaveValue(next);
 pending.resolve();await delivered.promise;await page.waitForTimeout(300);await expect(selection).toHaveValue(next);
});
