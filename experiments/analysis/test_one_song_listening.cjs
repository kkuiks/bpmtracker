/* Actual Chromium/Web Audio checks. These are not a human listening judgment.
 * ONE_SONG_URL points to a generated page served over localhost.
 * PLAYWRIGHT_MODULE and CHROMIUM_BINARY may use an existing isolated runtime. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
(async()=>{
 const output=process.env.ONE_SONG_TEST_OUTPUT||'/tmp/joljak-one-song-browser';await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_BINARY});
 const page=await browser.newPage({viewport:{width:1320,height:1050},acceptDownloads:true});page.setDefaultTimeout(120000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(process.env.ONE_SONG_URL||'http://127.0.0.1:8765/listening.html');
  await page.waitForFunction(()=>window.oneSongDebug?.state.ready||window.oneSongDebug?.state.error);
  const status=await page.evaluate(()=>({ready:oneSongDebug.state.ready,error:oneSongDebug.state.error}));assert.equal(status.error,null);assert.equal(status.ready,true);
  assert.equal(await page.locator('input[name=variant]').count(),4);
  const source=await page.evaluate(()=>({...oneSongDebug.state.bundle.source}));
  const fingerprint=await page.evaluate(()=>oneSongDebug.sourceFingerprint());
  const ids=await page.locator('input[name=variant]').evaluateAll(nodes=>nodes.map(n=>n.value));
  const auditionStart=await page.evaluate(()=>Math.min(oneSongDebug.state.bundle.source.duration_seconds-5,Math.max(...oneSongDebug.state.bundle.variants.map(v=>v.beats_seconds[0]||0))+2));
  await page.locator('#seek').evaluate((node,value)=>{node.value=String(Math.max(0,value));node.dispatchEvent(new Event('change',{bubbles:true}))},auditionStart);
  await page.click('#play');await page.waitForFunction(()=>oneSongDebug.state.playing&&oneSongDebug.state.context.currentTime>oneSongDebug.state.startAt+.06);
  const baseline=await page.evaluate(()=>({time:oneSongDebug.state.context.currentTime,position:oneSongDebug.position(),musicAt:oneSongDebug.state.musicVoice.startAt,startCount:oneSongDebug.state.startRecords.length}));
  for(let i=0;i<ids.length;i++){
   // The old radio remains selected while a requested WAV decodes: it describes
   // what is currently audible. Wait for the asynchronous switch after clicking.
   await page.locator('input[name=variant]').nth(i).click();
   await page.waitForFunction(id=>oneSongDebug.state.activeId===id&&!oneSongDebug.state.pendingId,ids[i]);
   const current=await page.evaluate(()=>({time:oneSongDebug.state.context.currentTime,position:oneSongDebug.position(),playing:oneSongDebug.state.playing,musicAt:oneSongDebug.state.musicVoice?.startAt,startCount:oneSongDebug.state.startRecords.length,cache:oneSongDebug.state.cache.size}));
   assert.equal(current.playing,true);assert.equal(current.musicAt,baseline.musicAt);assert.equal(current.startCount,baseline.startCount);
   assert.ok(Math.abs((current.position-baseline.position)-(current.time-baseline.time))<.02,'A/B switch must not restart or shift source time');
   assert.ok(current.cache<=2,'decoded click cache is bounded');
   await page.waitForFunction(()=>oneSongDebug.liveVoiceCount()===1);
   await page.waitForFunction(()=>oneSongDebug.clickPeak()>.0001,{},{timeout:8000});
  }
  const switches=await page.evaluate(()=>oneSongDebug.state.switchRecords);
  assert.ok(switches.length>=3);for(const s of switches){assert.equal(s.offset,s.transportPositionAtSwitch);assert.equal(s.fadeSeconds,.03);assert.equal(s.musicStartAt,baseline.musicAt)}
  await page.click('#clickMute');await page.waitForFunction(()=>oneSongDebug.clickPeak()<.000001);
  assert.equal(await page.locator('#clickMute').getAttribute('aria-pressed'),'true');
  await page.click('#clickMute');await page.locator('#clickVolume').evaluate(node=>{node.value='35';node.dispatchEvent(new Event('input',{bubbles:true}))});
  assert.equal(await page.locator('#clickLevel').textContent(),'35%');
  await page.click('#musicMute');assert.equal(await page.locator('#musicMute').getAttribute('aria-pressed'),'true');await page.click('#musicMute');
  await page.click('#pause');const paused=await page.evaluate(()=>oneSongDebug.position());
  await page.waitForTimeout(80);assert.equal(await page.evaluate(()=>oneSongDebug.position()),paused);
  await page.locator('#sections button').first().click();await page.check('#loop');
  const loop=await page.evaluate(()=>({...oneSongDebug.state.loop}));
  await page.locator('#seek').evaluate((node,value)=>{node.value=String(value);node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}))},loop.end-.12);
  await page.click('#play');
  await page.waitForFunction(()=>oneSongDebug.state.musicVoice?.source.loop&&oneSongDebug.position()<oneSongDebug.state.loop.start+.8);
  const nativeLoop=await page.evaluate(()=>({music:{enabled:oneSongDebug.state.musicVoice.source.loop,start:oneSongDebug.state.musicVoice.source.loopStart,end:oneSongDebug.state.musicVoice.source.loopEnd},click:[...oneSongDebug.state.clickVoices].map(v=>({enabled:v.source.loop,start:v.source.loopStart,end:v.source.loopEnd}))}));
  assert.equal(nativeLoop.music.enabled,true);assert.equal(nativeLoop.music.start,loop.start);assert.equal(nativeLoop.music.end,loop.end);assert.ok(nativeLoop.click.every(v=>v.enabled&&v.start===loop.start&&v.end===loop.end));
  // Block the UI briefly: native audio looping and the audio-clock position keep advancing.
  const clock=await page.evaluate(()=>{const before=oneSongDebug.state.context.currentTime;const end=performance.now()+120;while(performance.now()<end){}return{elapsed:oneSongDebug.state.context.currentTime-before,position:oneSongDebug.position(),loop:{...oneSongDebug.state.loop}}});
  assert.ok(clock.elapsed>.05);assert.ok(clock.position>=clock.loop.start&&clock.position<clock.loop.end);
  await page.click('#pause');await page.uncheck('#loop');
  await page.locator('#seek').evaluate((node,value)=>{node.value=String(value);node.dispatchEvent(new Event('change',{bubbles:true}))},source.duration_seconds-.05);
  const coverage=await page.evaluate(()=>oneSongDebug.state.bundle.variants.find(v=>v.id===oneSongDebug.state.activeId).coverage);
  if(coverage&&coverage.end<source.duration_seconds-.05)assert.equal(await page.locator('#coverage').getAttribute('data-verified'),'false');
  assert.deepEqual(await page.evaluate(()=>oneSongDebug.sourceFingerprint()),fingerprint);
  const offline=await page.evaluate(async()=>{const source=oneSongDebug.state.musicBuffer,offset=Math.min(1024,Math.floor(source.length/4)),frames=Math.min(4096,source.length-offset);const context=new OfflineAudioContext(source.numberOfChannels,frames,source.sampleRate),node=context.createBufferSource();node.buffer=source;node.playbackRate.value=1;node.connect(context.destination);node.start(0,offset/source.sampleRate);const result=await context.startRendering();let maximum=0;for(let channel=0;channel<source.numberOfChannels;channel++){const a=source.getChannelData(channel),b=result.getChannelData(channel);for(let i=0;i<frames;i++)maximum=Math.max(maximum,Math.abs(a[offset+i]-b[i]))}return{maximum_error:maximum,offset_frames:offset,rendered_frames:frames,sample_rate:result.sampleRate}});
  assert.ok(offline.maximum_error<.000001,'offline source playback preserves exact sample positions');
  const selected=await page.evaluate(()=>oneSongDebug.state.bundle.variants.find(v=>v.id===oneSongDebug.state.activeId));
  const downloads=[];
  for(const [id,digest,filename] of [['downloadClick',selected.click_sha256,'selected-click.wav'],['downloadMap',selected.map_sha256,'selected-map.json'],['downloadMidi',selected.midi_sha256,'selected-map.mid']]){
   if(!await page.locator('#'+id).isVisible())continue;
   const promise=page.waitForEvent('download');await page.click('#'+id);const download=await promise;
   const target=path.join(output,filename);await download.saveAs(target);const bytes=await fs.readFile(target);
   const actual=crypto.createHash('sha256').update(bytes).digest('hex');if(digest)assert.equal(actual,digest);
   downloads.push({id,bytes:bytes.length,sha256:actual});
  }
  await page.click('#toStart');assert.equal(await page.evaluate(()=>oneSongDebug.position()),0);
  await page.screenshot({path:path.join(output,'listening.png'),fullPage:true});assert.deepEqual(errors,[]);
  const result={passed:true,scope:'automated browser/Web Audio behavior; not a human listening verdict',source,
   variants:ids,checks:['verified source decode and unchanged PCM fingerprint','four clear named choices','shared-clock same-position A/B switching without music restart','30ms click crossfade with no leftover voices','bounded two-click decoded cache','music/click volumes and mute','pause and seek','native sample-clock looping despite UI blocking','coverage warning on unverified tail','offline exact-source sample-offset playback','selected click/map downloads preserve artifact hashes'],offline,downloads,switch_count:switches.length,page_errors:errors};
  await fs.writeFile(path.join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
