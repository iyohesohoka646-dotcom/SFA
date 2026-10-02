import {test,expect} from '@playwright/test';
import {session} from './session';
import {researchApi} from './scientific-helpers';
test('embedded Python is interactive, reconnects when hidden and ends explicitly',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await page.getByRole('button',{name:'终端',exact:true}).click();
 await expect(page.getByLabel('终端配置')).toBeVisible();await page.getByLabel('终端配置').selectOption('python');
 await page.getByRole('button',{name:'新建终端',exact:true}).click();
 const input=page.getByLabel('终端输入',{exact:true});await expect(input).toBeVisible();await input.focus();await page.keyboard.insertText("print('WEB-'+str(40+2))");await page.keyboard.press('Enter');await page.getByLabel('无障碍输出',{exact:true}).check();
 await expect.poll(async()=>await page.locator('.xterm-accessibility-tree').innerText()).toContain('WEB-42');
 const selected=await page.getByLabel('终端会话').inputValue();
 await page.getByRole('button',{name:'缩小 main 视图',exact:true}).click();await page.getByRole('button',{name:'恢复 main 视图',exact:true}).click();
 await expect(page.getByLabel('终端会话')).toHaveValue(selected);
 await expect.poll(async()=>await page.locator('.xterm-accessibility-tree').innerText()).toContain('WEB-42');
 await page.getByRole('button',{name:'结束会话',exact:true}).click();
 await expect.poll(async()=>(await researchApi(page,'research/terminals/'+selected)).status).toBe('ended');
});
