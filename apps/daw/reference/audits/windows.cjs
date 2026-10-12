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
 console.log(JSON.stringify(results.at(-1)));fs.writeFileSync(path.join(output,'windows-results.json'),JSON.stringify({results,errors},null,2));
 try{fs.writeFileSync(path.join(output,'windows-job-events.json'),JSON.stringify(await page.evaluate(()=>window.auditJobs),null,2));}catch{} }
async function menu(name,command){await page.keyboard.press('Escape');await page.getByRole('button',{name,exact:true}).click();await page.locator('.app-dropdown').getByRole('button',{name:new RegExp('^'+command+'(?:…)?(?:\\s+Ctrl|$)')}).click();}
async function queue(kind,paths){await app.evaluate(({dialog},{kind,paths})=>{if(!globalThis.auditQueues){globalThis.auditQueues={open:[],save:[]};
 dialog.showOpenDialog=async()=>{const v=globalThis.auditQueues.open.shift();return v?{canceled:false,filePaths:v}:{canceled:true,filePaths:[]};};
 dialog.showSaveDialog=async()=>{const v=globalThis.auditQueues.save.shift();return v?{canceled:false,filePath:v[0]}:{canceled:true};};}
 globalThis.auditQueues[kind].push(paths);},{kind,paths});}
async function importAudio(names,mode='sequence',copy=false){await queue('open',names.map(n=>path.join(output,'media',n)));
 await page.getByRole('button',{name:'Import Audio',exact:true}).first().click();await page.locator('.modal').getByLabel('Placement').selectOption(mode);
 await page.locator('.modal').getByRole('checkbox').setChecked(copy);
 const before=(await state()).assets.length;await page.locator('.modal').getByRole('button',{name:'Import Audio',exact:true}).click();
 await page.waitForFunction(before=>{const labels=document.querySelectorAll('.audio-clip');return labels.length>before;},before,{timeout:60000});
  await pause(120);return state();}
async function fresh(){await menu('File','New Project');await pause(100);}
async function select(index=0){await page.locator('.audio-clip').nth(index).click({position:{x:20,y:25}});}
async function key(key){await page.locator('.toolbar').count().then(async()=>{await page.locator('.timeline-ruler').click({position:{x:8,y:15}});});await page.keyboard.press(key);await pause(80);}
async function field(label,value){const input=page.getByLabel(label,{exact:true});await input.fill(String(value));await input.press('Enter');await pause(80);}
async function launch(data){app=await _electron.launch({executablePath:exe,args:['--user-data-dir='+path.join(data,'electron-profile')],cwd:path.dirname(exe),env:{...process.env,JOLJAK_DATA:data},timeout:90000});page=await app.firstWindow({timeout:90000});page.setDefaultTimeout(15000);
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());await page.waitForSelector('.app-shell');
 await page.evaluate(()=>{window.auditJobs=[];window.joljak.onJob(event=>window.auditJobs.push(event));});return {app,page};}
async function job(id,timeout=180000){await page.waitForFunction(id=>window.auditJobs.some(j=>j.id===id&&['complete','failed'].includes(j.stage)),id,{timeout});
 const result=await page.evaluate(id=>window.auditJobs.find(j=>j.id===id&&['complete','failed'].includes(j.stage)),id);assert.equal(result.stage,'complete',JSON.stringify(result));return result.result;}
