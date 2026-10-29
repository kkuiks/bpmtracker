/* Independent source/project timing and history checks; no recordings or model. */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { stripTypeScriptTypes } = require('node:module');
const app = path.resolve(__dirname, '..');
const generated = fs.mkdtempSync(path.join(os.tmpdir(), 'bpmtracker-map-contract-'));
for (const name of ['model', 'music', 'analysis-map', 'click-level', 'history', 'arrangement']) {
  const source = fs.readFileSync(path.join(app, 'src', name + '.ts'), 'utf8');
  const js = stripTypeScriptTypes(source, { mode: 'transform', sourceUrl: name + '.ts' });
  fs.writeFileSync(path.join(generated, name + '.mjs'), js.replace(/from "\.\/([^".]+)"/g, 'from "./$1.mjs"'));
}
const main = fs.readFileSync(path.join(app, 'electron/main.cjs'), 'utf8');
const validProject = vm.runInNewContext(main.slice(main.indexOf('function validProject('), main.indexOf('async function atomicJson(')) + '\nvalidProject;');

const fixtures = [
  { id: 'F01', bpm: 120, n: 4, d: 4, phase: 0, duration: 20, events: [], anchorQuarter: 0 },
  { id: 'F02', bpm: 87.5, n: 3, d: 4, phase: -.37, duration: 20, events: [], anchorQuarter: 0 },
  { id: 'F03', bpm: 120, n: 4, d: 4, phase: 0, duration: 24, events: [{time:3,quarter:6,bpm:90},{time:11,quarter:18,bpm:150}], anchorQuarter: 0 },
  { id: 'F04', bpm: 120, n: 4, d: 4, phase: 0, duration: 24, events: [{time:3,quarter:6,numerator:3,denominator:4},{time:6,quarter:12,numerator:7,denominator:4}], anchorQuarter: 0 },
  { id: 'F05', bpm: 120, n: 4, d: 4, phase: 0, duration: 18, events: [{time:4,quarter:8,bpm:90,numerator:6,denominator:8},{time:8,quarter:14,bpm:150}], anchorQuarter: 0 },
  { id: 'F06', bpm: 120, n: 4, d: 4, phase: -.2, duration: 20, events: [{time:3.8,quarter:8,bpm:90},{time:7.8,quarter:14,numerator:3,denominator:4}], anchorQuarter: 4, trim: true },
];

