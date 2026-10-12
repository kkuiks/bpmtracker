// Explicit Windows UI audit. Real IPC/decoding/playback; no estimator invocation.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {_electron}=require(process.env.JOLJAK_PLAYWRIGHT);
const output=process.env.JOLJAK_U1_AUDIT,exe=process.env.JOLJAK_U1_EXE;
delete process.env.ELECTRON_RUN_AS_NODE;
const results=[],errors=[];let app,page;
const visualOnly=process.env.JOLJAK_U1_VISUAL_ONLY==='1';
const report=path.join(output,visualOnly?'u1-presentation-results.json':'u1-results.json');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function state(){return page.evaluate(()=>{
  const element=document.querySelector('.app-shell'),key=Object.keys(element).find(k=>k.startsWith('__reactFiber$'));
  let root=element[key];while(root.return)root=root.return;root=root.stateNode.current;
  function find(f){if(!f)return null;let hook=f.memoizedState;
    while(hook&&typeof hook==='object'){if(hook.memoizedState?.format==='joljak-project')return hook.memoizedState;hook=hook.next;}
    return find(f.child)||find(f.sibling);}
  return JSON.parse(JSON.stringify(find(root)));
});}
async function check(name,run){
  if(visualOnly&&!/isolated 0\.6\.9|layouts keep|no renderer/.test(name))return;
  try{await run();results.push({name,status:'pass'});}catch(error){
  results.push({name,status:'fail',error:error.stack});await page.screenshot({path:path.join(output,'u1-failure.png')});throw error;
}finally{fs.writeFileSync(report,JSON.stringify({results,errors},null,2));console.log(JSON.stringify(results.at(-1)));}}
async function queue(files){await app.evaluate(({dialog},files)=>{globalThis.u1Files=files;
  dialog.showOpenDialog=async()=>({canceled:false,filePaths:globalThis.u1Files});},files);}
async function menu(name,command){await page.getByRole('button',{name,exact:true}).click();
  await page.locator('.app-dropdown').getByRole('button',{name:new RegExp('^'+command)}).click();}
async function field(label,value){const input=page.getByLabel(label,{exact:true});await input.dblclick();
  await input.fill(String(value));await input.press('Enter');await pause(70);}
async function undo(){await page.keyboard.press('Control+z');await pause(90);}
async function select(){await page.locator('.audio-clip').first().click({position:{x:26,y:25}});await pause(60);}
async function drag(node,dx,dy,cancel=false){const box=await node.boundingBox();assert.ok(box);const x=box.x+box.width/2,y=box.y+box.height/2;
  await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+dx,y+dy,{steps:8});await pause(40);
  if(cancel)await page.keyboard.press('Escape');await page.mouse.up();await pause(100);}
async function load(project,name){const file=path.join(output,name+'.joljak');project.name=name;fs.writeFileSync(file,JSON.stringify(project));
  await queue([file]);await menu('File','Open Project');await page.waitForFunction(name=>document.querySelector('.title-project')?.textContent.includes(name),name);
  await pause(160);}
async function playNative(){await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.send('joljak:command','play'));}
async function stop(){await page.locator('.stop-button').click();await pause(80);}
async function range(){await page.locator('button[title="Range Selection (2)"]').click();
  const box=await page.locator('.audio-clip').first().boundingBox();
  await page.mouse.move(box.x+28,box.y+30);await page.mouse.down();await page.mouse.move(box.x+166,box.y+30,{steps:8});await page.mouse.up();await pause(70);}
