// Focused native viewport/cursor audit requested during the owner's U1 review.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {_electron}=require(process.env.JOLJAK_PLAYWRIGHT);
const output=process.env.JOLJAK_UI_AUDIT,exe=process.env.JOLJAK_UI_EXE,probe=process.env.JOLJAK_UI_PROBE==='1';
delete process.env.ELECTRON_RUN_AS_NODE;
const cursorOnly=process.env.JOLJAK_UI_CURSOR_ONLY==='1';
const playbackOnly=process.env.JOLJAK_UI_PLAYBACK_ONLY==='1';
const report=path.join(output,probe?(cursorOnly?'viewport-cursor-probe.json':'viewport-probe.json'):playbackOnly?'viewport-playback-results.json':'viewport-results.json');
const results=[],errors=[];let app,page;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function observe(name,run){if(playbackOnly&&!name.startsWith('playing cursor'))return;if(cursorOnly&&!/cursor drag|cursor stems|renderer errors/.test(name))return;try{
  const evidence=await run();results.push({name,status:'pass',evidence});
}catch(error){results.push({name,status:'fail',error:error.stack});
  await page.screenshot({path:path.join(output,'viewport-failure.png')});throw error;
}finally{fs.writeFileSync(report,JSON.stringify({probe,results,errors},null,2));console.log(JSON.stringify(results.at(-1)));}}
async function pose(){return page.evaluate(()=>{
  const n=document.querySelector('.timeline-scroll'),r=n.getBoundingClientRect();
  return {left:n.scrollLeft,top:n.scrollTop,width:n.clientWidth,scrollWidth:n.scrollWidth,
    rulerFirst:document.querySelector('.ruler-tick span')?.textContent,x:r.x,y:r.y,height:r.height,
    focus:document.activeElement.getAttribute('aria-label')};
});}
async function scroll(left){await page.locator('.timeline-scroll').evaluate((n,left)=>n.scrollLeft=left,left);await pause(170);}
async function origin(){const points=[];for(let i=0;i<8;i++){await pause(60);points.push((await pose()).left);}
  if(!probe)assert.ok(points.every(x=>Math.abs(x)<.1),JSON.stringify(points));return points;}
async function field(label,value){const input=page.getByLabel(label,{exact:true});await input.locator('..').dblclick();
  await input.fill(String(value));await input.press('Enter');await pause(100);}