function sourceQuarter(map, seconds) {
  let value = -map.initial.bar_zero_source_seconds * map.initial.bpm / 60;
  let previous = 0, rate = map.initial.bpm;
  for (const event of map.events) {
    if (event.time > seconds) break;
    value += (event.time - previous) * rate / 60;
    previous = event.time; rate = event.bpm ?? rate;
  }
  return value + (seconds - previous) * rate / 60;
}
function projectTime(project, target) {
  let value = 0, previous = 0, rate = project.bpm;
  for (const event of [...project.tempos].sort((a,b)=>a.quarter-b.quarter)) {
    if (event.quarter > target) break;
    value += (event.quarter - previous) * 60 / rate;
    previous = event.quarter; rate = event.bpm;
  }
  return value + (target - previous) * 60 / rate;
}
function musicalBar(map, seconds) {
  let n=map.initial.numerator,d=map.initial.denominator,origin=0;
  for(const e of map.events) if(e.time<=seconds&&e.numerator!==undefined){n=e.numerator;d=e.denominator;origin=e.quarter;}
  const unit=(sourceQuarter(map,seconds)-origin)/(n*4/d);
  return Math.abs(unit-Math.round(unit))<1e-7;
}
function expectedBeats(map, from, to, origin) {
  const points=[0,...map.events.map(e=>e.time),map.duration_seconds],result=[];
  let n=map.initial.numerator,d=map.initial.denominator,rate=map.initial.bpm,barOrigin=0;
  for(let i=0;i<points.length-1;i++){
    if(i){const e=map.events[i-1];rate=e.bpm??rate;if(e.numerator!==undefined){n=e.numerator;d=e.denominator;barOrigin=e.quarter;}}
    const start=Math.max(from,points[i]),end=Math.min(to,points[i+1]);if(end<=start)continue;
    const a=sourceQuarter(map,start),z=sourceQuarter(map,end),step=4/d;
    for(let q=barOrigin+Math.ceil((a-barOrigin-1e-8)/step)*step;q<z-1e-8;q+=step){
      const time=start+(q-a)*60/rate;
      result.push({time:origin+time,strong:Math.abs((q-barOrigin)/(n*step)-Math.round((q-barOrigin)/(n*step)))<1e-7});
    }
  }
  return result;
}
function clockBeats(clocks, left, right) {
  const result=[];
  for(const clock of clocks){
    const start=Math.max(left,clock.start),end=Math.min(right,clock.end);if(end<=start)continue;
    const step=60/clock.bpm*4/clock.denominator;
    const first=Math.ceil((start-clock.phase-1e-8)/step);
    for(let beat=first,time=clock.phase+first*step;time<end-1e-8;beat++,time=clock.phase+beat*step)
      result.push({time,strong:((beat%clock.numerator)+clock.numerator)%clock.numerator===0});
  }
  return result;
}
const equivalent = value => JSON.parse(JSON.stringify(value));
(async()=>{
  const model=await import(pathToFileURL(path.join(generated,'model.mjs')));
  const music=await import(pathToFileURL(path.join(generated,'music.mjs')));
  const maps=await import(pathToFileURL(path.join(generated,'analysis-map.mjs')));
  const arrangement=await import(pathToFileURL(path.join(generated,'arrangement.mjs')));
  const {ProjectHistory}=await import(pathToFileURL(path.join(generated,'history.mjs')));
  const click=await import(pathToFileURL(path.join(generated,'click-level.mjs')));
  assert.equal(click.upgradedClickGain(.7,'earlier-plus6-v1'),.7);
  assert.equal(click.upgradedClickGain(.7,click.CLICK_GAIN_POLICY),.7);
  assert.equal(click.upgradedClickGain(.7,undefined),click.DEFAULT_CLICK_GAIN);
  assert.equal(click.upgradedClickGain(1.1,undefined),1.1);
  console.log('PASS saved click reference compatibility');
  const reports=[];
  const exported=[];
  for(const f of fixtures){
    const map={format:'bpmtracker-continuous-beat-map',version:1,status:'map',duration_seconds:f.duration,
      initial:{bpm:f.bpm,numerator:f.n,denominator:f.d,bar_zero_source_seconds:f.phase},events:f.events};
    maps.validateVariableMap(map);
    let p=model.createProject();
    const asset={id:'01234567-89ab-4cde-8123-456789abcdef',name:'fixture.wav',sourcePath:'/fixture.wav',pcmPath:'/fixture.f32',peaksPath:'/fixture.peaks',sampleRate:48000,channels:2,frames:48000*40,duration:40,peakBinFrames:256,peakBins:7500,originalSize:1,originalModified:0};
    p=model.importAssets(p,[asset],{mode:'sequence',copy:false,start:f.trim?3:0,targetTrackId:null,beforeTrackId:null});
    const clip=p.clips[0];clip.sourceStart=f.trim?7.2:0;clip.duration=f.trim?14:f.duration;
    const analysisStart=f.trim?5:0;
    if(f.trim){
      clip.groupId='stems';
      p.tracks.push({...p.tracks[0],id:'stem-track'});
      p.clips.push({...clip,id:'stem-clip',trackId:'stem-track',start:clip.start+.15});
      p.tracks.push({...p.tracks[0],id:'other-track'});
      p.clips.push({...clip,id:'unrelated',trackId:'other-track',start:50,sourceStart:0,duration:10,groupId:null});
      p.tracks.push({...p.tracks[0],id:'musical-other-track',timeBase:'musical'});
      p.clips.push({...clip,id:'musical-unrelated',trackId:'musical-other-track',start:55,musicalStart:105,sourceStart:0,duration:10,groupId:null});
      p.tempos=[{id:'outside-tempo',quarter:80,bpm:100,origin:'manual'}];
      p.signatures=[{id:'outside-signature',quarter:80+4*100/60,bar:23,numerator:3,denominator:4,origin:'manual'}];
    }
    const analysis={id:'analysis-'+f.id,clipId:clip.id,assetId:asset.id,sourceStart:analysisStart,
      sourceEnd:analysisStart+f.duration,initialTap:null,createdAt:'2026-10-29',result:structuredClone(map),recordPath:'/analysis.json'};
    const original=JSON.stringify(analysis.result);
    const saved=model.applyAnalysis(p,analysis);const clock=saved.clocks.at(-1);
    assert.equal(clock.kind,'map');
    const applied=music.placeClockOnProject(saved,clock);
    const next=applied.project,ref=next.clips.find(c=>c.id===clip.id);
    const origin=ref.start-ref.sourceStart+analysisStart;
    const from=clip.sourceStart-analysisStart,to=from+clip.duration;
    const initial=next.signatures.find(e=>e.id===analysis.id+':signature:initial');
    const shift=initial.quarter-f.anchorQuarter;
    const samples=[from,from+.125,(from+to)/2,to-.001,...map.events.filter(e=>e.time>=from&&e.time<to).map(e=>e.time)];
    let maxError=0;
    for(const t of samples){
      const q=sourceQuarter(map,t);
      maxError=Math.max(maxError,Math.abs(projectTime(next,shift+q)-(origin+t)));
      assert.ok(Math.abs(music.timeAtQuarter(next,shift+q)-(origin+t))<=1/48000);
      if(musicalBar(map,t))assert.equal(music.positionAtQuarter(next,shift+q).beat,1);
    }
    assert.ok(maxError<=1/48000,f.id+' source/project timing');
    assert.equal(JSON.stringify(next.analyses[0].result),original);
    assert.equal(ref.sourceStart,clip.sourceStart);assert.equal(ref.duration,clip.duration);
    if(f.trim){
      assert.ok(Math.abs(next.clips.find(c=>c.id==='stem-clip').start-ref.start-.15)<1e-8);
      assert.equal(next.clips.find(c=>c.id==='unrelated').start,50);
      const musical=next.clips.find(c=>c.id==='musical-unrelated');
      assert.ok(Math.abs(musical.musicalStart-105)<1e-8);
      assert.ok(Math.abs(musical.start-projectTime(next,105))<1e-8);
      assert.ok(Math.abs(projectTime(next,next.tempos.find(e=>e.id==='outside-tempo').quarter)-40)<1e-8);
      assert.ok(Math.abs(projectTime(next,next.signatures.find(e=>e.id==='outside-signature').quarter)-44)<1e-8);
    }
    const repeated=music.placeClockOnProject(next,next.clocks.at(-1)).project;
    assert.equal(repeated.tempos.length,next.tempos.length);assert.equal(repeated.signatures.length,next.signatures.length);
    assert.ok(Math.abs(repeated.clips[0].start-next.clips[0].start)<1e-8);
    const history=new ProjectHistory(saved);history.commit(next,'Apply Tempo map');
    assert.deepEqual(equivalent(history.undo()),equivalent(saved));assert.deepEqual(equivalent(history.redo()),equivalent(next));
    const reopened=music.upgradeProject(equivalent(next));validProject(equivalent(reopened));
    assert.equal(JSON.stringify(reopened.analyses[0].result),original);
    const preview=model.clockGeometries(saved,clock);assert.ok(preview.length);
    const expected=expectedBeats(map,from,to,origin);
    const previewOrigin=saved.clips[0].start-saved.clips[0].sourceStart+analysisStart;
    const shiftedPreview=model.clockGeometries(next,next.clocks.at(-1));
    for(const [label,actual] of [['preview',clockBeats(shiftedPreview,origin+from,origin+to)],
                               ['project',clockBeats(music.projectClocks(next),origin+from,origin+to)]]){
      assert.equal(actual.length,expected.length,f.id+' '+label+' beat count');
      actual.forEach((beat,i)=>{assert.ok(Math.abs(beat.time-expected[i].time)<=1/48000,f.id+' '+label+' beat time');assert.equal(beat.strong,expected[i].strong,f.id+' '+label+' strong beat');});
    }
    assert.equal(clockBeats(preview,previewOrigin+from,previewOrigin+to).length,expected.length);
    const conflict={...saved,tempos:[...saved.tempos,{id:'manual-conflict',quarter:20,bpm:399,origin:'manual'}]};
    if(!f.trim)assert.throws(()=>music.placeClockOnProject(conflict,clock),/conflict/);
    reports.push({id:f.id,passed:true,maxTimingErrorSeconds:maxError,tempoDeclarations:next.tempos.length,signatureDeclarations:next.signatures.length});
    exported.push({id:f.id,project:next,from:origin+from,to:origin+to,expectedBeats:expected});
    console.log('PASS',f.id,'timing, phase, persistence, history, reapplication');
  }
  const compatible=structuredClone(exported[0].project);
  compatible.tempos.push({id:'manual-compatible',quarter:4,bpm:120,origin:'manual'});
  compatible.signatures.push({id:'signature-compatible',quarter:4,bar:2,numerator:4,denominator:4,origin:'manual'});
  const preserved=music.placeClockOnProject(compatible,compatible.clocks[0]).project;
  assert.equal(preserved.tempos.find(e=>e.id==='manual-compatible').origin,'manual');
  assert.equal(preserved.signatures.find(e=>e.id==='signature-compatible').quarter,4);
  const badPhase=structuredClone(exported[0].project);
  badPhase.signatures.push({id:'manual-bad-phase',quarter:2,bar:2,numerator:4,denominator:4,origin:'manual'});
  const unchanged=JSON.stringify(badPhase);
  assert.throws(()=>music.placeClockOnProject(badPhase,badPhase.clocks[0]),/conflict/);
  assert.equal(JSON.stringify(badPhase),unchanged);
  console.log('PASS compatible manual points and atomic signature conflict');
  const compatibility=[];
  for(const version of [1,2,3]){
    let p=model.createProject();
    const asset={id:'01234567-89ab-4cde-8123-456789abcdef',name:'legacy.wav',sourcePath:'/legacy.wav',sampleRate:48000,channels:1,frames:480000,duration:10};
    p=model.importAssets(p,[asset],{mode:'sequence',copy:false,start:0,targetTrackId:null,beforeTrackId:null});
    p=model.applyAnalysis(p,{id:'legacy',clipId:p.clips[0].id,assetId:asset.id,sourceStart:0,sourceEnd:10,initialTap:null,createdAt:'2026-10-29',recordPath:'/legacy.json',
      result:{quarter_bpm:120,period_seconds:.5,time_signature:{numerator:4,denominator:4},offset_seconds:.137}});
    delete p.clocks[0].kind;p.version=version;
    if(version===1){delete p.bpm;delete p.signature;delete p.tempos;delete p.signatures;delete p.timingPolicy;}
    if(version===2){p.tempos=[{id:'legacy-tempo',quarter:0,bpm:120,origin:'manual'}];p.signatures=[{id:'legacy-signature',bar:1,numerator:4,denominator:4,origin:'manual'}];}
    validProject(equivalent(p));const opened=music.upgradeProject(p);validProject(equivalent(opened));
    assert.equal(opened.version,3);assert.equal(opened.clips[0].start,0);assert.equal(opened.clips[0].duration,10);
    assert.equal(opened.clocks[0].original.offset,.137);assert.equal(opened.analyses[0].result.quarter_bpm,120);
    compatibility.push({version,passed:true});console.log('PASS legacy version',version);
  }
  const missing=structuredClone(exported[0].project);missing.analyses=[];
  assert.throws(()=>validProject(missing),/variable analysis/);
  const deletionBase = { ...model.createProject(), bpm: 152, signature: { numerator: 7, denominator: 8 },
    tempos: [
      { id: 't0', quarter: 0, bpm: 152, origin: 'manual' },
      { id: 't1', quarter: 16, bpm: 90, origin: 'manual' },
      { id: 't2', quarter: 40, bpm: 140, origin: 'manual' },
    ],
    signatures: [
      { id: 's0', quarter: 0, bar: 1, numerator: 7, denominator: 8, origin: 'manual' },
      { id: 's1', quarter: 32, bar: 11, numerator: 3, denominator: 4, origin: 'manual' },
      { id: 's2', quarter: 52, bar: 18, numerator: 5, denominator: 8, origin: 'manual' },
    ] };
  const inheritedStart = music.removeMapEvents(music.editProjectMap(structuredClone(deletionBase)),
    [{ kind: 'tempo', id: 't0' }, { kind: 'signature', id: 's0' }]);
  const lateStart = { ...deletionBase,
    tempos: deletionBase.tempos.map(point => ({ ...point, quarter: point.quarter + 8 })),
    signatures: deletionBase.signatures.map(point => ({ ...point, quarter: point.quarter + 8 })) };
  const lastLateStart = { ...lateStart, tempos: lateStart.tempos.slice(0, 1), signatures: lateStart.signatures.slice(0, 1) };
  const deletionCases = [
    { name: 'start tempo', tempos: ['t0'], signatures: [], bpm: 90, n: 7, d: 8 },
    { name: 'start signature', tempos: [], signatures: ['s0'], bpm: 152, n: 3, d: 4 },
    { name: 'multiple start points', tempos: ['t0', 't1'], signatures: ['s0', 's1'], bpm: 140, n: 5, d: 8 },
    { name: 'later points', tempos: ['t1'], signatures: ['s1'], bpm: 152, n: 7, d: 8 },
    { name: 'all declarations', tempos: ['t0', 't1', 't2'], signatures: ['s0', 's1', 's2'], bpm: 120, n: 4, d: 4 },
    { name: 'inherited first tempo', base: inheritedStart, tempos: ['t1'], signatures: [], bpm: 140, n: 3, d: 4 },
    { name: 'inherited first signature', base: inheritedStart, tempos: [], signatures: ['s1'], bpm: 90, n: 5, d: 8 },
    { name: 'all inherited declarations', base: inheritedStart, tempos: ['t1', 't2'], signatures: ['s1', 's2'], bpm: 120, n: 4, d: 4 },
    { name: 'first declarations after time zero', base: lateStart, tempos: ['t0'], signatures: ['s0'], bpm: 90, n: 3, d: 4 },
    { name: 'last declarations after time zero', base: lastLateStart, tempos: ['t0'], signatures: ['s0'], bpm: 120, n: 4, d: 4 },
  ];
  const deletions = [];
  for (const test of deletionCases) {
    const base = music.editProjectMap(structuredClone(test.base ?? deletionBase));
    const original = JSON.stringify(base);
    const selected = [...test.tempos.map(id => ({ kind: 'tempo', id })), ...test.signatures.map(id => ({ kind: 'signature', id }))];
    const next = music.removeMapEvents(base, selected);
    assert.equal(next.bpm, test.bpm, test.name);
    assert.deepEqual(next.signature, { numerator: test.n, denominator: test.d }, test.name);
    const clock = music.projectClocks(next)[0];
    assert.equal(clock.bpm, test.bpm);assert.equal(clock.numerator, test.n);assert.equal(clock.denominator, test.d);
    for (const point of [...next.tempos, ...music.signatureDeclarations(next)]) {
      const old = [...base.tempos, ...base.signatures].find(event => event.id === point.id);
      assert.ok(Math.abs(projectTime(next, point.quarter) - projectTime(base, old.quarter)) < 1e-8, test.name + ' surviving declaration audio time');
    }
    assert.equal(JSON.stringify(base), original, 'deletion does not mutate history');
    const history = new ProjectHistory(base);history.commit(next, 'Delete map points');
    assert.deepEqual(equivalent(history.undo()), equivalent(base));assert.deepEqual(equivalent(history.redo()), equivalent(next));
    const reopened = music.upgradeProject(equivalent(next));validProject(equivalent(reopened));
    assert.equal(reopened.bpm, test.bpm);assert.deepEqual(reopened.signature, next.signature);
    deletions.push({ name: test.name, passed: true });
  }
  const legacySignature = { ...deletionBase, signatures: deletionBase.signatures.map(({ quarter, ...point }) => point) };
  const legacyDeleted = music.removeMapEvents(legacySignature, [{ kind: 'signature', id: 's0' }]);
  assert.deepEqual(legacyDeleted.signature, { numerator: 3, denominator: 4 });
  for (const point of music.signatureDeclarations(legacyDeleted)) {
    assert.ok(Math.abs(projectTime(legacyDeleted, point.quarter) - music.timeAtBar(legacySignature, legacySignature.signatures.find(old => old.id === point.id).bar)) < 1e-8);
  }
  assert.equal(music.removeMapEvents(deletionBase, [{ kind: 'tempo', id: 'missing' }]), deletionBase);
  deletions.push({ name: 'legacy bar coordinates and absent selection', passed: true });
  const following = [];
  function checkFollowing(name, before, next, bpm, numerator, denominator, shifts = {}) {
    assert.equal(next.bpm, bpm, name + ' initial BPM');
    assert.deepEqual(next.signature, { numerator, denominator }, name + ' initial signature');
    const clock = music.projectClocks(next)[0];
    assert.equal(clock.bpm, bpm);assert.equal(clock.numerator, numerator);assert.equal(clock.denominator, denominator);
    for (const point of [...next.tempos, ...music.signatureDeclarations(next)]) {
      const old = [...before.tempos, ...before.signatures].find(event => event.id === point.id);
      if (old) assert.ok(Math.abs(projectTime(next, point.quarter) - projectTime(before, old.quarter) - (shifts[point.id] ?? 0)) < 1e-8,
        name + ' declaration audio time');
    }
    const history = new ProjectHistory(before);history.commit(next, name);
    assert.deepEqual(equivalent(history.undo()), equivalent(before));assert.deepEqual(equivalent(history.redo()), equivalent(next));
    const reopened = music.upgradeProject(equivalent(next));validProject(equivalent(reopened));
    assert.equal(reopened.bpm, bpm);assert.deepEqual(reopened.signature, next.signature);
    following.push({ name, passed: true });
    return next;
  }
  let followed = inheritedStart;
  let updated = music.putTempo(followed, { ...followed.tempos.find(point => point.id === 't1'), bpm: 135 });
  followed = checkFollowing('edit inherited first tempo', followed, updated, 135, 3, 4);
  updated = music.putSignature(followed, { ...followed.signatures.find(point => point.id === 's1'), numerator: 5, denominator: 8 });
  followed = checkFollowing('edit inherited first signature', followed, updated, 135, 5, 8);
  updated = music.putTempo(followed, { ...followed.tempos.find(point => point.id === 't2'), bpm: 170 });
  followed = checkFollowing('later tempo leaves initial state', followed, updated, 135, 5, 8);
  updated = music.putSignature(followed, { ...followed.signatures.find(point => point.id === 's2'), numerator: 7, denominator: 8 });
  followed = checkFollowing('later signature leaves initial state', followed, updated, 135, 5, 8);
  followed = music.upgradeProject(equivalent(followed));
  updated = music.putTempo(followed, { ...followed.tempos.find(point => point.id === 't1'), bpm: 115 });
  followed = checkFollowing('edit inherited tempo after reopen', followed, updated, 115, 5, 8);
  updated = music.putSignature(followed, { ...followed.signatures.find(point => point.id === 's1'), numerator: 6, denominator: 8 });
  followed = checkFollowing('edit inherited signature after reopen', followed, updated, 115, 6, 8);
  updated = music.removeMapEvents(followed, [{ kind: 'tempo', id: 't1' }, { kind: 'signature', id: 's1' }]);
  followed = checkFollowing('delete inherited sources again', followed, updated, 170, 7, 8);
  updated = music.removeMapEvents(followed, [{ kind: 'tempo', id: 't2' }, { kind: 'signature', id: 's2' }]);
  followed = checkFollowing('delete last inherited sources', followed, updated, 120, 4, 4);
  assert.equal(followed.initialTempoFollowsFirst, false);assert.equal(followed.initialSignatureFollowsFirst, false);
  const independent = music.editProjectMap({ ...lateStart, bpm: 90, signature: { numerator: 3, denominator: 4 } });
  updated = music.putTempo(independent, { ...independent.tempos[0], bpm: 100 });
  checkFollowing('independent initial values stay independent', independent, updated, 90, 3, 4);
  const oldCopy = equivalent(inheritedStart);
  delete oldCopy.initialTempoFollowsFirst;delete oldCopy.initialSignatureFollowsFirst;
  let reopenedCopy = music.upgradeProject(oldCopy);
  updated = music.putTempo(reopenedCopy, { ...reopenedCopy.tempos[0], bpm: 105 });
  reopenedCopy = checkFollowing('older copied tempo adopts following', reopenedCopy, updated, 105, 3, 4);
  updated = music.putSignature(reopenedCopy, { ...reopenedCopy.signatures[0], numerator: 7, denominator: 8 });
  checkFollowing('older copied signature adopts following', reopenedCopy, updated, 105, 7, 8);
  const oldBrokenCopy = equivalent(exported[2].project);
  oldBrokenCopy.tempos = oldBrokenCopy.tempos.filter(point => !point.id.endsWith(':tempo:initial'));
  delete oldBrokenCopy.initialTempoFollowsFirst;delete oldBrokenCopy.initialSignatureFollowsFirst;
  const repairedCopy = music.upgradeProject(oldBrokenCopy);
  checkFollowing('repair identified older deleted analysis initial', oldBrokenCopy, repairedCopy,
    oldBrokenCopy.tempos[0].bpm, oldBrokenCopy.signature.numerator, oldBrokenCopy.signature.denominator);
  assert.deepEqual(repairedCopy.clips.map(clip => clip.start), oldBrokenCopy.clips.map(clip => clip.start));
  assert.deepEqual(repairedCopy.analyses, oldBrokenCopy.analyses);
  updated = arrangement.moveArrangement(inheritedStart, { clips: [], maps: [{ kind: 'tempo', id: 't1' }] }, 1, false);
  checkFollowing('move followed tempo without changing its order', inheritedStart, updated, 90, 3, 4, { t1: 1 });
  updated = arrangement.moveArrangement(inheritedStart, { clips: [], maps: [{ kind: 'tempo', id: 't1' }] }, 30, false);
  checkFollowing('moving tempo past another changes followed source', inheritedStart, updated, 140, 3, 4, { t1: 30 });
  const signatureMove = music.removeMapEvents({ ...model.createProject(), signatures: structuredClone(deletionBase.signatures) },
    [{ kind: 'signature', id: 's0' }]);
  updated = arrangement.moveArrangement(signatureMove, { clips: [], maps: [{ kind: 'signature', id: 's1' }] }, 14, false);
  checkFollowing('moving signature past another changes followed source', signatureMove, updated, 120, 5, 8, { s1: 14 });
  updated = music.putTempo(inheritedStart, { id: 'earlier', quarter: 2, bpm: 110, origin: 'manual' });
  checkFollowing('earlier inserted declaration becomes followed source', inheritedStart, updated, 110, 3, 4);
  const invalidFollowing = equivalent(inheritedStart);invalidFollowing.initialTempoFollowsFirst = 'true';
  assert.throws(() => validProject(invalidFollowing), /following state/);
  console.log('PASS start-declaration deletion, surviving audio times, history and reopen:', deletions.length);
  console.log('PASS initial values follow edited declarations:', following.length);
  const outputIndex=process.argv.indexOf('--output');
  if(outputIndex>=0)fs.writeFileSync(process.argv[outputIndex+1],JSON.stringify({fixtures:exported,legacy:compatibility,deletions,following},null,2));
  console.log(JSON.stringify({passed:reports.length,total:fixtures.length,fixtures:reports,legacy:compatibility,deletions,following}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;}).finally(()=>fs.rmSync(generated,{recursive:true,force:true}));
