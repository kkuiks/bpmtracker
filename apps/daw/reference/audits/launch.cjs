const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {_electron}=require(process.env.JOLJAK_PLAYWRIGHT);
const exe=process.env.JOLJAK_EXE,root=process.env.JOLJAK_ROOT,output=process.env.JOLJAK_AUDIT;
delete process.env.ELECTRON_RUN_AS_NODE;
(async()=>{
 const results=[];let app;
 try{
  app=await _electron.launch({executablePath:exe,args:['--user-data-dir='+path.join(output,'launch-profile')],cwd:path.dirname(exe),env:{...process.env,JOLJAK_DATA:path.join(output,'launch-workspace')},timeout:90000});
  const page=await app.firstWindow();await page.waitForSelector('.app-shell');assert.equal(await page.evaluate(()=>window.joljak.kind),'electron');assert.match(await app.evaluate(({app})=>app.getAppPath()),/development/);results.push('installed cached app startup');
  const project=JSON.parse(fs.readFileSync(path.join(output,'native-analysis-project.json'),'utf8'));
  const bad=structuredClone(project);bad.clips[0].assetId='missing';const badPath=path.join(output,'invalid.joljak');fs.writeFileSync(badPath,JSON.stringify(bad));
  await app.evaluate(({dialog},filename)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[filename]});},badPath);
  const error=await page.evaluate(()=>window.joljak.open().then(()=>null).catch(e=>e.message));assert.match(error,/Invalid audio\/track reference/);assert.equal(await page.locator('.audio-clip').count(),0);results.push('native malformed-project rejection');
  await app.evaluate(({dialog},folder)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});},output);
  const exported=await page.evaluate(async p=>{
   const completion=new Promise(resolve=>window.joljak.onJob(e=>{if(e.kind==='export'&&['complete','failed'].includes(e.stage))resolve(e);}));
   await window.joljak.exportProject(p,{start:.125,end:2.125,mix:true,stems:true,click:true,maps:true});return completion;
  },project);assert.equal(exported.stage,'complete',JSON.stringify(exported));assert.equal(exported.result.frames,96000);assert.equal(exported.result.files.length,5);fs.writeFileSync(path.join(output,'native-map-export.json'),JSON.stringify(exported.result,null,2));results.push('native click/JSON/MIDI export');
  await page.screenshot({path:path.join(output,'cached-app.png')});await app.close();app=null;
  app=await _electron.launch({executablePath:exe,args:['--user-data-dir='+path.join(output,'live-profile')],cwd:path.dirname(exe),env:{...process.env,JOLJAK_DATA:path.join(output,'live-workspace'),JOLJAK_DEV_URL:'http://127.0.0.1:8998'},timeout:90000});
  const live=await app.firstWindow();const errors=[];live.on('pageerror',e=>errors.push(e.message));await live.waitForSelector('.app-shell');assert.equal(await live.evaluate(()=>window.joljak.kind),'electron');assert.match(live.url(),/127\.0\.0\.1:8998/);
  const css=path.join(root,'apps/daw/src/styles.css'),original=fs.readFileSync(css),marker='joljak-hmr-audit-'+Date.now();
  try{fs.appendFileSync(css,'\n/* '+marker+' */\n');await live.waitForFunction(token=>Array.from(document.querySelectorAll('style')).some(e=>e.textContent.includes(token)),marker,{timeout:15000});}finally{fs.writeFileSync(css,original);}
  assert.deepEqual(errors,[]);results.push('Windows Vite/React hot reload with real desktop bridge');await app.close();app=null;
  fs.writeFileSync(path.join(output,'launch-results.json'),JSON.stringify({passed:results},null,2));console.log(JSON.stringify(results));
 }finally{if(app)await app.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
