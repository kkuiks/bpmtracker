// Opt-in regression audit. Run with Node; never called by build or packaging.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Module = require('node:module');
const test = require('node:test');
const modules = new Map();
function source(name) {
  if (modules.has(name)) return modules.get(name).exports;
  const filename = path.resolve(__dirname, '../src', `${name}.ts`);
  const mod = new Module(filename, module); modules.set(name, mod);
  mod.require = (id) => id.startsWith('./') ? source(id.slice(2)) : require(id);
  let code = Module.stripTypeScriptTypes(fs.readFileSync(filename, 'utf8'), {mode:'transform'});
  const names=[...code.matchAll(/export (?:const|function|class) (\w+)/g)].map(m=>m[1]);
  code=code.replace(/import\s*\{([^}]+)\}\s*from\s*"([^"]+)";/g,'const {$1} = require("$2");').replace(/export (?=(?:const|function|class) )/g,'');
  mod._compile(code+'\nmodule.exports={'+names.join(',')+'};', filename);
  return mod.exports;
}
const model = source('model');
const {ProjectHistory} = source('history');
const asset = {id:'audio',name:'source.wav',sampleRate:48000,channels:1,frames:480000,duration:10};
function project() { return model.importAssets(model.createProject(), [asset], {mode:'sequence',start:2,copy:false}); }
function analysis(p, start=0, end=10, bpm=120) {
  return {id:`prediction-${start}-${end}`,clipId:p.clips[0].id,assetId:asset.id,sourceStart:start,sourceEnd:end,
    result:{period_seconds:60/bpm,quarter_bpm:bpm,time_signature:{numerator:4,denominator:4},offset_seconds:.125}};
}
function near(actual,expected,epsilon=1e-8) {assert.ok(Math.abs(actual-expected)<=epsilon,`${actual} != ${expected}`);}
test('musical snap requires a real clock; second snap stays available', () => {
  const p=project(); near(model.snapTime(p,2.317,'beat'),2.317); near(model.snapTime(p,2.317,'second'),2);
  const q=model.applyAnalysis(p,analysis(p)); near(model.snapTime(q,2.317,'beat'),2.125);
});
test('move/copy use seconds and leave source audio and original prediction intact', () => {
  const p=project(), q=model.applyAnalysis(p,analysis(p)); const raw=JSON.stringify(q);
  const r=model.moveClips(q,[q.clips[0].id],3,false,undefined,true);
  assert.equal(JSON.stringify(q),raw); assert.equal(r.clips.length,2); assert.equal(r.clocks.length,2);
  near(model.clockGeometry(r,r.clocks[1]).phase,5.125); assert.deepEqual(r.clocks[1].original,q.clocks[0].original);
  const moved=model.moveClips(q,[q.clips[0].id],-99,false); near(moved.clips[0].start,0); near(model.clockGeometry(moved,moved.clocks[0]).phase,.125);
});
test('normal sizing reveals/hides source without changing phase or stretching', () => {
  const p=project(), clocked=model.applyAnalysis(p,analysis(p));
  const trimmed=model.trimClips(clocked,[p.clips[0].id],'start',3,false);
  assert.deepEqual([trimmed.clips[0].start,trimmed.clips[0].sourceStart,trimmed.clips[0].duration],[5,3,7]);
  near(model.clockGeometry(trimmed,trimmed.clocks[0]).phase,2.125);
  const revealed=model.trimClips(trimmed,[p.clips[0].id],'start',-99,false);
  assert.deepEqual(revealed.clips,p.clips);
  const extended=model.trimClips(p,[p.clips[0].id],'end',99,false); near(extended.clips[0].duration,10);
});
test('split/delete preserve clock scope; deleting a range leaves a gap', () => {
  const p=project(), q=model.applyAnalysis(p,analysis(p));
  const s=model.splitClips(q,[p.clips[0].id],6,false); assert.equal(s.clips.length,2);
  assert.deepEqual(s.clips.map(c=>[c.start,c.sourceStart,c.duration]),[[2,0,4],[6,4,6]]);
  assert.deepEqual(s.clocks,q.clocks);
  const deleted=model.removeClips(s,[p.clips[0].id],false); near(model.clockGeometry(deleted,deleted.clocks[0]).phase,2.125);
  const gap=model.removeRange(q,{start:5,end:8,trackIds:[p.tracks[0].id]},false);
  assert.deepEqual(gap.clips.map(c=>[c.start,c.sourceStart,c.duration]),[[2,0,3],[8,6,4]]);
});
test('linked stems move/split/trim together, copies get independent groups', () => {
  const p=model.importAssets(model.createProject(),[asset,{...asset,id:'stem-2'}],{mode:'stems',copy:false,start:2});
  const m=model.moveClips(p,[p.clips[0].id],2,true); assert.deepEqual(m.clips.map(c=>c.start),[4,4]);
  const c=model.moveClips(p,[p.clips[0].id],10,true,undefined,true);
  assert.equal(c.clips.length,4); assert.notEqual(c.clips[0].groupId,c.clips[2].groupId); assert.equal(c.clips[2].groupId,c.clips[3].groupId);
  const s=model.splitClips(p,[p.clips[0].id],5,true); assert.equal(s.clips.length,4); assert.equal(s.clips[2].groupId,s.clips[3].groupId);
  const t=model.trimClips(p,[p.clips[0].id],'start',1,true); assert.deepEqual(t.clips.map(c=>c.sourceStart),[1,1]);
});
test('applying a selected-range clock preserves both outside phases and reset values', () => {
  const p=project(), a=analysis(p), q=model.applyAnalysis(p,a), r=model.applyAnalysis(q,analysis(p,3,5,150));
  assert.equal(r.clocks.length,3); assert.equal(r.analyses.length,2);
  const regions=model.audibleClocks(r).sort((a,b)=>a.start-b.start);
  assert.deepEqual(regions.map(c=>[c.start,c.end,c.bpm]),[[2,5,120],[5,7,150],[7,12,120]]);
  near(regions[0].phase,regions[2].phase); near(model.clockGeometry(r,{...r.clocks[1],values:r.clocks[1].original}).phase,2.125);
  near(r.clips[0].start,p.clips[0].start);
});
test('undo retains imported assets and raw predictions but reverts arrangement/clock edits', () => {
  const empty=model.createProject(), h=new ProjectHistory(empty), p=project(), a=analysis(p);
  h.commit(p,'import'); h.record(a); h.commit(model.applyAnalysis(h.current,a),'apply');
  assert.equal(h.undo().clocks.length,0); assert.equal(h.current.analyses.length,1);
  assert.equal(h.undo().clips.length,0); assert.equal(h.current.assets.length,1);
  assert.equal(h.redo().clips.length,1); assert.equal(h.redo().clocks.length,1);
  const saved={...h.current,assets:h.current.assets.map(a=>({...a,sourcePath:'collected/source.wav'}))}; h.saved(saved); h.undo();
  assert.equal(h.current.assets[0].sourcePath,'collected/source.wav');
});
function transport() {
  let Transport; const messages=[];
  const context=vm.createContext({sampleRate:48000,currentFrame:0,Float32Array,Map,Set,Math,
    AudioWorkletProcessor:class {constructor(){this.port={postMessage:data=>messages.push(data)};}},
    registerProcessor:(_name,value)=>Transport=value});
  vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../public/transport-worklet.js'),'utf8'),context);
  const instance=new Transport();
  return {instance,messages,context,send:data=>instance.port.onmessage({data}),
    block:()=>{const output=[new Float32Array(128),new Float32Array(128)];instance.process([],[output]);context.currentFrame+=128;return output;}};
}
function pcmTransport() {
  const t=transport(), pcm=Float32Array.from({length:48000*2},(_,i)=>i%97/200);
  t.send({type:'project',clips:[{id:'clip',assetId:'a',trackId:'t',start:0,sourceStart:0,duration:2,sampleRate:48000,channels:1,frames:pcm.length,gain:1,pan:0,audible:true}],clocks:[],masterGain:.5,end:2});
  t.send({type:'chunk',key:'a:0',buffer:pcm.buffer});return t;
}
test('worklet audio, mono pan and master use the same sample clock', () => {
  const t=pcmTransport();t.send({type:'transport',position:0,playing:true});const [l,r]=t.block();
  for(let i=0;i<128;i++){near(l[i],(i%97/200)*Math.SQRT1_2*.5,1e-7);near(l[i],r[i]);}
  near(t.instance.position,128/48000);
});
test('missing media pauses at the first unavailable frame instead of advancing silently', () => {
  const t=pcmTransport();t.send({type:'clear'});t.send({type:'transport',position:.5,playing:true});t.block();
  assert.equal(t.instance.playing,false);near(t.instance.position,.5);assert.ok(t.messages.some(m=>m.type==='buffering'));
});
test('loop wraps exactly at locators and continues without inserted silence', () => {
  const t=pcmTransport();t.send({type:'transport',position:10/48000,playing:true,loop:{enabled:true,start:10/48000,end:74/48000}});
  const [left]=t.block(); for(let i=0;i<64;i++)near(left[i],left[i+64],1e-7);
  const [next]=t.block(); near(left[0],next[0],1e-7); assert.equal(t.instance.playing,true);
});
test('front event owns same-track overlaps; solo/mute metadata suppresses audio', () => {
  const t=pcmTransport(); const c=t.instance.clips[0];
  t.send({type:'project',clips:[{...c,pan:0,gain:1},{...c,id:'front',sourceStart:.01,pan:-1,gain:1}],clocks:[],masterGain:1,end:2});
  t.send({type:'transport',position:0,playing:true});const [l,r]=t.block();near(l[0],(480%97/200),1e-7);near(r[0],0);
});
test('click-only project sounds only within its scope with bar accents', () => {
  const t=transport();t.send({type:'project',clips:[],clocks:[{id:'clock',start:.25,end:1,bpm:120,numerator:4,denominator:4,phase:.25}],masterGain:1,end:1});
  t.send({type:'transport',playing:true,position:0,clickEnabled:true,clickGain:.7});
  let maximum=0;for(let i=0;i<93;i++){const [l]=t.block();maximum=Math.max(maximum,...l);}near(maximum,0);
  t.send({type:'transport',position:.25,playing:true});const [l]=t.block();assert.ok(Math.max(...l)>.1);
});
