// Explicitly invoked integration audit, never part of ordinary build/start.
// Native file-dialog path choices are queued; the actual production IPC,
// renderer, AudioWorklet, Python workers, media caches and files are exercised.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {_electron}=require(process.env.JOLJAK_PLAYWRIGHT);
const output=process.env.JOLJAK_AUDIT,exe=process.env.JOLJAK_EXE;
delete process.env.ELECTRON_RUN_AS_NODE;
const results=[], errors=[];let app,page;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function state(){return page.evaluate(()=>{
  const el=document.querySelector('.app-shell'),key=Object.keys(el).find(k=>k.startsWith('__reactFiber$'));
  let root=el[key];while(root.return)root=root.return;root=root.stateNode.current;
  function search(f){if(!f)return null;let h=f.memoizedState;while(h&&typeof h==='object'){if(h.memoizedState?.format==='joljak-project')return h.memoizedState;h=h.next;}return search(f.child)||search(f.sibling);}
  return JSON.parse(JSON.stringify(search(root)));
});}
async function check(name,fn){if(process.env.JOLJAK_TEST_FILTER&&!name.includes(process.env.JOLJAK_TEST_FILTER))return;const started=Date.now();try{await fn();results.push({name,status:'pass',ms:Date.now()-started});}
 catch(e){results.push({name,status:'fail',ms:Date.now()-started,error:e.stack});try{await page.screenshot({path:path.join(output,`failure-${results.length}.png`)});}catch{} }
 console.log(JSON.stringify(results.at(-1)));fs.writeFileSync(path.join(output,(process.env.JOLJAK_AUDIT_REPORT || 'windows-results.json')),JSON.stringify({results,errors},null,2));
 try{fs.writeFileSync(path.join(output,'windows-job-events.json'),JSON.stringify(await page.evaluate(()=>window.auditJobs),null,2));}catch{} }
async function menu(name,command){await page.keyboard.press('Escape');await page.getByRole('button',{name,exact:true}).click();await page.locator('.app-dropdown').getByRole('button',{name:new RegExp('^'+command+'(?:…)?(?:\\s+Ctrl|$)')}).click();}
async function queue(kind,paths){await app.evaluate(({dialog},{kind,paths})=>{if(!globalThis.auditQueues){globalThis.auditQueues={open:[],save:[]};
 dialog.showOpenDialog=async()=>{const v=globalThis.auditQueues.open.shift();return v?{canceled:false,filePaths:v}:{canceled:true,filePaths:[]};};
 dialog.showSaveDialog=async()=>{const v=globalThis.auditQueues.save.shift();return v?{canceled:false,filePath:v[0]}:{canceled:true};};}
 globalThis.auditQueues[kind].push(paths);},{kind,paths});}
async function importAudio(names,mode='sequence',copy=false){await queue('open',names.map(n=>path.join(output,'media',n)));
 await page.getByRole('button',{name:'Import Audio',exact:true}).first().click();await page.locator('.modal').getByLabel('Placement').selectOption(mode);
 if(copy)await page.locator('.modal').getByRole('checkbox').check();
 const before=(await state()).assets.length;await page.locator('.modal').getByRole('button',{name:'Import Audio',exact:true}).click();
 await page.waitForFunction(before=>{const labels=document.querySelectorAll('.audio-clip');return labels.length>before;},before,{timeout:60000});
 await pause(120);return state();}
async function fresh(){await menu('File','New Project');await pause(100);}
async function select(index=0){await page.locator('.audio-clip').nth(index).click({position:{x:20,y:25}});}
async function key(key){await page.locator('.toolbar').count().then(async()=>{await page.locator('.timeline-ruler').click({position:{x:8,y:15}});});await page.keyboard.press(key);await pause(80);}
async function field(label,value){const input=page.getByLabel(label,{exact:true});await input.fill(String(value));await input.press('Enter');await pause(80);}
async function launch(data){app=await _electron.launch({executablePath:exe,args:[],env:{...process.env,JOLJAK_DATA:data},timeout:90000});page=await app.firstWindow({timeout:90000});page.setDefaultTimeout(15000);
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());await page.waitForSelector('.app-shell');
 await page.evaluate(()=>{window.auditJobs=[];window.joljak.onJob(event=>window.auditJobs.push(event));});}
async function job(id,timeout=180000){await page.waitForFunction(id=>window.auditJobs.some(j=>j.id===id&&['complete','failed'].includes(j.stage)),id,{timeout});
 const result=await page.evaluate(id=>window.auditJobs.find(j=>j.id===id&&['complete','failed'].includes(j.stage)),id);assert.equal(result.stage,'complete',JSON.stringify(result));return result.result;}

module.exports={fs,path,assert,output,results,errors,pause,state,check,menu,queue,importAudio,fresh,select,key,field,launch,job,context:()=>({app,page})};
