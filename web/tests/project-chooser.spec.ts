import {test,expect} from '@playwright/test';
test.use({baseURL:'http://127.0.0.1:8880'});
const token=process.env.CDAF_BROWSER_TEST_SESSION!;
const headers={Authorization:'Bearer '+token};

test('Open folder works immediately and a browser can enter a project path',async({page,request})=>{
 const fixture=await(await request.get('/api/v1/project-test-fixture',{headers})).json();
 await page.goto('/#session='+token);
 await expect(page.getByRole('button',{name:'Open folder',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'Open folder',exact:true}).click();
 await expect(page.getByLabel('Folder path',{exact:true})).toBeFocused();
 await page.getByLabel('Folder path',{exact:true}).fill(fixture.root);
 await page.getByLabel('Folder path',{exact:true}).press('Enter');
 await expect(page.locator('.wb-project-name')).toHaveText('flat-lab');
 await expect(page.getByLabel('项目运行记录',{exact:true})).toHaveValue('');
});

test('cancelling a desktop picker leaves the welcome page usable',async({page})=>{
 await page.addInitScript(()=>{Object.assign(window,{desktopStartup:{pickProjectFolder:async()=>null}});});
 await page.goto('/#session='+token);
 const open=page.getByRole('button',{name:'Open folder',exact:true});
 await expect(open).toBeEnabled();await open.click();
 await expect(open).toBeEnabled();
 await expect(page.locator('.project-host-chooser')).toBeVisible();
 await expect(page.locator('.project-host-error')).toHaveCount(0);
});

test('a desktop folder choice opens the selected project without typing a path',async({page,request})=>{
 const fixture=await(await request.get('/api/v1/project-test-fixture',{headers})).json();
 await page.addInitScript(path=>{Object.assign(window,{desktopStartup:{pickProjectFolder:async()=>path}});},fixture.root);
 await page.goto('/#session='+token);
 await page.getByRole('button',{name:'Open folder',exact:true}).click();
 await expect(page.locator('.wb-project-name')).toHaveText('flat-lab');
 await expect(page.getByLabel('项目运行记录',{exact:true})).toHaveValue('');
 await page.getByRole('button',{name:'Switch project',exact:true}).click();
 await page.locator('.project-host-recent').getByRole('button').filter({hasText:'flat-lab'}).click();
 await expect(page.locator('.project-host-chooser')).toBeHidden();
});

test('picker errors are visible and a second attempt can succeed',async({page,request})=>{
 const fixture=await(await request.get('/api/v1/project-test-fixture',{headers})).json();
 await page.addInitScript(path=>{let attempt=0;Object.assign(window,{desktopStartup:{pickProjectFolder:async()=>{if(!attempt++)throw Error('Folder dialog unavailable');return path;}}});},fixture.root);
 await page.goto('/#session='+token);await page.getByRole('button',{name:'Open folder',exact:true}).click();
 await expect(page.locator('.project-host-error')).toContainText('Folder dialog unavailable');
 await page.getByRole('button',{name:'Retry',exact:true}).click();
 await expect(page.locator('.wb-project-name')).toHaveText('flat-lab');
});

test('the folder shortcut opens path input while text editing keeps its own shortcuts',async({page})=>{
 await page.goto('/#session='+token);
 await page.getByRole('button',{name:'Open folder',exact:true}).focus();
 await page.keyboard.press('Control+k');await page.keyboard.press('Control+o');
 await expect(page.getByLabel('Folder path',{exact:true})).toBeFocused();
 await page.getByLabel('Folder path',{exact:true}).fill('unchanged input');
 await page.keyboard.press('Control+k');
 await expect(page.getByLabel('Folder path',{exact:true})).toHaveValue('unchanged input');
});

test('desktop header controls follow welcome and opened project state',async({page,request})=>{
 const fixture=await(await request.get('/api/v1/project-test-fixture',{headers})).json();
 await page.addInitScript(path=>{Object.assign(window,{desktopStartup:{close:async()=>{},pickProjectFolder:async()=>path}});},fixture.root);
 await page.route('**/api/v1/lifecycle',route=>route.fulfill({json:{owned:true}}));
 await page.route('**/api/v1/lifecycle/leases',route=>route.fulfill({json:{id:'header-fixture',owned:true}}));
 await page.goto('/#session='+token);
 await expect(page.locator('.project-host-bar').getByRole('button',{name:'退出并停止',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'打开终端',exact:true})).toBeHidden();
 await page.getByRole('button',{name:'Open folder',exact:true}).click();
 await expect(page.locator('.wb-project-name')).toHaveText('flat-lab');
 await expect(page.locator('.project-host-bar').getByRole('button',{name:'打开终端',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Switch project',exact:true}).click();
 await expect(page.getByRole('button',{name:'打开终端',exact:true})).toBeHidden();
});
