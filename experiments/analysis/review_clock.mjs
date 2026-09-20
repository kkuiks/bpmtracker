/* Musical-map review state. Audio samples and source zero are immutable. */
export const copy = value => JSON.parse(JSON.stringify(value));

function validateMeters(map, duration, checkLockedTimes) {
  const meters = map.meter_events || [], first=map.grid[0].quarter_position, last=map.grid.at(-1).quarter_position;
  for (let i = 0; i < meters.length; i++) {
    const m = meters[i];
    if (!Number.isInteger(m.quarter_position) || m.quarter_position < first || m.quarter_position > last ||
        !Number.isFinite(m.source_seconds) || m.source_seconds < 0 || m.source_seconds > duration ||
        ![2, 3, 4, 6].includes(m.numerator) || m.denominator !== 4 ||
        (i && m.quarter_position <= meters[i - 1].quarter_position)) {
      throw Error('변박은 지도 범위 안의 정수 박 위치와 원곡 시각으로 지정한 2/4·3/4·4/4·6/4를 지원합니다.');
    }
    if (checkLockedTimes && m.locked && Math.abs(timeAt(map.grid,m.quarter_position)-m.source_seconds)>1e-7) {
      throw Error('잠긴 변박의 원곡 시각과 지도가 일치하지 않습니다.');
    }
  }
}

export function validateMap(map, duration = Infinity) {
  if (!Array.isArray(map.grid) || map.grid.length < 2) throw Error('박 격자가 최소 두 개 필요합니다.');
  for (let i = 0; i < map.grid.length; i++) {
    const p = map.grid[i], prev = map.grid[i - 1];
    if (!Number.isFinite(p.quarter_position) || !Number.isFinite(p.source_seconds) ||
        p.source_seconds < 0 || p.source_seconds > duration ||
        (prev && (p.quarter_position <= prev.quarter_position || p.source_seconds <= prev.source_seconds))) {
      throw Error('시간과 박 번호는 유한한 값으로 증가하며 음원 범위 안에 있어야 합니다.');
    }
  }
  validateMeters(map,duration,true);
  return map;
}

export function timeAt(grid, q) {
  if (!Number.isFinite(q)) throw Error('박 위치를 입력하세요.');
  let lo = 0, hi = grid.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (grid[mid].quarter_position <= q) lo = mid; else hi = mid; }
  const a = grid[lo], b = grid[hi];
  return a.source_seconds + (q - a.quarter_position) *
    (b.source_seconds - a.source_seconds) / (b.quarter_position - a.quarter_position);
}

export function lockMap(map, anchors, duration = Infinity) {
  const result = copy(map);
  // A locked bar must already be supported by the chosen candidate. Generic
  // point anchors may extend its support; they cannot hide an unsupported bar.
  validateMeters(map,duration,false);
  const requested=[...anchors.filter(a=>a.locked),...(map.meter_events||[]).filter(m=>m.locked)]
    .sort((a,b)=>a.quarter_position-b.quarter_position),locks=[];
  for(const point of requested) {
    const previous=locks.at(-1);
    if(previous && point.quarter_position===previous.quarter_position) {
      if(Math.abs(point.source_seconds-previous.source_seconds)>1e-7) throw Error('같은 박의 기준점과 변박 잠금 시각이 충돌합니다.');
      continue;
    }
    locks.push(point);
  }
  for (let i = 0; i < locks.length; i++) {
    const a = locks[i], prev = locks[i - 1];
    if (!Number.isFinite(a.source_seconds) || !Number.isFinite(a.quarter_position) ||
        a.source_seconds < 0 || a.source_seconds > duration ||
        (prev && (a.quarter_position <= prev.quarter_position || a.source_seconds <= prev.source_seconds))) {
      throw Error('잠금 기준점의 박 번호와 시간 순서가 충돌합니다.');
    }
  }
  if (!locks.length) return validateMap(result, duration);
  const deltas = locks.map(a => a.source_seconds - timeAt(map.grid, a.quarter_position));
  function delta(q) {
    if (q <= locks[0].quarter_position) return deltas[0];
    for (let i = 1; i < locks.length; i++) {
      if (q <= locks[i].quarter_position) {
        const fraction = (q - locks[i-1].quarter_position) / (locks[i].quarter_position - locks[i-1].quarter_position);
        return deltas[i-1] + fraction * (deltas[i] - deltas[i-1]);
      }
    }
    return deltas.at(-1);
  }
  // Include each anchor as a mapping knot; never silently round a fractional beat.
  const qs = [...new Set([...map.grid.map(p => p.quarter_position), ...locks.map(a => a.quarter_position)])].sort((a,b) => a-b);
  result.grid = qs.map(q => ({quarter_position:q, source_seconds:timeAt(map.grid,q)+delta(q)}));
  result.meter_events=(result.meter_events||[]).map(m=>m.locked?m:{...m,source_seconds:timeAt(result.grid,m.quarter_position)});
  result.user_constrained = true;
  return validateMap(result, duration);
}

