/* Owner-authorized continuity, partial-bar and legacy compatibility checks. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { webcrypto } = require('node:crypto');

async function main() {
  const root = path.resolve(__dirname, '../../..');
  const out = path.join(root, 'data/research/design-reviews/20261011-continuous-beat-map-v1/implementation-checks');
  fs.mkdirSync(out, { recursive: true });
  global.crypto ??= webcrypto;
  const { build } = await import(pathToFileURL(path.join(root, 'apps/daw/node_modules/rolldown/dist/index.mjs')).href);
  await build({ input: path.join(root, 'apps/daw/src/music.ts'), platform: 'node',
    output: { file: path.join(out, 'music.mjs'), format: 'esm' } });
  await build({ input: path.join(root, 'apps/daw/src/arrangement.ts'), platform: 'node',
    output: { file: path.join(out, 'arrangement.mjs'), format: 'esm' } });
  const music = await import(pathToFileURL(path.join(out, 'music.mjs')).href);
  const arrangement = await import(pathToFileURL(path.join(out, 'arrangement.mjs')).href);
  const electron = fs.readFileSync(path.join(root, 'apps/daw/electron/main.cjs'), 'utf8');
  const validator = electron.slice(electron.indexOf('function validProject('), electron.indexOf('async function atomicJson('));
  const validate = vm.runInNewContext(validator + '\nvalidProject;');
  const base = { format: 'joljak-project', version: 3, id: 'test', name: 'continuity control',
    assets: [], tracks: [], clips: [], clocks: [], analyses: [], sampleRate: 48000,
    masterGain: 1, clickGain: 1, bpm: 120, signature: { numerator: 4, denominator: 4 },
    tempos: [], signatures: [], projectDuration: 12, rulerFormat: 'bars', timingPolicy: 'persistent' };
  const checks = [], fixtures = [];
  function check(name, action) { action(); checks.push({ name, pass: true }); }
  function close(a,b) { assert.ok(Math.abs(a-b)<1e-8, `${a} != ${b}`); }
  const partial = music.putSignature(base, { id: 'partial', quarter: 2, bar: 1, numerator: 3, denominator: 4, origin: 'manual' });
  check('signature_inside_old_bar_shares_its_old_beat', () => {
    close(music.timeAtBar(partial, 2), 1);
    assert.equal(music.positionAtQuarter(partial, 1).bar, 1);
    assert.equal(music.positionAtQuarter(partial, 2).bar, 2);
    close(music.quarterAtBar(partial, 3), 5);
    assert.equal(music.parseMusicalTime(partial, '1.3.1.0'), null);
    validate(partial);
  });
  check('signature_between_old_beats_is_rejected', () => {
    assert.throws(() => music.putSignature(base, { id: 'bad', quarter: 1.25, bar: 1, numerator: 3, denominator: 4, origin: 'manual' }), /beat boundary/);
  });
  const compound = { ...base, signature: { numerator: 6, denominator: 8 } };
  const compoundChange = music.putSignature(compound, { id: 'compound', quarter: 1.5, bar: 1, numerator: 4, denominator: 4, origin: 'manual' });
  check('compound_eighth_boundary_can_start_new_signature', () => {
    close(music.timeAtBar(compoundChange, 2), .75);
    assert.equal(music.positionAtQuarter(compoundChange, 1).signature.denominator, 8);
    assert.equal(music.positionAtQuarter(compoundChange, 1.5).signature.denominator, 4);
  });
  const tempo = music.putTempo(base, { id: 'tempo', quarter: 2, bpm: 150, origin: 'manual' });
  check('tempo_change_retains_shared_beat_and_new_interval', () => {
    close(music.timeAtQuarter(tempo, 2), 1);
    close(music.timeAtQuarter(tempo, 3), 1.4);
    const clocks = music.projectClocks(tempo);
    const c = clocks.find(c => c.start === 1);
    close((1-c.phase)/(60/c.bpm), 2);
  });
  check('unchanged_tempo_cannot_move_click_phase', () => {
    const unchanged=music.putTempo(base,{id:'same',quarter:2,bpm:120,origin:'manual'});
    for(const c of music.projectClocks(unchanged)) close(c.phase,0);
  });
  check('signature_move_supports_an_existing_beat_inside_a_bar', () => {
    const moved=arrangement.moveArrangement(partial,{clips:[],maps:[{kind:'signature',id:'partial'}]},.5,false);
    close(moved.signatures[0].quarter,3);close(music.timeAtBar(moved,2),1.5);
  });
  check('signature_move_rejects_nonbeat_translation', () => {
    assert.throws(()=>arrangement.moveArrangement(partial,{clips:[],maps:[{kind:'signature',id:'partial'}]},.125,false),/beat boundary/);
  });
  const legacy = { ...base, version: 2, signatures: [
    {id:'oldA',bar:3,numerator:3,denominator:4,origin:'manual'},
    {id:'oldB',bar:6,numerator:6,denominator:8,origin:'manual'}] };
  const migrated = music.upgradeProject(legacy);
  check('legacy_bar_positions_migrate_without_timing_changes', () => {
    assert.equal(migrated.version,3);
    assert.deepEqual(music.projectClocks(migrated),music.projectClocks(legacy));
    close(migrated.signatures[0].quarter,8);close(migrated.signatures[1].quarter,17);
    validate(migrated);
  });
  check('native_v3_json_roundtrip_preserves_partial_map', () => {
    const restored=music.upgradeProject(validate(JSON.parse(JSON.stringify(partial))));
    assert.deepEqual(music.projectClocks(restored),music.projectClocks(partial));
  });
  const nativeFile=path.join(root,'data/samples/ntm/acle-kahney-tesseract-juno/registered/owner-approved-project-20261011-v1.joljak');
  if(fs.existsSync(nativeFile)) check('saved_owner_juno_project_keeps_audio_and_clock_geometry',()=>{
    const old=JSON.parse(fs.readFileSync(nativeFile,'utf8')),next=music.upgradeProject(old);
    assert.deepEqual(next.clips,old.clips);assert.deepEqual(next.assets,old.assets);
    assert.deepEqual(music.projectClocks(next),music.projectClocks(old));validate(next);
  });
  for(const [name,p] of [['partial',partial],['compound',compoundChange],['tempo',tempo],['legacy',legacy],['migrated',migrated]])
    fixtures.push({name,project:p,renderer_clocks:music.projectClocks(p)});
  fs.writeFileSync(path.join(out,'fixtures.json'),JSON.stringify(fixtures,null,2)+'\n');
  fs.writeFileSync(path.join(out,'renderer-checks.json'),JSON.stringify({checks,all_pass:true,native_windows_playback_not_tested:true},null,2)+'\n');
  console.log('CONTINUOUS_MAP_CHECKS',checks.length,'PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
