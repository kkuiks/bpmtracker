/* Run with PLAYWRIGHT_MODULE set to an installed playwright-core package path.
 * REVIEW_URL must point to a locally served generated review page.
 * This is a simulated UI test, never a human correction-time measurement. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
(async()=>{
 const out=process.env.REVIEW_TEST_OUTPUT||'/tmp/joljak-review-browser-results';await fs.mkdir(out,{recursive:true});
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_BINARY,headless:true});
 const page=await browser.newPage({viewport:{width:1360,height:1050},acceptDownloads:true});const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(process.env.REVIEW_URL||'http://127.0.0.1:8765/');
  await page.waitForFunction(()=>window.reviewDebug?.decoded!==null&&window.reviewDebug?.decoded!==undefined);
  const tracks=await page.locator('#track option').evaluateAll(nodes=>nodes.map(n=>n.value));
  for(const id of tracks){
   await page.selectOption('#track',id);await page.waitForFunction(id=>window.reviewDebug.session.track.id===id&&!!window.reviewDebug.decoded,id);
   const choices=await page.locator('#candidate option').evaluateAll(nodes=>nodes.map(n=>n.value));
   for(const choice of choices){await page.selectOption('#candidate',choice);await page.click('#choose');
    assert.equal(await page.locator('#status').getAttribute('data-error'),'false',`${id}/${choice}`);}
  }
  await page.selectOption('#track',tracks[0]);await page.waitForFunction(id=>window.reviewDebug.session.track.id===id&&!!window.reviewDebug.decoded,tracks[0]);
  assert.equal(await page.locator('#status').getAttribute('data-error'),'false');
  const source=await page.evaluate(()=>window.reviewDebug.session.state.source);
  await page.click('#play');await page.waitForFunction(()=>window.reviewDebug.playing&&window.reviewDebug.position()>.1);
  await page.click('#pause');
  const initial=await page.evaluate(()=>JSON.stringify(window.reviewDebug.session.state.map.grid));
  const anchor=await page.evaluate(()=>{const g=window.reviewDebug.session.state.map.grid,p=g[Math.min(20,g.length-2)];return {q:p.quarter_position,t:p.source_seconds+.003};});
  await page.fill('#anchorQ',String(anchor.q));await page.fill('#anchorT',String(anchor.t));await page.click('#anchor');
  assert.equal(await page.locator('#anchors .listline').count(),1);
  await page.click('#double');assert.equal(await page.locator('#status').getAttribute('data-error'),'true');
  await page.fill('#meterQ',String(anchor.q));await page.selectOption('#meterN','2');await page.click('#meter');
  const savedMap=await page.evaluate(()=>JSON.stringify(window.reviewDebug.session.state.map));
  let downloadPromise=page.waitForEvent('download');await page.click('#save');const download=await downloadPromise;
  const savePath=path.join(out,'simulated-review-session.json');await download.saveAs(savePath);
  const saved=JSON.parse(await fs.readFile(savePath));assert.equal(saved.source_audio_modified,false);assert.equal(saved.accepted,false);
  await page.click('#undo');assert.notEqual(await page.evaluate(()=>JSON.stringify(window.reviewDebug.session.state.map)),savedMap);
  await page.setInputFiles('#restore',savePath);await page.waitForFunction(expected=>JSON.stringify(window.reviewDebug.session.state.map)===expected,savedMap);
  downloadPromise=page.waitForEvent('download');await page.click('#exportClick');const clickDownload=await downloadPromise;
  const clickPath=path.join(out,'simulated-click.wav');await clickDownload.saveAs(clickPath);const wav=await fs.readFile(clickPath);
  assert.equal(wav.length,44+source.sample_frames*2);assert.equal(wav.readUInt32LE(24),source.sample_rate);
  assert.deepEqual(await page.evaluate(()=>window.reviewDebug.session.state.source),source);
  // Reload does not require analysis; restoring a saved map reproduces its exact grid.
  await page.reload();await page.waitForFunction(()=>!!window.reviewDebug?.decoded);await page.setInputFiles('#restore',savePath);
  await page.waitForFunction(expected=>JSON.stringify(window.reviewDebug.session.state.map)===expected,savedMap);
  assert.notEqual(initial,await page.evaluate(()=>JSON.stringify(window.reviewDebug.session.state.map.grid)));
  await page.click('#toSupport');
  assert.ok(await page.evaluate(()=>Math.abs(window.reviewDebug.position()-window.reviewDebug.session.state.map.grid[0].source_seconds)<1e-7));
  await page.screenshot({path:path.join(out,'review.png'),fullPage:true});assert.deepEqual(errors,[]);
  const result={passed:true,scope:'simulated browser workflow, not listening or human correction measurement',
    checks:['source hash/decode','shared audio-clock playback','anchor lock blocks unit changes','meter edit','undo','save/reload/restore','click WAV exact frames/rate','no page errors'],source};
  await fs.writeFile(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
