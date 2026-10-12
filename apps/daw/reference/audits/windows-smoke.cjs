// This harness drives the actual Windows Electron app. Dialog queues only
// replace interactive path selection; IPC, decoding and UI remain real.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {_electron} = require(process.env.JOLJAK_PLAYWRIGHT);
const output = process.env.JOLJAK_AUDIT;
delete process.env.ELECTRON_RUN_AS_NODE;
(async()=>{
  const app=await _electron.launch({executablePath:process.env.JOLJAK_EXE,args:[],env:{...process.env,JOLJAK_DATA:path.join(output,'workspace')},timeout:90000});
  const page=await app.firstWindow({timeout:90000}); const errors=[];
  page.on('pageerror',e=>errors.push(e.message)); page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.waitForSelector('.app-shell');
  console.log(JSON.stringify({stage:'opened',title:await page.title(),bridge:await page.evaluate(()=>window.joljak?.kind),text:(await page.locator('body').innerText()).slice(0,500)}));
  await page.screenshot({path:path.join(output,'startup.png')});
  assert.equal(await page.evaluate(()=>window.joljak?.kind),'electron');
  console.log(JSON.stringify({stage:'startup-errors',errors}));
  await app.close();
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
