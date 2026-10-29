/* Beat-level declarations, explicit short bars and their editable source remain one history edit. */
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { stripTypeScriptTypes } = require('node:module');
const app = path.resolve(__dirname, '..'), generated = fs.mkdtempSync(path.join(os.tmpdir(), 'bpmtracker-signatures-'));
for (const name of ['model', 'music', 'analysis-map', 'click-level', 'history', 'arrangement']) {
  const source = stripTypeScriptTypes(fs.readFileSync(path.join(app, 'src', name + '.ts'), 'utf8'), { mode: 'transform' });
  fs.writeFileSync(path.join(generated, name + '.mjs'), source.replace(/from "\.\/([^".]+)"/g, 'from "./$1.mjs"'));
}
const copy = value => JSON.parse(JSON.stringify(value));
function seconds(project, quarter) {
  let at = 0, result = 0, bpm = project.bpm;
  for (const point of [...project.tempos].sort((a,b) => a.quarter-b.quarter)) {
    if (point.quarter > quarter) break;
    result += (point.quarter-at)*60/bpm;at=point.quarter;bpm=point.bpm;
  }
  return result+(quarter-at)*60/bpm;
}
(async () => {
  const model = await import(pathToFileURL(path.join(generated, 'model.mjs')));
  const music = await import(pathToFileURL(path.join(generated, 'music.mjs')));
  const arrangement = await import(pathToFileURL(path.join(generated, 'arrangement.mjs')));
  const { ProjectHistory } = await import(pathToFileURL(path.join(generated, 'history.mjs')));
  const rows = [], fixtures = [];
  const base = () => ({ ...model.createProject(), projectDuration: 30 });
  const point = (id, quarter, numerator=3, denominator=4) => ({id,quarter,bar:1,numerator,denominator,origin:'manual'});
  const shape = p => p.signatures.map(s => [s.quarter,s.numerator,s.denominator,!!s.shortBar]);
  function verify(name, raw, result) {
    const endQuarter = 48, end = seconds(result,endQuarter);
    const declarations = music.signatureDeclarations(raw).sort((a,b) => a.quarter-b.quarter);
    const regions = declarations[0]?.quarter === 0 ? declarations : [{quarter:0,...raw.signature},...declarations];
    const expected = [];
    for (let i=0;i<regions.length;i++) {
      const region = regions[i], until = Math.min(endQuarter,regions[i+1]?.quarter??endQuarter), step = 4/region.denominator;
      for (let q=region.quarter,beat=0;q<until-1e-8;q+=step,beat++)
        expected.push({time:seconds(raw,q),strong:beat%region.numerator===0});
    }
    const actual = [];
    for (const clock of music.projectClocks(result,end)) {
      const step = 60/clock.bpm*4/clock.denominator;
      const first = Math.ceil((clock.start-clock.phase-1e-8)/step);
      for (let beat=first,time=clock.phase+first*step;time<clock.end-1e-8;beat++,time=clock.phase+beat*step)
        actual.push({time,strong:beat%clock.numerator===0});
    }
    assert.equal(actual.length,expected.length,name+' beat count');
    actual.forEach((beat,i) => { assert.ok(Math.abs(beat.time-expected[i].time)<1e-8,name+' beat time');assert.equal(beat.strong,expected[i].strong,name+' emphasis'); });
    const reopened = music.upgradeProject(copy(result));
    assert.deepEqual(reopened.signatures,result.signatures,name+' reopen');
    assert.deepEqual(music.editMapAtTimes(result).signatures,result.signatures,name+' recalculation is stable');
    rows.push({name,passed:true});fixtures.push({id:name,project:result,from:0,to:end,expectedBeats:expected});
  }
  const first = music.putSignature(base(),point('new',2));
  assert.deepEqual(shape(first),[[0,2,4,true],[2,3,4,false]]);
  assert.equal(music.positionAtQuarter(first,2).bar,2);
  verify('third beat produces a 2/4 bar', {...base(),signatures:[point('new',2)]},first);
  const later = music.putSignature(base(),point('later',10));
  assert.deepEqual(shape(later),[[8,2,4,true],[10,3,4,false]]);
  assert.equal(music.positionAtQuarter(later,10).bar,4);
  verify('earlier full bars stay 4/4', {...base(),signatures:[point('later',10)]},later);
  const eighth = {...base(),signature:{numerator:6,denominator:8}};
  const compound = music.putSignature(eighth,point('compound',1.5,5,4));
  assert.deepEqual(shape(compound),[[0,3,8,true],[1.5,5,4,false]]);
  verify('compound meter keeps its eighth-note pulse',{...eighth,signatures:[point('compound',1.5,5,4)]},compound);
  const original = music.editProjectMap({...base(),signatures:[point('original',0,4,4)]});
  const overwritten = music.putSignature(original,point('change',2));
  assert.deepEqual(overwritten.signatures[0].shortBar.original,{numerator:4,denominator:4});
  assert.equal(overwritten.signatures[0].id,'original');
  verify('an existing declaration retains its requested value',{...original,signatures:[...original.signatures,point('change',2)]},overwritten);
  const removed = music.removeMapEvents(overwritten,[{kind:'signature',id:'change'}]);
  assert.deepEqual(removed.signatures,original.signatures);
  verify('delete restores the original declaration',original,removed);
  const changed = music.putSignature(overwritten,point('change',2,5,8));
  assert.deepEqual(shape(changed),[[0,2,4,true],[2,5,8,false]]);
  verify('editing a declaration retains its preceding short bar',{...original,signatures:[...original.signatures,point('change',2,5,8)]},changed);
  const moved = arrangement.moveArrangement(overwritten,{clips:[],maps:[{kind:'signature',id:'change'}]},.5,false);
  assert.deepEqual(shape(moved),[[0,3,4,true],[3,3,4,false]]);
  verify('move recomputes 2/4 as 3/4',{...original,signatures:[...original.signatures,point('change',3)]},moved);
  const downbeat = arrangement.moveArrangement(overwritten,{clips:[],maps:[{kind:'signature',id:'change'}]},1,false);
  assert.deepEqual(shape(downbeat),[[0,4,4,false],[4,3,4,false]]);
  verify('move to downbeat removes the correction',{...original,signatures:[...original.signatures,point('change',4)]},downbeat);
  const chain = music.putSignature(first,point('second',3,5,4));
  assert.deepEqual(shape(chain),[[0,2,4,true],[2,1,4,true],[3,5,4,false]]);
  assert.deepEqual(music.signatureDeclarations(chain).map(s=>[s.id,s.numerator]),[['new',3],['second',5]]);
  verify('multiple nearby changes keep their source declarations',{...base(),signatures:[point('new',2),point('second',3,5,4)]},chain);
  const unchained = music.removeMapEvents(chain,[{kind:'signature',id:'second'}]);
  assert.deepEqual(unchained.signatures,first.signatures);
  verify('delete the next change restores the preceding request',{...base(),signatures:[point('new',2)]},unchained);
  const history = new ProjectHistory(original);history.commit(overwritten,'Declare signature');
  assert.deepEqual(copy(history.undo()),copy(original));assert.deepEqual(copy(history.redo()),copy(overwritten));
  rows.push({name:'declaration and automatic correction undo atomically',passed:true});
  const following = music.removeMapEvents(music.editProjectMap({...base(),signatures:[point('initial',0,4,4),point('next',8,3,4)]}),[{kind:'signature',id:'initial'}]);
  const inherited = music.putSignature(following,point('earlier',4,5,4));
  assert.deepEqual(inherited.signature,{numerator:5,denominator:4});
  const inheritedEdit = music.putSignature(inherited,point('earlier',4,6,8));
  assert.deepEqual(inheritedEdit.signature,{numerator:6,denominator:8});
  rows.push({name:'initial following uses declarations rather than calculated bars',passed:true});
  assert.deepEqual(music.parseTimeSignature(' 7 / 8 '),{numerator:7,denominator:8});
  for(const invalid of ['','4','0/4','33/4','3/3','2.5/4','3/64','4/4/4'])assert.equal(music.parseTimeSignature(invalid),null);
  rows.push({name:'typed signatures validate both parts',passed:true});
  const output = process.argv.indexOf('--output');
  const report = {passed:rows.length,total:rows.length,rows,fixtures};
  if(output>=0)fs.writeFileSync(process.argv[output+1],JSON.stringify(report,null,2));
  console.log(JSON.stringify({passed:rows.length,total:rows.length,rows}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;}).finally(()=>fs.rmSync(generated,{recursive:true,force:true}));
