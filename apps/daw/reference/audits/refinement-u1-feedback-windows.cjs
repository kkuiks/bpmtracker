// Explicit follow-up to the owner's U1 feedback; no analysis/model invocation.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {_electron}=require(process.env.BPMTRACKER_PLAYWRIGHT);
const output=process.env.BPMTRACKER_U1_AUDIT,exe=process.env.BPMTRACKER_U1_EXE;
delete process.env.ELECTRON_RUN_AS_NODE;
const results=[],errors=[];let app,page;
const report=path.join(output,'u1-feedback-results.json');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function state(){return page.evaluate(()=>{
  const element=document.querySelector('.app-shell'),key=Object.keys(element).find(k=>k.startsWith('__reactFiber$'));
  let root=element[key];while(root.return)root=root.return;root=root.stateNode.current;
  function find(f){if(!f)return null;let hook=f.memoizedState;
    while(hook&&typeof hook==='object'){if(hook.memoizedState?.format==='bpmtracker-project')return hook.memoizedState;hook=hook.next;}
    return find(f.child)||find(f.sibling);}
  return JSON.parse(JSON.stringify(find(root)));
});}
async function check(name,run){try{
  await run();results.push({name,status:'pass'});
}catch(error){results.push({name,status:'fail',error:error.stack});
  await page.screenshot({path:path.join(output,'u1-feedback-failure.png')});throw error;
}finally{fs.writeFileSync(report,JSON.stringify({results,errors},null,2));console.log(JSON.stringify(results.at(-1)));}}
async function queue(files){await app.evaluate(({dialog},files)=>{
  globalThis.u1Files=files;dialog.showOpenDialog=async()=>({canceled:false,filePaths:globalThis.u1Files});
},files);}
async function menu(name,command){await page.getByRole('button',{name,exact:true}).click();
  await page.locator('.app-dropdown').getByRole('button',{name:new RegExp('^'+command)}).click();}
async function field(label,value){const input=page.getByLabel(label,{exact:true});await input.locator('..').dblclick();
  await input.fill(String(value));await input.press('Enter');await pause(80);}
async function undo(){await page.keyboard.press('Control+z');await pause(90);}
async function select(){await page.locator('.audio-clip').first().click({position:{x:26,y:25}});await pause(60);}
async function hold(node,dy){await node.waitFor({state:'visible'});const box=await node.boundingBox();assert.ok(box);const x=box.x+box.width/2,y=box.y+box.height/2;
  await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x,y+dy,{steps:8});await pause(60);}
async function release(){await page.mouse.up();await pause(100);}
async function wheel(node){await node.hover();await page.mouse.wheel(0,-90);await pause(340);}
async function load(project,name){const file=path.join(output,name+'.bpmtracker');project.name=name;fs.writeFileSync(file,JSON.stringify(project));
  await queue([file]);await menu('File','Open Project');await page.waitForFunction(name=>document.querySelector('.title-project')?.textContent.includes(name),name);await pause(160);}
const parts=label=>page.getByLabel(label,{exact:true}).locator('..').locator('[data-value-segment]');
async function boxes(){return page.evaluate(()=>{
  const names=['Project position','Tempo','Signature numerator','Signature denominator'];
  return Object.fromEntries(names.map(name=>{const r=document.querySelector(`[aria-label="${name}"]`).getBoundingClientRect();return [name,{x:r.x,y:r.y,width:r.width,height:r.height}];}));
});}
function sameBoxes(a,b){for(const name of Object.keys(a))for(const property of ['x','y','width','height'])
  assert.ok(Math.abs(a[name][property]-b[name][property])<.1,JSON.stringify({name,property,a:a[name],b:b[name]}));}