export function clickEvents(map, duration) {
  const first = Math.ceil(map.grid[0].quarter_position), last = Math.floor(map.grid.at(-1).quarter_position);
  if (last - first > 100000) throw Error('실험 도구의 최대 클릭 수를 초과했습니다.');
  const events = [];
  for (let q = first; q <= last; q++) {
    const t = timeAt(map.grid,q);
    const meter = (map.meter_events || []).filter(m => m.quarter_position <= q).at(-1);
    const accent = !!meter && Math.abs((q - meter.quarter_position) % meter.numerator) < 1e-8;
    if (t >= 0 && t < duration) events.push({quarter_position:q, source_seconds:t, accent});
  }
  return events;
}

export class ReviewSession {
  constructor(track) {
    this.track = track;
    this.state = {schema_version:1, source:copy(track.source), selected_map_id:track.maps[0].id,
      map:copy(track.maps[0]), anchors:[], revision:0, accepted:false};
    validateMap(this.state.map, track.source.duration_seconds);
    this.history = []; this.actions = []; this.startedAt = null;
  }
  begin() { if (this.startedAt === null) this.startedAt = Date.now(); }
  apply(kind, action) {
    const next = copy(this.state); action(next);
    next.map = lockMap(next.map,next.anchors,this.track.source.duration_seconds);
    this.history.push(copy(this.state)); next.revision = this.state.revision+1; next.accepted=false;
    this.state=next; this.begin();
    this.actions.push({kind, revision:next.revision, elapsed_ms:Date.now()-this.startedAt});
    return this.state;
  }
  choose(id, expectedRevision=this.state.revision) {
    if (expectedRevision !== this.state.revision) throw Error('이전 상태에서 만든 후보입니다. 현재 수정 내용을 유지합니다.');
    const map = this.track.maps.find(m => m.id===id); if (!map) throw Error('후보를 찾지 못했습니다.');
    if (map.full_song_map===false) {
      const lo=map.grid[0].source_seconds,hi=map.grid.at(-1).source_seconds;
      const locks=[...this.state.anchors,...(this.state.map.meter_events||[])].filter(p=>p.locked);
      if(locks.some(p=>p.source_seconds<lo-1e-7||p.source_seconds>hi+1e-7)) {
        throw Error('다른 구간의 잠금 기준점을 이 부분 지도로 옮길 수 없습니다. 구간 연결은 아직 미확정입니다.');
      }
    }
    return this.apply('choose_candidate', s => {
      const lockedMeters=(s.map.meter_events||[]).filter(m=>m.locked);
      s.map=copy(map); s.selected_map_id=id;
      s.map.meter_events=[...(s.map.meter_events||[]).filter(m=>!lockedMeters.some(l=>l.quarter_position===m.quarter_position)),...lockedMeters].sort((a,b)=>a.quarter_position-b.quarter_position);
    });
  }
  scale(factor) {
    if (![.5,2].includes(factor)) throw Error('지원하지 않는 배수입니다.');
    if (this.state.anchors.some(a=>a.locked) || (this.state.map.meter_events||[]).some(m=>m.locked)) {
      throw Error('박 단위를 바꾸기 전에 기준점·변박 잠금을 명시적으로 해제하세요.');
    }
    return this.apply('change_beat_unit',s=>{
      s.map.grid=s.map.grid.map(p=>({...p,quarter_position:p.quarter_position*factor}));
      s.map.meter_events=[]; s.map.label+=' · '+factor+'배';
    });
  }
  shift(seconds) {
    if (!Number.isFinite(seconds)) throw Error('이동할 시간을 입력하세요.');
    if (this.state.anchors.some(a=>a.locked) || (this.state.map.meter_events||[]).some(m=>m.locked)) throw Error('시간 이동 전에 기준점·변박 잠금을 해제하세요.');
    return this.apply('shift_phase',s=>{s.map.grid=s.map.grid.map(p=>({...p,source_seconds:p.source_seconds+seconds}));});
  }
  anchor(q,t) { return this.apply('lock_anchor',s=>{
    if(s.map.full_song_map===false && (q<s.map.grid[0].quarter_position || q>s.map.grid.at(-1).quarter_position ||
        t<s.map.grid[0].source_seconds || t>s.map.grid.at(-1).source_seconds)) throw Error('부분 지도 밖의 기준점으로 미확정 구간을 자동 연결할 수 없습니다.');
    s.anchors=s.anchors.filter(a=>a.quarter_position!==q);
    s.anchors.push({quarter_position:q,source_seconds:t,locked:true});
  }); }
  removeAnchor(q) { return this.apply('unlock_anchor',s=>{s.anchors=s.anchors.filter(a=>a.quarter_position!==q);}); }
  meter(q,numerator) { return this.apply('set_meter',s=>{
    if(!Number.isInteger(q)) throw Error('이 도구의 변박은 정수 4분음표 위치에 지정하세요.');
    if (q < s.map.grid[0].quarter_position || q > s.map.grid.at(-1).quarter_position) throw Error('변박 위치가 지도 범위를 벗어납니다.');
    s.map.meter_events=[...(s.map.meter_events||[]).filter(m=>m.quarter_position!==q),
      {quarter_position:q,source_seconds:timeAt(s.map.grid,q),numerator,denominator:4,locked:true,provenance:'user'}].sort((a,b)=>a.quarter_position-b.quarter_position);
  }); }
  removeMeter(q) { return this.apply('remove_meter',s=>{s.map.meter_events=(s.map.meter_events||[]).filter(m=>m.quarter_position!==q);}); }
  undo() {
    if (!this.history.length) return;
    const revision=this.state.revision+1; this.state=this.history.pop(); this.state.revision=revision; this.state.accepted=false;
    this.begin(); this.actions.push({kind:'undo',revision,elapsed_ms:Date.now()-this.startedAt});
  }
  export(accepted=false) {
    return {...copy(this.state),accepted,user_acceptance_only:true,
      source_audio_modified:false,actions:copy(this.actions),
      review_elapsed_ms:this.startedAt===null?0:Date.now()-this.startedAt,
      correction_action_count:this.actions.filter(a=>!['choose_candidate','undo','restore'].includes(a.kind)).length,
      candidate_application_count:this.actions.filter(a=>a.kind==='choose_candidate').length,
      undo_count:this.actions.filter(a=>a.kind==='undo').length,
      action_count_semantics:'Manual edit, candidate application and undo counts are separate; candidate review has nonzero user effort.',
      measurement_status:'human session only; elapsed time includes playback and idle time; correctness independently unverified'};
  }
  restore(saved) {
    if (saved.schema_version!==1 || saved.source?.sha256!==this.track.source.sha256 ||
        saved.source.sample_rate!==this.track.source.sample_rate || saved.source.sample_frames!==this.track.source.sample_frames ||
        saved.source.duration_seconds!==this.track.source.duration_seconds || saved.source.source_frame_offset!==0) throw Error('저장 파일의 원본 음원 정보가 일치하지 않습니다.');
    validateMap(saved.map,this.track.source.duration_seconds);
    const constrained=lockMap(saved.map,saved.anchors||[],this.track.source.duration_seconds);
    for(const a of saved.anchors||[]) if(a.locked && Math.abs(timeAt(saved.map.grid,a.quarter_position)-a.source_seconds)>1e-7) throw Error('저장된 지도와 잠금 기준점이 일치하지 않습니다.');
    this.history.push(copy(this.state));
    this.state={schema_version:1,source:copy(this.track.source),selected_map_id:saved.selected_map_id,map:constrained,
      anchors:copy(saved.anchors||[]),revision:this.state.revision+1,accepted:false};
    this.actions=copy(saved.actions||[]);
    const elapsed=Number(saved.review_elapsed_ms)||0;
    this.startedAt=Date.now()-Math.max(0,elapsed);
    this.actions.push({kind:'restore',revision:this.state.revision,elapsed_ms:Date.now()-this.startedAt});
  }
}

export function clickWav(map, source) {
  const samples=source.sample_frames, rate=source.sample_rate;
  const buffer=new ArrayBuffer(44+samples*2), view=new DataView(buffer);
  const str=(offset,value)=>{for(let i=0;i<value.length;i++)view.setUint8(offset+i,value.charCodeAt(i));};
  str(0,'RIFF');view.setUint32(4,36+samples*2,true);str(8,'WAVE');str(12,'fmt ');
  view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);
  view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,samples*2,true);
  for(const event of clickEvents(map,source.duration_seconds)) {
    const start=Math.round(event.source_seconds*rate), length=Math.round(.02*rate),frequency=event.accent?1500:1000;
    for(let i=0;i<length && start+i<samples;i++) {
      const v=.45*Math.sin(2*Math.PI*frequency*i/rate)*Math.exp(-i/(rate*.004));
      const offset=44+(start+i)*2;
      view.setInt16(offset,Math.max(-32768,Math.min(32767,view.getInt16(offset,true)+Math.round(v*32767))),true);
    }
  }
  return buffer;
}
