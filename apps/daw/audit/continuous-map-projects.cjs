/* Focused checks of the delivered native maps and the real metronome worklet. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {webcrypto,createHash}=require('node:crypto');

async function main(){
  const root=path.resolve(__dirname,'../../..');
  const run=path.resolve(process.argv[2]);
  const out=path.join(run,'native-click-checks');fs.mkdirSync(out,{recursive:true});
  global.crypto??=webcrypto;
  const {build}=await import(pathToFileURL(path.join(root,'apps/daw/node_modules/rolldown/dist/index.mjs')).href);
  await build({input:path.join(root,'apps/daw/src/music.ts'),platform:'node',output:{file:path.join(out,'music.mjs'),format:'esm'}});
  const music=await import(pathToFileURL(path.join(out,'music.mjs')).href);
  const electron=fs.readFileSync(path.join(root,'apps/daw/electron/main.cjs'),'utf8');
  const validate=vm.runInNewContext(electron.slice(electron.indexOf('function validProject('),electron.indexOf('async function atomicJson('))+'\nvalidProject;');
  const workletCode=fs.readFileSync(path.join(root,'apps/daw/public/transport-worklet.js'),'utf8');
  let Transport;
  const context=vm.createContext({sampleRate:48000,currentFrame:0,Float32Array,Map,Set,Math,
    AudioWorkletProcessor:class{constructor(){this.port={postMessage:()=>{}};}},registerProcessor:(_name,T)=>{Transport=T;}});
  vm.runInContext(workletCode,context);
  const manifest=JSON.parse(fs.readFileSync(path.join(run,'listen-projects/manifest.json'),'utf8'));
  const reports=[],fixtures=[];
  const near=(a,b,tol=1e-7)=>assert.ok(Math.abs(a-b)<tol,`${a} != ${b}`);
  function sections(mapping){
    let {bpm,numerator:n,denominator:d,bar_zero_source_seconds:at}=mapping.initial;
    let q=0,barQ=0,start=0;const result=[];
    for(const event of [...mapping.events,{time:mapping.duration_seconds}]){
      const quarter=q+(start-at)*bpm/60,barLength=n*4/d;
      const barStart=barQ+Math.floor((quarter-barQ+1e-8)/barLength)*barLength;
      if(event.time>start+1e-8)result.push({start,end:event.time,bpm,numerator:n,denominator:d,phase:start-(quarter-barStart)*60/bpm});
      if(event.quarter===undefined)break;
      at=event.time;q=event.quarter;bpm=event.bpm??bpm;
      if(event.numerator!==undefined){n=event.numerator;d=event.denominator;barQ=q;}
      start=event.time;
    }
    return result;
  }
  for(const row of manifest.rows){
    const file=path.resolve(row.project_path),raw=JSON.parse(fs.readFileSync(file,'utf8'));
    const project=music.upgradeProject(validate(raw));
    assert.deepEqual(project.clips,raw.clips);assert.equal(project.tracks.length,1);
    assert.equal(project.tracks[0].timeBase,'linear');assert.equal(project.clocks.length,0);
    assert.ok(fs.existsSync(path.resolve(path.dirname(file),project.assets[0].sourcePath)));
    const mapping=JSON.parse(fs.readFileSync(row.map_path,'utf8'));
    if(row.variant==='current'){
      const predictionPath=row.prediction_path??path.join(run,'predictions/C1_CONTINUOUS_MAP/proxy100',row.id+'.json');
      assert.deepEqual(mapping,JSON.parse(fs.readFileSync(predictionPath,'utf8')));
    }
    const origin=project.clips[0].start,clocks=music.projectClocks(project);
    const actual=clocks.filter(c=>c.end>origin+1e-8&&c.start<origin+row.source_duration_seconds-1e-8)
      .map(c=>({...c,start:Math.max(0,c.start-origin),end:Math.min(row.source_duration_seconds,c.end-origin),phase:c.phase-origin}));
    const expected=sections(mapping);assert.equal(actual.length,expected.length);
    const ticks=[];
    for(let i=0;i<actual.length;i++){
      const a=actual[i],e=expected[i];
      for(const key of ['bpm','numerator','denominator','start','end'])near(a[key],e[key]);
      const bar=60/a.bpm*4/a.denominator*a.numerator;
      near(((a.phase-e.phase+bar/2)%bar+bar)%bar-bar/2,0);
      const step=60/e.bpm*4/e.denominator;
      const first=Math.ceil((e.start-e.phase-1e-8)/step),last=Math.ceil((e.end-e.phase-1e-8)/step);
      for(let beat=first;beat<last;beat++)ticks.push({time:origin+e.phase+beat*step,strong:((beat%e.numerator)+e.numerator)%e.numerator===0});
    }
    const transport=new Transport();
    transport.port.onmessage({data:{type:'project',clips:[],clocks,masterGain:1,end:project.projectDuration}});
    assert.equal(transport.referenceEvents,null);
    let maximumError=0;
    for(const tick of ticks){
      const start=tick.time-2/48000;
      transport.port.onmessage({data:{type:'transport',position:start,playing:true,clickEnabled:true,clickGain:1}});
      const output=[new Float32Array(128),new Float32Array(128)];transport.process([],[output]);context.currentFrame+=128;
      for(let frame=3;frame<64;frame++){
        const age=(frame-2)/48000;
        const tone=Math.sin(2*Math.PI*(tick.strong?1600:1050)*age)*Math.exp(-age/.006)*(tick.strong?.32:.20);
        const error=Math.abs(output[0][frame]-tone);maximumError=Math.max(maximumError,error);
        assert.ok(error<1e-5,`${row.id} ${row.variant} click differs at ${tick.time}: ${error}`);
        assert.equal(output[0][frame],output[1][frame]);
      }
    }
    fixtures.push({name:row.id+'-'+row.variant,project,renderer_clocks:clocks});
    reports.push({id:row.id,variant:row.variant,project_validator_passed:true,serialized_prediction_preserved:true,
      actual_renderer_geometry_matches_map:true,actual_worklet_clicks_checked:ticks.length,
      maximum_worklet_sample_error:maximumError,no_reference_preview_bypass:true,no_click_audio_tracks:true,source_file_exists:true});
  }
  const result={all_pass:true,rows:reports,actual_native_map_and_worklet_test:true,
    audio_media_decode_not_tested:true,windows_GUI_and_loudspeaker_playback_not_tested:true};
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2)+'\n');
  fs.writeFileSync(path.join(out,'fixtures.json'),JSON.stringify(fixtures,null,2)+'\n');
  console.log('NATIVE_MAP_AND_WORKLET',reports.length,'PROJECTS',reports.reduce((a,r)=>a+r.actual_worklet_clicks_checked,0),'CLICKS PASS');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
