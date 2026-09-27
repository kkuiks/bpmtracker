import test from 'node:test';
import assert from 'node:assert/strict';
import {ReviewSession,timeAt,clickEvents,clickWav,lockMap} from './review_clock.mjs';
const track=()=>({source:{sha256:'fixture',sample_rate:1000,sample_frames:12000,duration_seconds:12,source_frame_offset:0},
  maps:[{id:'a',grid:Array.from({length:20},(_,q)=>({quarter_position:q,source_seconds:1+q*.5})),meter_events:[]},
    {id:'b',grid:Array.from({length:20},(_,q)=>({quarter_position:q,source_seconds:1.1+q*.5})),meter_events:[]}]});
test('disjoint partial regions cannot rebase locked musical origins',()=>{
 const t=track();t.maps.push({id:'partial',full_song_map:false,grid:[{quarter_position:0,source_seconds:8},{quarter_position:4,source_seconds:10}],meter_events:[]});
 const s=new ReviewSession(t);s.anchor(2,2);const before=JSON.stringify(s.state);
 assert.throws(()=>s.choose('partial'));assert.equal(JSON.stringify(s.state),before);
 s.removeAnchor(2);s.choose('partial');assert.throws(()=>s.anchor(-1,1));
 assert.equal(s.state.map.grid[0].source_seconds,8);
});
test('anchors persist across candidate changes; source and old proposal remain unchanged',()=>{
 const t=track(),before=JSON.stringify(t),s=new ReviewSession(t);s.anchor(4,3.02);s.anchor(10,6.01);s.meter(4,2);s.choose('b');
 assert.equal(timeAt(s.state.map.grid,4),3.02);assert.equal(timeAt(s.state.map.grid,10),6.01);
 assert.equal(s.state.map.meter_events[0].numerator,2);assert.equal(JSON.stringify(t),before);
 assert.throws(()=>s.scale(2));assert.throws(()=>s.choose('a',0));
});
test('conflicting anchors fail atomically and undo restores the previous valid map',()=>{
 const s=new ReviewSession(track());s.anchor(4,3);const before=JSON.stringify(s.state);
 assert.throws(()=>s.anchor(5,2.9));assert.equal(JSON.stringify(s.state),before);
 s.anchor(8,5.02);s.undo();assert.equal(s.state.anchors.length,1);assert.equal(timeAt(s.state.map.grid,8),5);
});
test('fractional anchor retained without rounding; negative timeline rejected',()=>{
 const s=new ReviewSession(track());s.anchor(4.5,3.26);assert.equal(timeAt(s.state.map.grid,4.5),3.26);
 assert.throws(()=>lockMap(track().maps[0],[{quarter_position:10,source_seconds:.1,locked:true}],12));
});
test('meter changes affect accents without moving pulse times',()=>{
 const s=new ReviewSession(track()),before=JSON.stringify(s.state.map.grid);s.meter(0,4);s.meter(4,2);s.meter(6,4);
 assert.deepEqual(clickEvents(s.state.map,12).filter(e=>e.accent).slice(0,4).map(e=>e.quarter_position),[0,4,6,10]);
 assert.equal(JSON.stringify(s.state.map.grid),before);
});
test('save/reopen identity and locks checked; user acceptance not machine accuracy',()=>{
 const s=new ReviewSession(track());s.anchor(4,3.01);const saved=s.export(true),restored=new ReviewSession(track());restored.restore(saved);
 assert.deepEqual(restored.state.map.grid,s.state.map.grid);assert.equal(restored.state.accepted,false);
 assert.equal(saved.source_audio_modified,false);assert.equal(saved.user_acceptance_only,true);
 assert.throws(()=>restored.restore({...saved,source:{...saved.source,sha256:'other'}}));
 const tampered=structuredClone(saved);tampered.anchors[0].source_seconds+=.1;assert.throws(()=>restored.restore(tampered));
});
test('click export has exact original duration/rate with no samples before first beat',()=>{
 const t=track();t.source.sample_rate=16000;t.source.sample_frames=192000;
 const v=new DataView(clickWav(t.maps[0],t.source));assert.equal(v.byteLength,384044);
 assert.equal(v.getUint32(24,true),16000);assert.equal(v.getUint32(40,true),384000);
 assert.equal(new Uint8Array(v.buffer,44,32000).some(x=>x!==0),false);
 assert.equal(new Uint8Array(v.buffer,32044,640).some(x=>x!==0),true);
});
test('locked meter preserves source time and quarter across a differently timed candidate',()=>{
 const t=track();t.maps[1].grid=t.maps[1].grid.map(p=>({...p,source_seconds:1.2+p.quarter_position*.48}));
 const original=JSON.stringify(t),s=new ReviewSession(t);s.meter(4,2);s.meter(6,4);
 const locked=structuredClone(s.state.map.meter_events);s.choose('b');
 for(const m of locked){assert.equal(timeAt(s.state.map.grid,m.quarter_position),m.source_seconds);}
 assert.deepEqual(s.state.map.meter_events,locked);assert.equal(JSON.stringify(t),original);
 assert.throws(()=>s.shift(.02));
 s.undo();assert.deepEqual(s.state.map.meter_events,locked);
});
test('candidate with insufficient quarter support cannot silently drop a locked meter',()=>{
 const t=track();t.maps[1].grid=t.maps[1].grid.slice(0,10);
 const s=new ReviewSession(t);s.meter(16,3);const before=JSON.stringify(s.state);
 assert.throws(()=>s.choose('b'));assert.equal(JSON.stringify(s.state),before);
});
test('fractional meters are rejected and conflicting point and meter locks are atomic',()=>{
 const s=new ReviewSession(track());assert.throws(()=>s.meter(.5,4));s.meter(4,2);
 const before=JSON.stringify(s.state);assert.throws(()=>s.anchor(4,3.1));assert.equal(JSON.stringify(s.state),before);
 s.anchor(4,3);s.choose('b');assert.equal(timeAt(s.state.map.grid,4),3);
 assert.equal(clickEvents(s.state.map,12).find(e=>e.quarter_position===4).accent,true);
});
test('restoring a mismatched locked meter source time fails without repairing or mutating state',()=>{
 const s=new ReviewSession(track());s.meter(4,2);const good=s.export(),restored=new ReviewSession(track());
 restored.restore(good);assert.equal(timeAt(restored.state.map.grid,4),3);
 const before=JSON.stringify(restored.state),bad=structuredClone(good);bad.map.meter_events[0].source_seconds+=.1;
 assert.throws(()=>restored.restore(bad));assert.equal(JSON.stringify(restored.state),before);
 const fractional=structuredClone(good);fractional.map.meter_events[0].quarter_position=4.5;
 assert.throws(()=>restored.restore(fractional));assert.equal(JSON.stringify(restored.state),before);
});