(async()=>{
 await launch(path.join(output,`integration-${Date.now()}`));
 if(process.env.JOLJAK_EXTENDED_ONLY){
  const seed=path.join(output,'seed.joljak');fs.writeFileSync(seed,fs.readFileSync(path.join(output,'native-analysis-project.json')));await queue('open',[seed]);await menu('File','Open Project');await page.waitForFunction(()=>window.auditJobs.some(j=>j.kind==='decode'&&j.stage==='complete'),null,{timeout:60000});await pause(150);
 }else{
 await check('Windows startup, production protocol and sandbox preload',async()=>{assert.equal(await page.evaluate(()=>window.joljak.kind),'electron');assert.match(page.url(),/^joljak:\/\/app\//);assert.equal(await page.evaluate(()=>typeof window.require),'undefined');await page.screenshot({path:path.join(output,'windows-startup.png')});});
 await check('WAV/MP3/FLAC sequence import and rendered waveforms',async()=>{const p=await importAudio(['mono48.wav','stereo44.mp3','stereo96.flac']);assert.equal(p.clips.length,3);assert.equal(p.tracks.length,1);assert.deepEqual(p.clips.map(c=>c.start),[0,8.5,17]);assert.ok(p.assets.every(a=>a.playbackRate===48000));assert.equal(await page.locator('canvas').count(),3);});
 await check('UI add track, move, Alt-drag copy, undo and redo',async()=>{await page.keyboard.press('t');await pause(100);const before=await state();assert.equal(before.tracks.length,2);
 const box=await page.locator('.audio-clip').first().boundingBox();await page.mouse.move(box.x+35,box.y+30);await page.mouse.down();await page.mouse.move(box.x+95,box.y+122,{steps:5});await page.mouse.up();await pause(100);
 const moved=await state();assert.equal(moved.clips[0].trackId,moved.tracks[1].id);assert.ok(moved.clips[0].start>before.clips[0].start);
 await page.keyboard.press('Control+z');await pause(80);assert.deepEqual((await state()).clips,before.clips);await page.keyboard.press('Control+Shift+z');await pause(80);assert.deepEqual((await state()).clips,moved.clips);
 const b=await page.locator('.audio-clip').filter({hasText:'mono48'}).boundingBox();await page.keyboard.down('Alt');await page.mouse.move(b.x+20,b.y+25);await page.mouse.down();await page.mouse.move(b.x+170,b.y+25,{steps:5});await page.mouse.up();await page.keyboard.up('Alt');await pause(100);assert.equal((await state()).clips.length,4);});
 await check('UI split tool, trim corners and clear selection shortcut',async()=>{await fresh();await importAudio(['mono48.wav']);await page.keyboard.press('3');const box=await page.locator('.audio-clip').boundingBox();await page.mouse.click(box.x+box.width*.5,box.y+30);await pause(100);assert.equal((await state()).clips.length,2);
 await page.keyboard.press('1');const handle=await page.locator('.trim-handle.left').first().boundingBox();await page.mouse.move(handle.x+1,handle.y+5);await page.mouse.down();await page.mouse.move(handle.x+20,handle.y+5,{steps:5});await page.mouse.up();await pause(100);assert.ok((await state()).clips[0].sourceStart>0);
 await select();await page.keyboard.press('Control+Shift+a');await pause(80);assert.equal(await page.locator('.audio-clip.selected').count(),0);});
 await check('linked stem import and group moves',async()=>{await fresh();const p=await importAudio(['mono48.wav','stereo44.wav'],'stems');assert.equal(p.tracks.length,2);assert.equal(p.clips[0].groupId,p.clips[1].groupId);
 const b=await page.locator('.audio-clip').first().boundingBox();await page.mouse.move(b.x+30,b.y+25);await page.mouse.down();await page.mouse.move(b.x+60,b.y+25,{steps:4});await page.mouse.up();await pause(100);const moved=await state();assert.ok(moved.clips[0].start>0);assert.equal(moved.clips[0].start,moved.clips[1].start);});
 await check('Inspector pan/volume and track mute/solo shortcuts',async()=>{await select();await field('Volume',-6);await field('Pan',-25);let p=await state();assert.ok(Math.abs(p.tracks[0].gain-10**(-6/20))<1e-8);assert.equal(p.tracks[0].pan,-.25);
 await page.keyboard.press('m');await pause(80);assert.equal((await state()).tracks[0].mute,true);await page.keyboard.press('m');await page.keyboard.press('s');await pause(80);assert.equal((await state()).tracks[0].solo,true);await page.keyboard.press('s');});
 await check('real AudioContext playback, stop, seek and cycle',async()=>{await page.locator('button[title="Go to project start (Num .)"]').click();await page.locator('button[title="Start / Stop (Space)"]').click();await page.waitForFunction(()=>document.querySelector('footer')?.textContent.includes('Playing'),null,{timeout:15000});
 await pause(650);const time=await page.locator('.position-display span').textContent();assert.notEqual(time,'00:00.000');await page.locator('button[title="Stop (Num 0)"]').click();await pause(100);assert.ok(!(await page.locator('footer').innerText()).includes('Playing'));
 await select();await page.keyboard.press('p');await pause(80);assert.ok(await page.locator('.locator-range').count());await page.keyboard.press('Alt+p');await pause(350);await page.locator('button[title="Stop (Num 0)"]').click();});
 const projectFile=path.join(output,'saved','audit.joljak');fs.mkdirSync(path.dirname(projectFile),{recursive:true});
 await check('save, repeated overwrite and open round trip',async()=>{await queue('save',[projectFile]);await menu('File','Save');await page.waitForFunction(()=>document.querySelector('.title-project')?.textContent.trim()==='audit');const before=await state();
 await select();await field('Pan',30);await menu('File','Save');await pause(200);assert.equal(JSON.parse(fs.readFileSync(projectFile,'utf8')).tracks[0].pan,.3);
 await fresh();await queue('open',[projectFile]);await menu('File','Open Project');await pause(250);const reopened=await state();assert.equal(reopened.clips.length,before.clips.length);assert.equal(reopened.tracks[0].pan,.3);});
 await check('Save As collection uses portable media paths',async()=>{const target=path.join(output,'portable-project','collected.joljak');fs.mkdirSync(path.dirname(target),{recursive:true});await queue('save',[target]);await menu('File','Save As');await page.locator('.modal').getByRole('checkbox').check();await page.locator('.modal').getByRole('button',{name:'Choose File & Save'}).click();await pause(250);
 const saved=JSON.parse(fs.readFileSync(target,'utf8'));assert.ok(saved.assets.every(a=>!path.isAbsolute(a.sourcePath)));assert.ok(saved.assets.every(a=>fs.existsSync(path.resolve(path.dirname(target),a.sourcePath))));});
 await check('Windows WAV mix/stem export uses common frame count',async()=>{await queue('open',[output]);await page.getByRole('button',{name:'Export',exact:true}).click();await page.locator('.modal').getByRole('button',{name:'Choose Folder & Export'}).click();await page.waitForFunction(()=>window.auditJobs.some(j=>j.kind==='export'&&['complete','failed'].includes(j.stage)),null,{timeout:60000});
 const result=await page.evaluate(()=>window.auditJobs.findLast(j=>j.kind==='export'&&['complete','failed'].includes(j.stage)));assert.equal(result.stage,'complete',JSON.stringify(result));fs.writeFileSync(path.join(output,'native-export-result.json'),JSON.stringify(result.result,null,2));assert.equal(result.result.files.length,3);});
 await check('native AudioWorklet render recorded for sample comparison with exported mix',async()=>{
 const p=await state();const end=Math.max(...p.clips.map(c=>c.start+c.duration));
 const recording=await page.evaluate(async({p,end})=>{
   const context=new OfflineAudioContext(2,Math.round(end*48000),48000);await context.audioWorklet.addModule(new URL('transport-worklet.js',document.baseURI).href);
   const node=new AudioWorkletNode(context,'joljak-transport',{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2]});node.connect(context.destination);
   const solo=p.tracks.some(t=>t.solo);const clips=p.clips.map(c=>{const a=p.assets.find(a=>a.id===c.assetId),t=p.tracks.find(t=>t.id===c.trackId);return {...c,sampleRate:a.playbackRate,channels:a.channels,frames:a.playbackFrames,gain:t.gain,pan:t.pan,audible:!t.mute&&(!solo||t.solo)};});
   node.port.postMessage({type:'project',clips,clocks:[],masterGain:p.masterGain,end});
   for(const a of p.assets)for(let i=0;i<Math.ceil(a.duration/2);i++){const buffer=await window.joljak.chunk(a.id,i);node.port.postMessage({type:'chunk',key:a.id+':'+i,buffer},[buffer]);}
   node.port.postMessage({type:'transport',position:0,playing:true,clickEnabled:false});const rendered=await context.startRendering();let peak=0;
   const pcmBase64=[0,1].map(channel=>{const samples=rendered.getChannelData(channel);const bytes=new Uint8Array(samples.buffer,samples.byteOffset,samples.byteLength);let text='';
    for(let i=0;i<samples.length;i++)peak=Math.max(peak,Math.abs(samples[i]));
    for(let i=0;i<bytes.length;i+=16384)text+=String.fromCharCode(...bytes.subarray(i,i+16384));return btoa(text);});return {pcmBase64,peak};
 },{p,end});
 fs.writeFileSync(path.join(output,'native-playback-project.json'),JSON.stringify(p,null,2));
 for(let channel=0;channel<2;channel++)fs.writeFileSync(path.join(output,`native-playback-${channel}.f32`),Buffer.from(recording.pcmBase64[channel],'base64'));
 assert.ok(recording.peak>.001);});
 await check('corrupt import produces an error and leaves arrangement intact',async()=>{const p=await state();await queue('open',[path.join(output,'media','corrupt.wav')]);await page.getByRole('button',{name:'Import Audio',exact:true}).first().click();await page.locator('.modal').getByRole('button',{name:'Import Audio',exact:true}).click();await page.waitForFunction(()=>window.auditJobs.some(j=>j.kind==='decode'&&j.stage==='failed'),null,{timeout:60000});assert.deepEqual((await state()).clips,p.clips);});
 await check('synthetic whole-event analysis, stored raw result, apply/edit/reset/undo',async()=>{await fresh();await importAudio(['synthetic160.wav']);await select();await page.getByRole('button',{name:'Analyze Audio',exact:true}).click();await page.locator('.tap-control input').fill('160');await page.locator('.modal').getByRole('button',{name:'Analyze Audio',exact:true}).click();
 await page.waitForFunction(()=>window.auditJobs.some(j=>j.kind==='analyze'&&['complete','failed'].includes(j.stage)),null,{timeout:240000});
 const completed=await page.evaluate(()=>window.auditJobs.findLast(j=>j.kind==='analyze'&&['complete','failed'].includes(j.stage)));assert.equal(completed.stage,'complete',JSON.stringify(completed));
 await page.waitForSelector('.analysis-result');const before=await state();assert.equal(before.analyses.length,1);assert.equal(before.clocks.length,0);assert.ok(before.analyses[0].result.period_seconds,JSON.stringify(before.analyses[0].result));
 await page.getByRole('button',{name:'Audition',exact:true}).click();await pause(300);await page.locator('button[title="Stop (Num 0)"]').click();await page.getByRole('button',{name:'Apply Clock',exact:true}).click();await pause(100);
 const applied=await state();assert.equal(applied.clocks.length,1);await field('Quarter BPM',180);assert.equal((await state()).clocks[0].values.bpm,180);assert.deepEqual((await state()).clips,applied.clips);
 await page.getByRole('button',{name:'Reset to Analysis',exact:true}).click();assert.deepEqual((await state()).clocks[0].values,applied.clocks[0].original);
 await page.keyboard.press('Control+z');await page.keyboard.press('Control+z');await page.keyboard.press('Control+z');await pause(100);assert.equal((await state()).clocks.length,0);assert.equal((await state()).analyses.length,1);
 fs.writeFileSync(path.join(output,'native-analysis-project.json'),JSON.stringify(applied,null,2));});
 }
 if(process.env.JOLJAK_EXTENDED)await require('./windows-extended.cjs')({app,page,fs,path,assert,output,results,errors,pause,state,check,menu,queue,importAudio,fresh,select,field,launch,job});
 await check('no uncaught renderer exceptions',async()=>assert.deepEqual(errors,[]));
 await page.screenshot({path:path.join(output,'windows-final.png')});await app.close();
 console.log(JSON.stringify({summary:{pass:results.filter(r=>r.status==='pass').length,fail:results.filter(r=>r.status==='fail').length}}));
 process.exitCode=results.some(r=>r.status==='fail')?1:0;
})().catch(async e=>{console.error(e.stack);try{await app?.close();}catch{}process.exitCode=1;});
