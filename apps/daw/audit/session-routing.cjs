// Controlled completions exercise the real React UI. No inference/audio claim.
const assert = require('node:assert/strict');
const { chromium } = require('../../../.daw-runtime/audit-tools/playwright-core');
async function project(page) {
  return page.evaluate(() => {
    const el = document.querySelector('.app-shell');
    let fiber = el[Object.keys(el).find(k => k.startsWith('__reactFiber$'))];
    while (fiber.return) fiber = fiber.return;
    fiber = fiber.stateNode.current;
    function find(f) {
      if (!f) return null;
      let hook = f.memoizedState;
      while (hook && typeof hook === 'object') {
        if (hook.memoizedState?.format === 'joljak-project') return hook.memoizedState;
        hook = hook.next;
      }
      return find(f.child) || find(f.sibling);
    }
    return JSON.parse(JSON.stringify(find(fiber)));
  });
}
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'/home/yooch/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome'});
  const results = [];
  try {
    for (const kind of ['decode', 'analyze', 'selection']) {
      const context = await browser.newContext({viewport:{width:1440,height:940}});
      await context.addInitScript(() => {
        const callbacks = new Set();
        window.auditJob = null;
        window.cancelled = [];
        const asset = {id:crypto.randomUUID(),name:'source.wav',sampleRate:48000,channels:1,frames:480000,duration:10,peakBins:1875,peakBinFrames:256,pcmPath:'/audit/audio.f32',peaksPath:'/audit/peaks.f32',sourcePath:'/audit/source.wav'};
        window.joljak = {
          kind:'electron', recovery:async()=>null, autosave:async()=>{}, closingProject:()=>true,
          registerAssets:async()=>{}, peaks:async()=>new Float32Array(3750).buffer,
          chooseAudio:async()=>['/audit/source.wav'],
          decode:async()=>{window.auditJob={id:crypto.randomUUID(),kind:'decode'};return window.auditJob.id;},
          analyze:async(_asset,start,end,tap,clipId)=>{window.auditJob={id:crypto.randomUUID(),kind:'analyze',clipId};return window.auditJob.id;},
          cancel:async id=>window.cancelled.push(id),
          onJob:callback=>{callbacks.add(callback);return()=>callbacks.delete(callback);},
          onCommand:()=>()=>{}, window:()=>{},
        };
        window.emitAudit = () => {
          const j = window.auditJob;
          const result = j.kind === 'decode' ? {assets:[asset]} : {id:j.id,clipId:j.clipId,assetId:asset.id,sourceStart:0,sourceEnd:10,result:{quarter_bpm:160,period_seconds:.375,time_signature:{numerator:4,denominator:4},offset_seconds:.1}};
          for (const callback of callbacks) callback({...j,stage:'complete',result});
        };
      });
      const page = await context.newPage();
      page.on('dialog', dialog=>dialog.accept());
      await page.goto('http://127.0.0.1:8998');
      await page.waitForSelector('.app-shell');
      await page.getByRole('button',{name:'Import Audio',exact:true}).first().click();
      await page.locator('.modal').getByRole('button',{name:'Import Audio',exact:true}).click();
      await page.waitForFunction(()=>window.auditJob !== null);
      if (kind !== 'decode') {
        await page.evaluate(()=>window.emitAudit());
        await page.waitForSelector('.audio-clip');
        await page.getByRole('button',{name:'Analyze Audio',exact:true}).click();
        await page.locator('.modal').getByRole('button',{name:'Analyze Audio',exact:true}).click();
        await page.waitForFunction(()=>window.auditJob.kind === 'analyze');
      }
      if (kind === 'selection') {
        await page.evaluate(()=>window.emitAudit());
        await page.getByRole('button',{name:'Apply Clock',exact:true}).click();
        await page.keyboard.press('Control+a');
        await page.keyboard.press('Delete');
        await page.waitForTimeout(100);
        const p = await project(page);
        try {assert.equal(p.clips.length,0);assert.equal(p.clocks.length,1);results.push({kind,status:'pass'});}
        catch(e){results.push({kind,status:'fail',error:e.message});}
        await context.close();
        continue;
      }
      const old = (await project(page)).id;
      await page.getByRole('button',{name:'File',exact:true}).click();
      await page.locator('.app-dropdown').getByRole('button',{name:/^New Project/}).click();
      await page.waitForTimeout(100);
      await page.evaluate(()=>window.emitAudit());
      await page.waitForTimeout(100);
      const p = await project(page);
      try {
        assert.notEqual(p.id,old);
        assert.equal(p.clips.length,0);
        assert.equal(p.analyses.length,0);
        assert.equal(p.assets.length,0);
        results.push({kind,status:'pass'});
      } catch (e) {results.push({kind,status:'fail',error:e.message});}
      await context.close();
    }
  } finally {await browser.close();}
  console.log(JSON.stringify(results,null,2));
  process.exitCode = results.some(r=>r.status === 'fail') ? 1 : 0;
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
