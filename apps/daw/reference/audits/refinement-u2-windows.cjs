// Owner-authorized native UX review of the approved U2 workspace and shared menus.
// Retained four-WAV fixtures; isolated profiles; no analysis or export job is run.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {_electron}=require(process.env.JOLJAK_PLAYWRIGHT);
const output=process.env.JOLJAK_U2_AUDIT,exe=process.env.JOLJAK_U2_EXE;
const contextOnly=process.env.JOLJAK_U2_CONTEXT_ONLY==='1';
const keyboardOnly=process.env.JOLJAK_U2_KEYBOARD_ONLY==='1';
const mapOnly=process.env.JOLJAK_U2_MAP_ONLY==='1';
delete process.env.ELECTRON_RUN_AS_NODE;
const results=[],errors=[];let app,page;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const report=path.join(output,mapOnly?'u2-map-results.json':keyboardOnly?'u2-keyboard-results.json':contextOnly?'u2-context-results.json':'u2-results.json');
async function state(){return page.evaluate(()=>{
  const element=document.querySelector('.app-shell'),key=Object.keys(element).find(k=>k.startsWith('__reactFiber$'));
  let root=element[key];while(root.return)root=root.return;root=root.stateNode.current;
  function find(f){if(!f)return null;let hook=f.memoizedState;
    while(hook&&typeof hook==='object'){if(hook.memoizedState?.format==='joljak-project')return hook.memoizedState;hook=hook.next;}
    return find(f.child)||find(f.sibling);}
  return JSON.parse(JSON.stringify(find(root)));
});}
async function check(name,run){if(!name.startsWith('native')&&(mapOnly?!name.startsWith('map menus'):keyboardOnly?!name.startsWith('right-click'):contextOnly!==name.startsWith('context:')))return;
try{const evidence=await run();results.push({name,status:'pass',evidence});}
catch(error){results.push({name,status:'fail',error:error.stack});await screenshot('u2-failure');throw error;}
finally{fs.writeFileSync(report,JSON.stringify({results,errors},null,2));console.log(JSON.stringify(results.at(-1)));}}
async function screenshot(name){await page.screenshot({path:path.join(output,name+'.png')});}
async function queue(files){await app.evaluate(({dialog},files)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:files});},files);}
const menuName=label=>new RegExp('^'+label.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(?:\\s|$)');
async function command(menu,label){await page.getByRole('button',{name:menu,exact:true}).click();
  await page.locator('.owned-menu').first().getByRole('menuitem',{name:menuName(label)}).click();await pause(90);}
async function item(label){await page.locator('.owned-menu').getByRole('menuitem',{name:menuName(label)}).click();await pause(90);}
async function field(label,value){const input=page.getByLabel(label,{exact:true});await input.locator('..').dblclick();
  await input.fill(String(value));await input.press('Enter');await pause(90);}
async function load(project,name){const file=path.join(output,name+'.joljak');project.name=name;fs.writeFileSync(file,JSON.stringify(project));
  await queue([file]);await command('File','Open Project…');await page.waitForFunction(name=>document.querySelector('.title-project')?.textContent.includes(name),name);await pause(140);}
async function select(index=0){await page.locator('.audio-clip').nth(index).click({position:{x:30,y:30}});await pause(70);}
async function undo(){await page.keyboard.press('Control+z');await pause(90);}
async function rightClip(index=0){await page.locator('.audio-clip').nth(index).click({button:'right',position:{x:80,y:28}});await pause(60);}
async function position(){return Number(await page.getByLabel('Project position',{exact:true}).getAttribute('aria-valuenow'));}
async function geometry(){return page.evaluate(()=>{
  const selectors=['.title-bar','.menu-bar','.edit-toolbar','.info-line','.inspector-pane','.track-pane','.timeline-ruler','.tempo-track-lane','.signature-track-lane','.track-head','.audio-clip','.timeline-controls','.transport-bar'];
  return {width:innerWidth,height:innerHeight,ratio:devicePixelRatio,rects:Object.fromEntries(selectors.map(selector=>{
    const node=document.querySelector(selector);if(!node)return[selector,null];const r=node.getBoundingClientRect();
    return [selector,{x:r.x,y:r.y,width:r.width,height:r.height}];}))};
});}
async function visibleControls(){const names=['Project position','Tempo','Signature numerator','Signature denominator','Click boost','Output level'];
  return page.evaluate(names=>Object.fromEntries(names.map(name=>{const node=document.querySelector(`[aria-label="${name}"]`),r=node.getBoundingClientRect();
    return [name,{x:r.x,y:r.y,width:r.width,height:r.height,visible:r.x>=0&&r.right<=innerWidth&&r.y>=0&&r.bottom<=innerHeight}];})),names);}
(async()=>{try{
  app=await _electron.launch({executablePath:exe,cwd:path.dirname(exe),env:{...process.env,
    JOLJAK_DATA:path.join(output,'workspace-'+randomUUID()),JOLJAK_DEV_URL:''},timeout:90000});
  page=await app.firstWindow();page.setDefaultTimeout(12000);
  page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  page.on('dialog',dialog=>dialog.accept());await page.waitForSelector('.app-shell');
  await check('native 0.6.12 imports the retained linked stems in an isolated profile',async()=>{
    assert.equal(await app.evaluate(({app})=>app.getVersion()),'0.6.12');assert.match(page.url(),/^joljak:\/\/app\//);
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setBounds({width:1440,height:940}));await pause(160);await screenshot('u2-empty');
    await queue(['Drums','Bass','Guitars','Vocals'].map(name=>path.join(process.env.JOLJAK_U2_MEDIA,name+'.wav')));
    await command('File','Import Audio…');await page.locator('.modal').getByLabel('Placement').selectOption('stems');
    await page.locator('.modal').getByRole('button',{name:'Import Audio',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.audio-clip').length===4,null,{timeout:60000});await select();
    await page.getByRole('button',{name:'Fit project',exact:true}).click();await pause(150);await screenshot('u2-wide');
    return await geometry();
  });
  const baseline=await state();
  await check('wide and compact workspaces fit the approved main controls',async()=>{
    const wide=await geometry();for(const r of Object.values(await visibleControls()))assert.ok(r.visible,JSON.stringify(r));
    assert.equal(wide.rects['.info-line'].height,48);assert.equal(wide.rects['.audio-clip'].height,74);assert.equal(wide.rects['.transport-bar'].height,52);
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setBounds({width:1024,height:720}));await pause(160);
    const compact=await geometry();for(const [name,r]of Object.entries(await visibleControls()))assert.ok(r.visible,JSON.stringify({name,r,compact}));
    assert.equal(compact.rects['.inspector-pane'].width,200);assert.equal(compact.rects['.track-pane'].width,188);
    assert.equal((await page.getByRole('button',{name:'Analyze Audio',exact:true}).boundingBox()).width,86);
    await screenshot('u2-compact');await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setBounds({width:1440,height:940}));await pause(160);
    return {wide,compact};
  });
  await check('right-click keeps the linked selection, lead, cursor and project; keyboard dismissal restores focus',async()=>{
    await select(0);const before=await state(),lead=await page.locator('.info-name strong').textContent(),track=await page.locator('.inspector-track h3').textContent(),cursor=await position();
    await rightClip(2);assert.equal(await page.locator('.info-name strong').textContent(),lead);
    assert.equal(await page.locator('.audio-clip.selected').count(),4);assert.equal(await position(),cursor);assert.deepEqual(await state(),before);
    assert.equal(await page.locator('.inspector-track h3').textContent(),track);
    await screenshot('u2-event-menu');await page.keyboard.press('ArrowDown');assert.equal(await page.evaluate(()=>document.activeElement.textContent.trim()),'CutCtrl X');
    await page.keyboard.press('End');assert.match(await page.evaluate(()=>document.activeElement.textContent),/Delete Events/);
    await page.keyboard.press('Home');await page.keyboard.press('Escape');assert.equal(await page.locator('.owned-menu').count(),0);
    assert.equal(await page.evaluate(()=>document.activeElement.classList.contains('audio-clip')),true);
    await page.keyboard.press('Shift+F10');assert.equal(await page.locator('.owned-menu').count(),1);await page.keyboard.press('Escape');
    await rightClip(0);await page.keyboard.press('Tab');assert.equal(await page.locator('.owned-menu').count(),0);
    assert.equal(await page.evaluate(()=>document.activeElement.tagName==='BODY'),false);
    await rightClip(0);await page.keyboard.press('Delete');assert.equal((await state()).clips.length,0);await undo();assert.deepEqual((await state()).clips,before.clips);
    await page.getByRole('button',{name:'File',exact:true}).focus();await page.keyboard.press('ArrowRight');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Edit');
    await page.keyboard.press('ArrowDown');assert.match(await page.evaluate(()=>document.activeElement.textContent),/Undo/);await page.keyboard.press('Escape');
    const input=page.getByLabel('Tempo',{exact:true});await input.locator('..').dblclick();await input.fill('141');await input.selectText();
    await app.evaluate(({Menu})=>{globalThis.u2Popup=Menu.prototype.popup;Menu.prototype.popup=function(){globalThis.u2TextRoles=this.items.map(item=>item.role);};});
    try{await input.click({button:'right'});await pause(90);const roles=await app.evaluate(()=>globalThis.u2TextRoles);assert.deepEqual(roles.filter(Boolean),['undo','redo','cut','copy','paste','selectall']);}
    finally{await app.evaluate(({Menu})=>{Menu.prototype.popup=globalThis.u2Popup;});}
    await input.press('Escape');assert.deepEqual(await state(),before);
  });
  await check('menu duplicate and keyboard Undo preserve linked geometry and the lead event',async()=>{
    await rightClip(2);await item('Duplicate');let p=await state();assert.equal(p.clips.length,8);
    const copied=p.clips.filter(c=>!baseline.clips.some(original=>original.id===c.id));assert.ok(copied.every(c=>c.start===30));
    assert.equal(await page.locator('.info-name strong').textContent(),'Drums');
    assert.deepEqual(p.tempos,baseline.tempos);assert.deepEqual(p.signatures,baseline.signatures);
    await undo();assert.deepEqual((await state()).clips,baseline.clips);
  });
  await check('menu edge placement and disabled multi-track submenu do not change the project',async()=>{
    await load(structuredClone(baseline),'Menu edges');await page.locator('.track-head').first().click();
    await page.locator('.track-head').nth(2).click({modifiers:['Shift']});const before=await state();
    await page.locator('.track-head').nth(1).click({button:'right'});const timebase=page.locator('.owned-menu').getByRole('menuitem',{name:'Time Base',exact:true});
    assert.equal(await timebase.getAttribute('aria-disabled'),'true');await timebase.hover();await timebase.click({force:true});assert.equal(await page.locator('.owned-menu.submenu').count(),0);
    await screenshot('u2-track-menu');await page.keyboard.press('Escape');assert.deepEqual(await state(),before);
    await select();await page.getByRole('button',{name:'Fit project',exact:true}).click();const screen=await geometry(),clipBox=await page.locator('.audio-clip').last().boundingBox();
    await page.locator('.audio-clip').last().click({button:'right',position:{x:clipBox.width-12,y:clipBox.height-8}});await pause(90);
    const box=await page.locator('.owned-menu').first().boundingBox();assert.ok(box&&box.x>=8&&box.y>=8&&box.x+box.width<=screen.width-7&&box.y+box.height<=screen.height-7,JSON.stringify(box));
    await page.locator('.owned-menu').first().getByRole('menuitem',{name:'Order',exact:true}).hover();await pause(90);const child=await page.locator('.owned-menu.submenu').boundingBox();
    assert.ok(child&&child.x>=8&&child.x+child.width<=screen.width-7,JSON.stringify(child));
    await page.keyboard.press('Escape');
  });
  await check('numeric menu binds BPM to its opening cursor during playback and stages Paste Value',async()=>{
    await load(structuredClone(baseline),'Captured tempo');await field('Project position','5.1.1.0');
    await page.locator('.play-button').click();await page.waitForFunction(()=>document.querySelector('.play-button').getAttribute('aria-pressed')==='true');await pause(180);
    const before=await position();await page.getByLabel('Tempo',{exact:true}).click({button:'right'});const after=await position();
    await pause(650);const execution=await position();await item('Edit Value…');const input=page.getByLabel('Tempo',{exact:true});await input.fill('137');await input.press('Enter');await pause(90);await page.locator('.stop-button').click();
    let p=await state();assert.equal(p.bpm,120);assert.equal(p.tempos.length,1);assert.equal(p.tempos[0].bpm,137);
    const seconds=p.tempos[0].quarter/2;assert.ok(seconds>=before-.1&&seconds<=after+.1,JSON.stringify({before,after,execution,seconds}));assert.ok(execution-seconds>.4);
    await load(structuredClone(baseline),'Exact value');await field('Tempo','400/3');
    await page.getByLabel('Tempo',{exact:true}).click({button:'right'});await item('Copy Exact Value');
    assert.equal(await app.evaluate(({clipboard})=>clipboard.readText()),String(400/3));
    await app.evaluate(({clipboard})=>clipboard.writeText('145.25'));await page.getByLabel('Tempo',{exact:true}).click({button:'right'});await item('Paste Value');
    assert.equal(await page.getByLabel('Tempo',{exact:true}).inputValue(),'145.25');assert.equal((await state()).tempos[0].bpm,400/3);
    await page.getByLabel('Tempo',{exact:true}).press('Escape');assert.equal((await state()).tempos[0].bpm,400/3);
    return {before,after,execution,seconds};
  });
  await check('map menus edit and delete the first declaration with one Undo',async()=>{
    await load(structuredClone(baseline),'Map actions');await field('Tempo','132');const p=await state();assert.equal(p.tempos.length,1);
    await page.locator('.tempo-point').click({button:'right'});await item('Edit Properties');assert.equal(await page.getByLabel('Tempo position',{exact:true}).count(),1);
    await page.keyboard.press('Escape');await page.locator('.tempo-point').click({button:'right'});await item('Delete Tempo Point');assert.equal((await state()).tempos.length,0);assert.equal((await state()).bpm,120);
    await undo();assert.deepEqual((await state()).tempos,p.tempos);await page.locator('.tempo-point').click();await screenshot('u2-tempo');
    await page.locator('.signature-track-lane').click({button:'right',position:{x:200,y:12}});await item('Add Signature at Bar Start…');
    const numerator=page.locator('.info-line').getByLabel('Signature numerator',{exact:true});await numerator.locator('..').dblclick();await numerator.fill('3');await numerator.press('Enter');
    assert.equal((await state()).signature.numerator,4);assert.equal((await state()).signatures[0].numerator,3);
    assert.equal((await numerator.boundingBox()).height,24);assert.equal((await page.locator('.info-line').getByLabel('Signature denominator',{exact:true}).boundingBox()).height,24);
    assert.equal((await page.locator('.transport-bar').getByLabel('Signature numerator',{exact:true}).boundingBox()).height,30);await screenshot('u2-signature');
  });
  await check('maps and Inspector toggles preserve viewport and data; Restore Layout restores widths',async()=>{
    await load(structuredClone(baseline),'Layout restore');await select();await field('Project position','4.1.1.0');
    const before=await state(),viewport=await page.locator('.timeline-scroll').evaluate(n=>({left:n.scrollLeft,scale:parseFloat(document.querySelector('.audio-clip').style.width)/30}));
    await page.getByRole('button',{name:'Show/Hide Tempo and Signature',exact:true}).click();assert.equal(await page.locator('.tempo-track-lane').count(),0);
    await page.getByRole('button',{name:'Show/Hide Inspector',exact:true}).click();
    await page.getByRole('button',{name:'Show/Hide Inspector',exact:true}).click();await page.getByRole('button',{name:'Show/Hide Tempo and Signature',exact:true}).click();
    assert.deepEqual(await state(),before);assert.equal(await page.locator('.timeline-scroll').evaluate(n=>n.scrollLeft),viewport.left);
    const handle=page.getByRole('separator',{name:'Inspector width',exact:true});await handle.focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('ArrowRight');
    assert.equal((await geometry()).rects['.inspector-pane'].width,240);await command('View','Restore Layout');assert.equal((await geometry()).rects['.inspector-pane'].width,220);
    assert.equal((await geometry()).rects['.track-pane'].width,216);assert.deepEqual(await state(),before);
    await page.locator('.timeline-scroll').evaluate(n=>{n.scrollLeft=700;});await pause(80);await page.locator('.timeline-scroll').evaluate(n=>{n.scrollLeft=0;});await pause(200);
    assert.equal(await page.locator('.timeline-scroll').evaluate(n=>n.scrollLeft),0);
    const stems=await page.evaluate(()=>{const ruler=document.querySelector('.ruler-playhead'),line=document.querySelector('.playhead');return {body:line.getBoundingClientRect().width,top:parseFloat(getComputedStyle(ruler,'::after').width)};});
    assert.equal(stems.body,stems.top);return {viewport,stems};
  });
  await check('duplicated-track Inspector has one volume and pan control; contextual analysis opens then cancels',async()=>{
    await load(structuredClone(baseline),'Inspector review');await page.locator('.track-head').first().click();await field('Volume','-8');
    await page.locator('.track-head').first().click({button:'right'});await item('Duplicate Tracks');assert.equal((await state()).tracks.length,5);
    await page.locator('.track-head').nth(1).click();await field('Volume','-3');await field('Pan','25');
    for(let i=0;i<8;i++){await page.locator('.track-head').nth(i%2).click();assert.equal(await page.getByLabel('Track volume slider',{exact:true}).count(),1);assert.equal(await page.getByLabel('Track pan slider',{exact:true}).count(),1);}
    let p=await state();assert.ok(Math.abs(p.tracks[0].gain-10**(-8/20))<1e-10);assert.equal(p.tracks[0].pan,0);assert.equal(p.tracks[1].pan,.25);
    await field('Output level','-6');assert.ok(Math.abs((await state()).masterGain-10**(-6/20))<1e-10);
    await load(structuredClone(baseline),'Analysis integration');await select(2);await rightClip(2);await item('Analyze Audio…');
    assert.equal(await page.locator('.modal').getByRole('heading',{name:'Find the musical clock',exact:true}).count(),1);await screenshot('u2-analysis-entry');
    await page.locator('.modal').getByRole('button',{name:'Cancel',exact:true}).click();assert.equal(await page.locator('.modal').count(),0);
    assert.deepEqual((await state()).clocks,baseline.clocks);assert.deepEqual(errors,[]);await screenshot('u2-final');
  });
  await check('context: range copy and paste preserve boundary silence, empty rows and the shared map',async()=>{
    const fixture=structuredClone(baseline);fixture.clips=fixture.clips.filter((c,i)=>i===0||i===2).map(c=>({...c,start:4,duration:6,groupId:null}));
    fixture.tempos=[{id:randomUUID(),quarter:100,bpm:135,origin:'manual'}];fixture.signatures=[{id:randomUUID(),bar:30,numerator:3,denominator:4,origin:'manual'}];
    await load(fixture,'Range gaps');await page.locator('.track-head').first().click();await page.getByLabel('Snap grid',{exact:true}).selectOption('second');
    await page.getByRole('button',{name:'Range Selection (2)',exact:true}).click();
    const clip=await page.locator('.audio-clip').first().boundingBox(),lane=await page.locator('.track-lane').first().boundingBox(),scale=clip.width/6;
    await page.mouse.move(lane.x+2*scale,lane.y+44);await page.mouse.down();await page.mouse.move(lane.x+12*scale,lane.y+2*88+44,{steps:10});await page.mouse.up();await pause(90);
    assert.equal(Number(await page.getByLabel('Range start',{exact:true}).getAttribute('aria-valuenow')),2);assert.equal(Number(await page.getByLabel('Range end',{exact:true}).getAttribute('aria-valuenow')),12);
    const before=await state(),cursor=await position();await page.locator('.range-overlay').click({button:'right',position:{x:80,y:44}});assert.equal(await position(),cursor);await item('Copy Range');assert.deepEqual(await state(),before);
    await field('Project position','9.1.1.0');await command('Edit','Paste');let p=await state();const pasted=p.clips.filter(c=>!before.clips.some(original=>original.id===c.id));
    assert.deepEqual(pasted.map(c=>[c.start,c.duration,c.trackId]),[[18,6,p.tracks[0].id],[18,6,p.tracks[2].id]]);
    assert.equal(Number(await page.getByLabel('Range start',{exact:true}).getAttribute('aria-valuenow')),16);assert.equal(Number(await page.getByLabel('Range end',{exact:true}).getAttribute('aria-valuenow')),26);
    assert.deepEqual(p.tempos,before.tempos);assert.deepEqual(p.signatures,before.signatures);await screenshot('u2-range');await undo();assert.deepEqual((await state()).clips,before.clips);
    return {start:16,end:26,audioStart:18,emptyRow:p.tracks[1].name};
  });
  await check('context: blank lane and ruler actions retain their opening point and destination during playback',async()=>{
    await page.getByRole('button',{name:'Object Selection (1)',exact:true}).click();await page.locator('.track-head').first().click();await field('Project position','1.1.1.0');
    const before=await state(),box=await page.locator('.audio-clip').first().boundingBox(),lane=await page.locator('.track-lane').nth(2).boundingBox(),scale=box.width/6;
    await page.locator('.play-button').click();await pause(200);await page.mouse.click(lane.x+12*scale,lane.y+44,{button:'right'});await pause(650);await item('Paste Here');await page.locator('.stop-button').click();let p=await state();
    const pasted=p.clips.filter(c=>!before.clips.some(original=>original.id===c.id));assert.equal(p.tracks.length,5);assert.deepEqual(pasted.map(c=>[c.start,c.duration,c.trackId]),[[14,6,p.tracks[2].id],[14,6,p.tracks[4].id]]);
    assert.deepEqual(p.tempos,before.tempos);assert.deepEqual(p.signatures,before.signatures);await undo();assert.deepEqual((await state()).clips,before.clips);
    await queue(['Drums','Bass'].map(name=>path.join(process.env.JOLJAK_U2_MEDIA,name+'.wav')));
    const emptyLane=await page.locator('.track-lane').nth(1).boundingBox();await page.locator('.play-button').click();await pause(150);await page.mouse.click(emptyLane.x+17*scale,emptyLane.y+44,{button:'right'});
    await pause(650);await item('Import Audio Here…');assert.equal(Number(await page.getByLabel('Import position',{exact:true}).getAttribute('aria-valuenow')),17);
    await page.locator('.modal').getByRole('button',{name:'Cancel',exact:true}).click();await page.locator('.stop-button').click();assert.deepEqual(await state(),before);
    const ruler=await page.locator('.timeline-ruler').boundingBox();await page.mouse.click(ruler.x+11*scale,ruler.y+14,{button:'right'});const cursor=await position();await item('Set Left Locator');
    assert.equal(Number(await page.getByLabel('Left locator',{exact:true}).getAttribute('aria-valuenow')),11);assert.equal(await position(),cursor);assert.deepEqual(await state(),before);
    return {pointer:12,pastedAudioStart:14,destinationTrack:before.tracks[2].name,importPoint:17,leftLocator:11};
  });
  await check('context: mixed audio/map right-click keeps its scope and Delete is atomic',async()=>{
    const fixture=structuredClone(baseline);fixture.tempos=[{id:randomUUID(),quarter:8,bpm:132,origin:'manual'}];await load(fixture,'Mixed selection');await select();
    await page.locator('.tempo-point').click({modifiers:['Shift']});const before=await state();await page.locator('.tempo-point').click({button:'right'});
    const copy=page.locator('.owned-menu').getByRole('menuitem',{name:menuName('Copy')});assert.equal(await copy.getAttribute('aria-disabled'),'true');await copy.click({force:true});assert.deepEqual(await state(),before);await screenshot('u2-mixed-menu');await page.keyboard.press('Escape');
    await page.locator('.map-list-row.selected').click({button:'right'});assert.equal(await page.locator('.owned-menu').getByRole('menuitem',{name:menuName('Copy')}).getAttribute('aria-disabled'),'true');await item('Delete Selection');
    let p=await state();assert.equal(p.clips.length,0);assert.equal(p.tempos.length,0);assert.equal(p.bpm,120);await undo();p=await state();assert.deepEqual(p.clips,before.clips);assert.deepEqual(p.tempos,before.tempos);
  });
  await check('context: Time Base menu preserves placement, then tempo moves only Musical anchors',async()=>{
    const fixture=structuredClone(baseline);fixture.clips=fixture.clips.map(c=>({...c,start:4}));await load(fixture,'Time base');await page.locator('.track-head').first().click();
    await page.locator('.track-head').first().click({button:'right'});await page.locator('.owned-menu').first().getByRole('menuitem',{name:'Time Base',exact:true}).hover();
    await page.locator('.owned-menu.submenu').getByRole('menuitemcheckbox',{name:'Musical',exact:true}).click();let p=await state();
    assert.equal(p.tracks[0].timeBase,'musical');assert.deepEqual(p.clips.map(c=>[c.start,c.sourceStart,c.duration]),fixture.clips.map(c=>[c.start,c.sourceStart,c.duration]));
    await field('Tempo','90');p=await state();assert.ok(Math.abs(p.clips[0].start-16/3)<1e-8);assert.ok(p.clips.slice(1).every(c=>c.start===4&&c.duration===30));
    await undo();assert.equal((await state()).clips[0].start,4);assert.deepEqual(errors,[]);await screenshot('u2-time-base');
  });
}catch(error){console.error(error.stack);process.exitCode=1;}finally{
  fs.writeFileSync(report,JSON.stringify({results,errors},null,2));
  if(app){await app.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();});await app.close();}
}})();