(async()=>{try{
  app=await _electron.launch({executablePath:exe,cwd:path.dirname(exe),env:{...process.env,
    JOLJAK_DATA:path.join(output,'workspace-'+randomUUID()),JOLJAK_DEV_URL:''},timeout:90000});
  page=await app.firstWindow();page.setDefaultTimeout(12000);page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});page.on('dialog',dialog=>dialog.accept());
  await page.waitForSelector('.app-shell');
  await check('isolated 0.6.9 production app and four linked native WAV imports',async()=>{
    assert.equal(await app.evaluate(({app})=>app.getVersion()),'0.6.9');assert.match(page.url(),/^joljak:\/\/app\//);
    assert.equal(await page.evaluate(()=>window.joljak.kind),'electron');
    await queue(['Drums','Bass','Guitars','Vocals'].map(name=>path.join(output,'media',name+'.wav')));
    await menu('File','Import Audio');await page.locator('.modal').getByLabel('Placement').selectOption('stems');
    await page.locator('.modal').getByRole('button',{name:'Import Audio',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.audio-clip').length===4,null,{timeout:60000});await select();
    const project=await state();assert.equal(project.tracks.length,4);assert.equal(new Set(project.clips.map(c=>c.groupId)).size,1);
    await page.screenshot({path:path.join(output,'u1-normal.png')});
  });
  const baseline=await state();
  await check('fraction BPM retains exact value; native Undo restores whole value',async()=>{
    await field('Tempo','400/3');assert.equal((await state()).bpm,400/3);assert.equal((await state()).tempos.length,0);
    await undo();assert.equal((await state()).bpm,baseline.bpm);
  });
  await check('value paste is staged and value copy retains full precision',async()=>{
    const input=page.getByLabel('Tempo',{exact:true});
    await input.evaluate(node=>{const data=new DataTransfer();data.setData('text/plain','400/3');node.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));});
    assert.equal(await input.inputValue(),'400/3');assert.equal((await state()).bpm,baseline.bpm);await input.press('Enter');await pause(60);
    const copied=await input.evaluate(node=>{const data=new DataTransfer();node.dispatchEvent(new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:data}));return data.getData('text/plain');});
    assert.equal(copied,String(400/3));await undo();assert.equal((await state()).bpm,baseline.bpm);
  });
  await check('invalid numeric entry stays visible, unapplied and cancellable',async()=>{
    const input=page.getByLabel('Tempo',{exact:true});await input.dblclick();await input.fill('125/0');await input.press('Enter');
    assert.equal(await input.inputValue(),'125/0');assert.equal(await input.getAttribute('aria-invalid'),'true');assert.equal((await state()).bpm,baseline.bpm);
    const bounds=await page.locator('.value-error').boundingBox(),size=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
    assert.ok(bounds.x>=0&&bounds.x+bounds.width<=size.width&&bounds.y+bounds.height<=size.height);
    await page.screenshot({path:path.join(output,'u1-invalid.png')});await input.press('Escape');assert.equal(await page.locator('.value-error').count(),0);
  });
  await check('numeric scrub commits one history entry and Escape cancels',async()=>{
    const input=page.getByLabel('Tempo',{exact:true});await drag(input,0,-24);assert.ok((await state()).bpm>baseline.bpm);
    await undo();assert.equal((await state()).bpm,baseline.bpm);await drag(input,0,-30,true);assert.equal((await state()).bpm,baseline.bpm);
    await page.keyboard.down('Shift');await drag(input,0,-24);await page.keyboard.up('Shift');
    assert.ok(Math.abs((await state()).bpm-baseline.bpm-.15)<1e-8);await undo();assert.equal((await state()).bpm,baseline.bpm);
  });
  await check('focused wheel adjusts the value once without scrolling the project',async()=>{
    const input=page.getByLabel('Tempo',{exact:true});await input.click();const box=await input.boundingBox();
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.wheel(0,-90);await pause(300);
    assert.equal((await state()).bpm,baseline.bpm+.25);await undo();assert.equal((await state()).bpm,baseline.bpm);
  });
  await check('text Undo stays in the input, preserving project history',async()=>{
    const input=page.getByLabel('Tempo',{exact:true});await input.dblclick();await page.keyboard.type('130',{delay:20});
    await undo();assert.notEqual(await input.inputValue(),'130');assert.equal((await state()).bpm,baseline.bpm);await input.press('Escape');
  });
  await check('segmented bar scrub moves linked stems equally with one Undo',async()=>{
    await select();const input=page.getByLabel('Event start',{exact:true});
    await drag(input.locator('..').locator('.value-segments > span').first(),0,-8);
    const moved=await state();assert.ok(moved.clips[0].start>0);assert.ok(moved.clips.every(c=>c.start===moved.clips[0].start));
    assert.deepEqual(moved.clips.map(c=>[c.sourceStart,c.duration]),baseline.clips.map(c=>[c.sourceStart,c.duration]));
    await undo();assert.deepEqual((await state()).clips,baseline.clips);
  });
  await check('volume and pan live previews cancel without consuming history',async()=>{
    await select();let before=await state();const label=await page.locator('button[title^="Undo"]').getAttribute('title');
    await drag(page.getByLabel('Track volume slider').locator('.fader-cap'),-30,0,true);
    assert.deepEqual((await state()).tracks,before.tracks);
    await drag(page.getByLabel('Track pan slider').locator('.pan-cap'),28,0,true);
    assert.deepEqual((await state()).tracks,before.tracks);assert.equal(await page.locator('button[title^="Undo"]').getAttribute('title'),label);
  });
  await check('completed pan gesture takes exactly one Undo',async()=>{
    const before=await state();await drag(page.getByLabel('Track pan slider').locator('.pan-cap'),22,0);
    assert.notDeepEqual((await state()).tracks,before.tracks);await undo();assert.deepEqual((await state()).tracks,before.tracks);
  });
  await check('range Escape restores preceding range bounds',async()=>{
    await range();const start=await page.getByLabel('Range start').getAttribute('aria-valuenow'),end=await page.getByLabel('Range end').getAttribute('aria-valuenow');
    const box=await page.locator('.audio-clip').first().boundingBox();await page.mouse.move(box.x+185,box.y+30);await page.mouse.down();
    await page.mouse.move(box.x+255,box.y+30,{steps:4});await page.keyboard.press('Escape');await page.mouse.up();
    assert.equal(await page.getByLabel('Range start').getAttribute('aria-valuenow'),start);assert.equal(await page.getByLabel('Range end').getAttribute('aria-valuenow'),end);
  });
  await check('pointer cancellation preserves the preceding range',async()=>{
    const start=await page.getByLabel('Range start').getAttribute('aria-valuenow'),end=await page.getByLabel('Range end').getAttribute('aria-valuenow');
    const box=await page.locator('.audio-clip').first().boundingBox();await page.mouse.move(box.x+190,box.y+25);await page.mouse.down();
    await page.mouse.move(box.x+260,box.y+25,{steps:4});await page.getByLabel('Project timeline',{exact:true}).dispatchEvent('pointercancel');await page.mouse.up();
    assert.equal(await page.getByLabel('Range start').getAttribute('aria-valuenow'),start);assert.equal(await page.getByLabel('Range end').getAttribute('aria-valuenow'),end);
  });
  await check('Object toolbar and keyboard clear the same active range',async()=>{
    await page.locator('button[title="Object Selection (1)"]').click();assert.equal(await page.getByLabel('Range start').count(),0);
    await range();await page.keyboard.press('1');assert.equal(await page.getByLabel('Range start').count(),0);
    assert.equal(await page.locator('button[title="Object Selection (1)"]').getAttribute('aria-pressed'),'true');
  });
  await check('playing tempo edit retains its starting cursor declaration',async()=>{
    const project=structuredClone(baseline);project.tempos=[{id:randomUUID(),quarter:0,bpm:120,origin:'manual'}];await load(project,'Cursor-target check');
    await playNative();await pause(260);
    const before=Number(await page.getByLabel('Project position',{exact:true}).getAttribute('aria-valuenow'));
    const input=page.getByLabel('Tempo',{exact:true});await input.dblclick();
    const after=Number(await page.getByLabel('Project position',{exact:true}).getAttribute('aria-valuenow'));
    await input.fill('132');await pause(900);assert.equal(await input.inputValue(),'132');await input.press('Enter');await pause(80);await stop();
    const point=(await state()).tempos.find(p=>p.quarter>0);assert.ok(point,JSON.stringify((await state()).tempos));
    assert.ok(point.quarter>=before*2-.08&&point.quarter<=after*2+.08,JSON.stringify({point,before,after}));
  });
  await check('signature edit survives playback across a different denominator',async()=>{
    const project=structuredClone(baseline);project.signatures=[{id:randomUUID(),bar:1,numerator:4,denominator:4,origin:'manual'},
      {id:randomUUID(),bar:2,numerator:7,denominator:8,origin:'manual'}];await load(project,'Signature-target check');
    const input=page.getByLabel('Signature numerator');await input.dblclick();await input.fill('3');await playNative();await pause(2500);
    assert.equal(await input.inputValue(),'3');assert.equal(await page.getByLabel('Signature denominator').inputValue(),'4');
    await input.press('Enter');await pause(80);await stop();
    const point=(await state()).signatures.find(p=>p.bar===1);assert.equal(point.numerator,3);assert.equal(point.denominator,4);
  });
  await check('normal and 1024x720 layouts keep essential controls inside the window',async()=>{
    await load(structuredClone(baseline),'U1 review');await select();await page.screenshot({path:path.join(output,'u1-final.png')});
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setBounds({width:1024,height:720}));await pause(150);
    const size=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scale:devicePixelRatio}));
    for(const label of ['Project position','Tempo','Signature numerator','Signature denominator']){
      const bounds=await page.getByLabel(label,{exact:true}).boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=size.width,JSON.stringify({label,bounds,size}));
    }
    const stopButton=await page.locator('.stop-button').boundingBox();assert.ok(stopButton.y+stopButton.height<=size.height);
    fs.writeFileSync(path.join(output,'u1-layout.json'),JSON.stringify(size));await page.screenshot({path:path.join(output,'u1-small.png')});
  });
  await check('no renderer errors',async()=>assert.deepEqual(errors,[]));
}catch(error){console.error(error.stack);process.exitCode=1;}finally{
  fs.writeFileSync(report,JSON.stringify({results,errors},null,2));
  if(app){await app.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();});await app.close();}
}})();