(async()=>{try{
  app=await _electron.launch({executablePath:exe,cwd:path.dirname(exe),env:{...process.env,
    BPMTRACKER_DATA:path.join(output,'workspace-'+randomUUID()),BPMTRACKER_DEV_URL:''},timeout:90000});
  page=await app.firstWindow();page.setDefaultTimeout(12000);
  page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  page.on('dialog',dialog=>dialog.accept());await page.waitForSelector('.app-shell');
  await check('isolated native 0.6.10 app imports the retained four linked WAV fixtures',async()=>{
    assert.equal(await app.evaluate(({app})=>app.getVersion()),'0.6.10');assert.match(page.url(),/^bpmtracker:\/\/app\//);
    await queue(['Drums','Bass','Guitars','Vocals'].map(name=>path.join(output,'media',name+'.wav')));
    await menu('File','Import Audio');await page.locator('.modal').getByLabel('Placement').selectOption('stems');
    await page.locator('.modal').getByRole('button',{name:'Import Audio',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.audio-clip').length===4,null,{timeout:60000});await select();
  });
  const baseline=await state();
  await check('first footer BPM entry declares at the cursor; existing point updates; Undo preserves project base',async()=>{
    await field('Project position','5.1.1.0');await field('Tempo','137.25');let p=await state();
    assert.equal(p.bpm,120);assert.equal(p.tempos.length,1);assert.equal(p.tempos[0].quarter,16);assert.equal(p.tempos[0].bpm,137.25);
    assert.deepEqual(p.clips,baseline.clips);await field('Tempo','141');p=await state();assert.equal(p.tempos.length,1);assert.equal(p.tempos[0].bpm,141);
    await undo();assert.equal((await state()).tempos[0].bpm,137.25);await undo();assert.equal((await state()).tempos.length,0);assert.equal((await state()).bpm,120);
  });
  await check('BPM drag and Shift drag use integers; typed fractions remain exact; each drag takes one Undo',async()=>{
    await load(structuredClone(baseline),'Integer BPM');const input=page.getByLabel('Tempo',{exact:true});
    await hold(input,-24);assert.equal(Number(await input.getAttribute('aria-valuenow')),126);assert.equal((await state()).tempos.length,0);await release();
    assert.equal((await state()).tempos[0].bpm,126);await undo();assert.equal((await state()).tempos.length,0);
    await page.keyboard.down('Shift');await hold(input,-24);await release();await page.keyboard.up('Shift');
    assert.equal((await state()).tempos[0].bpm,126);await undo();await field('Tempo','400/3');assert.equal((await state()).tempos[0].bpm,400/3);
    await hold(input,-8);await release();assert.ok(Number.isInteger((await state()).tempos[0].bpm));await undo();assert.equal((await state()).tempos[0].bpm,400/3);
  });
  await check('hover wheel changes unfocused BPM by one without stealing focus or scrolling; one Undo',async()=>{
    await load(structuredClone(baseline),'Hover BPM');await select();
    const before=await page.evaluate(()=>({focus:document.activeElement.getAttribute('aria-label'),scroll:document.querySelector('.timeline-scroll').scrollTop}));
    await wheel(page.getByLabel('Tempo',{exact:true}));assert.equal((await state()).tempos[0].bpm,121);assert.equal((await state()).bpm,120);
    const after=await page.evaluate(()=>({focus:document.activeElement.getAttribute('aria-label'),scroll:document.querySelector('.timeline-scroll').scrollTop}));
    assert.deepEqual(after,before);await undo();assert.equal((await state()).tempos.length,0);
  });
  await check('linked clips move visibly before pointer release; Escape restores geometry and history; release takes one Undo',async()=>{
    await load(structuredClone(baseline),'Live position');await select();const before=await state(),box=await page.locator('.audio-clip').first().boundingBox();
    const history=await page.locator('button[title^="Undo"]').getAttribute('title');await hold(parts('Event start').first(),-8);let p=await state();
    assert.ok(p.clips.every(c=>c.start===4));assert.ok((await page.locator('.audio-clip').first().boundingBox()).x>box.x);
    assert.deepEqual(p.clips.map(c=>[c.sourceStart,c.duration]),before.clips.map(c=>[c.sourceStart,c.duration]));
    assert.equal(await page.locator('button[title^="Undo"]').getAttribute('title'),history);
    await page.keyboard.press('Escape');await release();assert.deepEqual((await state()).clips,before.clips);
    assert.equal(await page.locator('button[title^="Undo"]').getAttribute('title'),history);
    await hold(parts('Event start').first(),-8);await release();assert.ok((await state()).clips.every(c=>c.start===4));await undo();assert.deepEqual((await state()).clips,before.clips);
    await page.locator('.inspector-fold > summary').filter({hasText:/^Move Selection$/}).click();
    await hold(parts('Selection position').first(),-4);assert.ok((await state()).clips.every(c=>c.start===2));
    await page.keyboard.press('Escape');await release();assert.deepEqual((await state()).clips,before.clips);
    await page.locator('.inspector-fold > summary').filter({hasText:/^Audio Event$/}).click();
    await hold(parts('Audio position').first(),-4);assert.ok((await state()).clips.every(c=>c.start===2));
    await page.keyboard.press('Escape');await release();assert.deepEqual((await state()).clips,before.clips);
  });
  await check('end and duration scrubs preview linked trims and preserve one-Undo semantics',async()=>{
    await load(structuredClone(baseline),'Live trim');await select();await hold(parts('Event end').first(),8);
    assert.ok((await state()).clips.every(c=>c.duration===26));await release();await undo();assert.deepEqual((await state()).clips,baseline.clips);
    await hold(page.getByLabel('Length',{exact:true}),12);assert.ok((await state()).clips.every(c=>c.duration<30));
    await page.keyboard.press('Escape');await release();assert.deepEqual((await state()).clips,baseline.clips);
  });
  await check('hover wheel over position segments uses that segment and moves linked clips with one Undo',async()=>{
    await load(structuredClone(baseline),'Hover position');await select();await wheel(parts('Event start').first());
    assert.ok((await state()).clips.every(c=>c.start===2));await undo();assert.deepEqual((await state()).clips,baseline.clips);
    await wheel(parts('Event start').last());assert.ok((await state()).clips.every(c=>Math.abs(c.start-1/960)<1e-8));await undo();assert.deepEqual((await state()).clips,baseline.clips);
  });
  await check('numeric widths and each position segment stay fixed across decimals and digit boundaries',async()=>{
    await load(structuredClone(baseline),'Stable values');await field('Tempo','12');const a=await boxes();assert.equal(await page.getByLabel('Tempo',{exact:true}).inputValue(),'12.000');
    await field('Tempo','12.25');assert.equal(await page.getByLabel('Tempo',{exact:true}).inputValue(),'12.250');sameBoxes(a,await boxes());
    await load(structuredClone(baseline),'Stable positions');await field('Project position','9.4.4.0');
    const spans=async()=>parts('Project position').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return{x:r.x,width:r.width};}));
    const initial=await spans(),initialBoxes=await boxes();for(const position of ['10.1.1.119','99.4.4.0','100.1.1.119']){
      await field('Project position',position);assert.deepEqual(await spans(),initial);sameBoxes(initialBoxes,await boxes());}
  });
  await check('duplicated-track switching retains exactly one volume/pan control and edits only the focused track',async()=>{
    await load(structuredClone(baseline),'Duplicate Inspector');await select();await field('Volume','-8');
    await page.locator('.track-head').first().click();await page.locator('.track-head').first().click({button:'right'});await page.locator('.context-menu').getByRole('menuitem',{name:'Duplicate Tracks',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.track-head').length===5);await page.locator('.track-head').nth(1).click();
    await field('Volume','-3');await field('Pan','25');
    for(let i=0;i<24;i++){
      const duplicate=i%2===1;await page.locator('.track-head').nth(duplicate?1:0).click();
      assert.equal(await page.getByLabel('Track volume slider',{exact:true}).count(),1);assert.equal(await page.getByLabel('Track pan slider',{exact:true}).count(),1);
      assert.equal(await page.getByLabel('Volume',{exact:true}).inputValue(),duplicate?'-3.00':'-8.00');assert.equal(await page.getByLabel('Pan',{exact:true}).inputValue(),duplicate?'25':'0');
    }
    const p=await state();assert.ok(Math.abs(p.tracks[0].gain-10**(-8/20))<1e-10);assert.equal(p.tracks[0].pan,0);
    assert.ok(Math.abs(p.tracks[1].gain-10**(-3/20))<1e-10);assert.equal(p.tracks[1].pan,.25);
    await page.screenshot({path:path.join(output,'u1-feedback-inspector.png')});
  });
  await check('first tempo declaration during playback keeps the captured input target',async()=>{
    await load(structuredClone(baseline),'Playback target');await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.send('bpmtracker:command','play'));await pause(260);
    const before=Number(await page.getByLabel('Project position',{exact:true}).getAttribute('aria-valuenow'));
    const input=page.getByLabel('Tempo',{exact:true});await input.dblclick();const after=Number(await page.getByLabel('Project position',{exact:true}).getAttribute('aria-valuenow'));
    await input.fill('132');await pause(800);assert.equal(await input.inputValue(),'132');await input.press('Enter');await pause(80);await page.locator('.stop-button').click();
    const p=await state();assert.equal(p.bpm,120);assert.equal(p.tempos.length,1);assert.ok(p.tempos[0].quarter>=before*2-.08&&p.tempos[0].quarter<=after*2+.08);
  });
  await check('normal and small layouts retain control bounds and fit Inspector rows; no renderer errors',async()=>{
    await load(structuredClone(baseline),'Feedback review');await select();await page.screenshot({path:path.join(output,'u1-feedback-normal.png')});
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setBounds({width:1024,height:720}));await pause(150);
    const size=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scale:devicePixelRatio}));const bounds=await boxes();
    for(const [name,r] of Object.entries(bounds))assert.ok(r.x>=0&&r.x+r.width<=size.width&&r.y+r.height<=size.height,JSON.stringify({name,r,size}));
    const rows=await page.locator('.inspector-volume, .inspector-pan').evaluateAll(nodes=>nodes.map(row=>{
      const bounds=row.getBoundingClientRect();return [...row.children].every(child=>{const r=child.getBoundingClientRect();return r.x>=bounds.x-.1&&r.right<=bounds.right+.1;});}));
    assert.deepEqual(rows,[true,true]);assert.deepEqual(errors,[]);fs.writeFileSync(path.join(output,'u1-feedback-layout.json'),JSON.stringify(size));
    await page.screenshot({path:path.join(output,'u1-feedback-small.png')});
  });
}catch(error){console.error(error.stack);process.exitCode=1;}finally{
  fs.writeFileSync(report,JSON.stringify({results,errors},null,2));
  if(app){await app.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();});await app.close();}
}})();