(async()=>{try{
  app=await _electron.launch({executablePath:exe,cwd:path.dirname(exe),env:{...process.env,
    JOLJAK_DATA:path.join(output,'workspace-'+randomUUID()),JOLJAK_DEV_URL:''},timeout:90000});
  page=await app.firstWindow();page.setDefaultTimeout(12000);
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('dialog',d=>d.accept());
  await page.waitForSelector('.app-shell');
  if(!probe)assert.equal(await app.evaluate(({app})=>app.getVersion()),'0.6.11');
  await app.evaluate(({dialog},file)=>dialog.showOpenDialog=async()=>({canceled:false,filePaths:[file]}),process.env.JOLJAK_UI_PROJECT);
  await page.getByRole('button',{name:'File',exact:true}).click();await page.locator('.app-dropdown').getByRole('button',{name:/^Open Project/}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.audio-clip').length===4);await pause(200);
  await observe('native horizontal scroll repeatedly settles at the exact origin',async()=>{
    const samples=[];for(const previous of [90,900,6,1500]){await scroll(previous);await scroll(0);samples.push(await origin());}return samples;
  });
  await observe('Shift-wheel pans to the origin without a delayed rebound',async()=>{
    const samples=[];const p=await pose();await page.mouse.move(p.x+p.width/2,p.y+200);
    for(let i=0;i<4;i++){await scroll(800);await page.keyboard.down('Shift');await page.mouse.wheel(0,-2000);await page.keyboard.up('Shift');await pause(150);samples.push(await origin());}return samples;
  });
  await observe('native scrollbar thumb reaches the origin without moving back',async()=>{
    const samples=[];for(let i=0;i<4;i++){
      await scroll(300);const p=await pose();
      const thumb=Math.max(20,p.width*p.width/p.scrollWidth),x=p.x+p.left*p.width/p.scrollWidth+thumb/2,y=p.y+p.height-5;
      await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(p.x-20,y,{steps:8});await page.mouse.up();await pause(180);samples.push(await origin());
    }return samples;
  });
  await observe('cursor drag and return-to-start keep the viewport at its origin',async()=>{
    const positions=[];
    for(const snap of ['off','beat'])for(const side of [1,11])for(let i=0;i<4;i++){
      await scroll(0);await field('Project position','5.1.1.0');const p=await pose();
      await page.getByLabel('Snap grid',{exact:true}).selectOption(snap);
      const head=await page.locator('.ruler-playhead').boundingBox();await page.mouse.move(head.x+side,head.y+3);await page.mouse.down();
      await page.mouse.move(p.x-12,head.y+5,{steps:12});await page.mouse.up();await pause(100);
      const cursor=Number(await page.getByLabel('Project position',{exact:true}).getAttribute('aria-valuenow'));
      positions.push({snap,side,cursor,left:(await pose()).left});if(!probe){assert.equal(cursor,0);assert.equal((await pose()).left,0);}
    }
    await field('Project position','5.1.1.0');await page.locator('button[title^="Go to project start"]').click();return {positions,rewind:await origin()};
  });
  await observe('playing cursor drag stays at zero while held and retains the left viewport',async()=>{
    await scroll(0);await field('Project position','5.1.1.0');
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.send('joljak:command','play'));
    await page.waitForFunction(()=>document.querySelector('.play-button')?.getAttribute('aria-pressed')==='true');await pause(250);
    const playing=await page.locator('.play-button').getAttribute('aria-pressed');assert.equal(playing,'true');
    const head=await page.locator('.ruler-playhead').boundingBox(),p=await pose();await page.mouse.move(head.x+1,head.y+3);await page.mouse.down();
    await page.mouse.move(p.x-18,head.y+5,{steps:12});await pause(120);
    const held=await page.locator('.ruler-playhead').evaluate(n=>n.style.left),left=(await pose()).left;
    if(!probe){assert.equal(held,'0px');assert.equal(left,0);}
    await page.mouse.up();await page.locator('.stop-button').click();return {playing,held,left,settled:await origin()};
  });
  await observe('ruler and arrangement cursor stems have matching width and alignment',async()=>{
    await scroll(0);await field('Project position','4.1.1.37');
    const geometry=await page.evaluate(()=>{
      const ruler=document.querySelector('.ruler-playhead'),line=document.querySelector('.playhead');
      const r=ruler.getBoundingClientRect(),l=line.getBoundingClientRect(),after=getComputedStyle(ruler,'::after');
      return {rulerClip:getComputedStyle(ruler).clipPath,rulerWidth:r.width,bodyWidth:l.width,
        stemWidth:parseFloat(after.width)||null,stemX:Number.isFinite(parseFloat(after.left))?r.x+parseFloat(after.left):null,
        bodyX:l.x,bodyChildren:line.children.length,ratio:devicePixelRatio};
    });
    if(!probe){assert.equal(geometry.rulerClip,'none');assert.equal(geometry.stemWidth,geometry.bodyWidth);
      assert.ok(Math.abs(geometry.stemX-geometry.bodyX)<.02,JSON.stringify(geometry));assert.equal(geometry.bodyChildren,0);}
    const box=await page.locator('.ruler-playhead').boundingBox();
    await page.screenshot({path:path.join(output,probe?'cursor-before.png':'cursor-after.png'),clip:{x:Math.floor(box.x-24),y:Math.floor(box.y-5),width:64,height:180}});
    return geometry;
  });
  await observe('viewport and cursor have no renderer errors',async()=>{assert.deepEqual(errors,[]);return await pose();});
}catch(error){console.error(error.stack);process.exitCode=1;}finally{
  fs.writeFileSync(report,JSON.stringify({probe,results,errors},null,2));
  if(app){await app.evaluate(({BrowserWindow})=>{for(const w of BrowserWindow.getAllWindows())w.destroy();});await app.close();}
}})();
