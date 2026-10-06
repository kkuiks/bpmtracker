const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const text=fs.readFileSync(path.join(__dirname,'../electron/main.cjs'),'utf8');
const validate=vm.runInNewContext(text.slice(text.indexOf('function validProject('),text.indexOf('async function atomicJson('))+'\nvalidProject;');
function project(){return {format:'joljak-project',version:1,id:'project',name:'Audit',sampleRate:48000,masterGain:1,clickGain:.7,assets:[{id:'01234567-89ab-4cde-8123-456789abcdef',name:'source.wav',sourcePath:'/audit/source.wav',sampleRate:48000,channels:1,frames:480000,duration:10}],tracks:[{id:'track',name:'Audio',gain:1,pan:0,mute:false,solo:false}],clips:[{id:'clip',trackId:'track',assetId:'01234567-89ab-4cde-8123-456789abcdef',start:0,sourceStart:0,duration:10}],clocks:[],analyses:[]};}
const cases=[
 ['valid audio project is accepted',p=>p,false],
 ['unknown audio reference is rejected before rendering',p=>{p.clips[0].assetId='missing';return p;},true],
 ['unknown track is rejected before rendering',p=>{p.clips[0].trackId='missing';return p;},true],
 ['source bounds cannot run past the decoded original',p=>{p.clips[0].sourceStart=9;return p;},true],
 ['invalid master settings are rejected',p=>{p.masterGain=NaN;return p;},true],
 ['duplicate asset identity is rejected',p=>{p.assets.push({...p.assets[0]});return p;},true],
];let failed=0;
for(const [name,modify,reject] of cases){try{if(reject)assert.throws(()=>validate(modify(project())));else assert.doesNotThrow(()=>validate(modify(project())));console.log('PASS',name);}catch(e){failed++;console.log('FAIL',name,e.message);}}
process.exitCode=failed?1:0;
