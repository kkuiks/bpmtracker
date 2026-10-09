"use strict";

const $ = id => document.getElementById(id);
const checks = ["listened", "tempo", "meter", "alignment", "coverage"];
const verdicts = {unreviewed:"미판정", valid:"유효", redundant:"중복 선언", context:"원본 문맥", needs_correction:"수정 필요", unknown:"미확인"};
const labels = {draft:"검토 중", confirmed_current_scope:"이번 검토 완료", needs_correction:"수정 필요", insufficient_evidence:"자료·판단 부족", candidate_reviewed:"후보 검토 기록", unreviewed:"이번 검토 전", stale:"지도 버전 변경"};
const state = {index:null, records:{}, token:null, packet:null, generation:0, context:null, music:null, clicks:null, musicGain:null, clickGain:null, sources:[],
  playing:false, loading:false, position:0, startedAt:0, startPosition:0, loop:false, loopStart:0, loopEnd:10, offset:0, controller:null,
  decisions:{}, played:[], lastObserved:null, peaks:null, saveTimer:null, saveChain:Promise.resolve(), dirty:false, editVersion:0, lastDraw:0};

function time(t, decimals=true) {
  const sign=t<0?"−":"";
  const n=Math.round(Math.abs(t)*1000), minutes=Math.floor(n/60000), seconds=Math.floor(n/1000)%60;
  return sign+minutes+":"+String(seconds).padStart(2,"0")+(decimals?"."+String(n%1000).padStart(3,"0"):"");
}
function number(n){return Number(n).toPrecision(15).replace(/(\.\d*?[1-9])0+(?=$|e)/,"$1").replace(/\.0+(?=$|e)/,"");}
function status(id,message,kind=""){ $(id).textContent=message;$(id).className="status"+(kind?" "+kind:""); }
function recordStatus(row){if(state.packet?.id===row.id&&state.dirty)return "draft";const r=state.records[row.id];return !r?"unreviewed":r.reference_sha256!==row.reference_sha256?"stale":r.status;}
function reviewRecorded(row){const s=recordStatus(row);return row.group==="candidate"?["candidate_reviewed","needs_correction","insufficient_evidence"].includes(s):s==="confirmed_current_scope";}
function updateProgress(){
  const group=$("group").value, tracks=state.index.tracks.filter(t=>t.group===group), completed=tracks.filter(reviewRecorded).length;
  $("progress").textContent=group==="candidate"?`후보 검토 ${completed} / ${tracks.length} 기록`:`이번 ${group==="auxiliary"?"보조 표본 검토":"재검증"} ${completed} / ${tracks.length} 완료`;
  for(const o of $("group").options){const names={formal:"정식 표본",auxiliary:"보조 표본",candidate:"미승인 후보"};o.textContent=`${names[o.value]} · ${state.index.counts[o.value]}개`;o.disabled=!state.index.counts[o.value];}
  if(state.packet){const row=state.index.tracks.find(t=>t.id===state.packet.id), s=recordStatus(row);$("review-state").textContent=labels[s];$("review-state").className="chip"+(s==="confirmed_current_scope"?" complete":"");}
}
function filteredTracks(){
  const term=$("search").value.trim().toLowerCase(), group=$("group").value, filter=$("filter").value;
  return state.index.tracks.filter(t=>{
    const s=recordStatus(t);
    return t.group===group&&t.title.toLowerCase().includes(term)&&(filter==="all"||filter==="unreviewed"&&!reviewRecorded(t)||filter==="attention"&&t.attention_count>0||filter==="confirmed"&&reviewRecorded(t)||filter==="needs"&&["needs_correction","insufficient_evidence"].includes(s));
  });
}
function renderList(){
  const rows=filteredTracks();$("track-list").replaceChildren();$("list-count").textContent=`${rows.length}개 표시`;
  for(const row of rows){
    const b=document.createElement("button");b.className="track-button"+(row.id===state.packet?.id?" active":"");
    const name=document.createElement("span");name.className="track-name";name.textContent=row.title;
    const meta=document.createElement("span");meta.className="track-meta";
    const label=document.createElement("span"),s=recordStatus(row);label.textContent=labels[s];label.className=s==="confirmed_current_scope"?"complete":["needs_correction","insufficient_evidence"].includes(s)?"problem":"pending";
    const info=document.createElement("span");info.textContent=time(row.duration_seconds,false)+(row.attention_count?` · 점검 ${row.attention_count}`:"");meta.append(label,info);b.append(name,meta);b.onclick=()=>selectTrack(row.id).catch(e=>status("save-status",e.message,"error"));$("track-list").append(b);
  }
}

function currentPosition(){
  if(!state.playing)return state.position;
  const raw=state.startPosition+Math.max(0,state.context.currentTime-state.startedAt);
  if(state.loop&&raw>=state.loopEnd)return state.loopStart+(raw-state.loopStart)%(state.loopEnd-state.loopStart);
  return Math.min(raw,state.packet.duration_seconds);
}
function mergeIntervals(values){
  const sorted=values.filter(([a,b])=>b>a).sort((a,b)=>a[0]-b[0]), out=[];
  for(const [a,b] of sorted){const last=out.at(-1);if(last&&a<=last[1]+.05)last[1]=Math.max(last[1],b);else out.push([a,b]);}
  return out;
}
function observePlayback(){
  if(!state.playing)return;
  const now=currentPosition(), ctx=state.context.currentTime;
  if(state.lastObserved&&Number($("music-gain").value)>0&&ctx>=state.startedAt){
    const elapsed=ctx-state.lastObserved.ctx;
    if(now>=state.lastObserved.time&&now-state.lastObserved.time<=elapsed+.05)state.played=mergeIntervals([...state.played,[state.lastObserved.time,now]]);
    else if(state.loop&&now<state.lastObserved.time)state.played=mergeIntervals([...state.played,[state.lastObserved.time,state.loopEnd],[state.loopStart,now]]);
  }
  state.lastObserved={ctx,time:now};
}
function stopSources(){for(const s of state.sources){s.onended=null;try{s.stop();}catch{}s.disconnect();}state.sources=[];}
function pause(){if(state.playing)observePlayback();state.position=currentPosition();state.playing=false;state.lastObserved=null;stopSources();$("play").textContent="재생";updatePlayed();}
function setGains(){
  if(!state.context)return;
  state.musicGain.gain.setTargetAtTime(Number($("music-gain").value),state.context.currentTime,.01);
  state.clickGain.gain.setTargetAtTime($("click-enabled").checked?Number($("click-gain").value):0,state.context.currentTime,.01);
}
function ensureContext(){
  if(!state.context){const Constructor=window.AudioContext||window.webkitAudioContext;if(!Constructor)throw Error("이 브라우저에서는 동기화 오디오 재생을 지원하지 않습니다.");state.context=new Constructor({sampleRate:state.packet.sample_rate});state.musicGain=state.context.createGain();state.clickGain=state.context.createGain();state.musicGain.connect(state.context.destination);state.clickGain.connect(state.context.destination);setGains();}
  return state.context;
}
function makeClicks(){
  if(!state.music)return;
  const rate=state.context.sampleRate, buffer=state.context.createBuffer(1,state.music.length,rate), samples=buffer.getChannelData(0), shift=state.offset/1000;
  const mode=state.packet.click_modes.find(m=>m.id===$("click-mode").value)||state.packet.click_modes[0];
  const accents=$("accent").checked, barFrames=new Set(state.packet.bars.map(t=>Math.round((t+shift)*rate)));
  const tone=(at,accented)=>{const start=Math.round((at+shift)*rate), length=Math.round(rate*.022), freq=accented?2200:1400, amp=accented?.4:.24;
    for(let i=0;i<length;i++){const target=start+i;if(target<0||target>=samples.length)continue;const t=i/rate;samples[target]+=amp*Math.min(1,i/(rate*.0005))*Math.exp(-210*t)*Math.cos(2*Math.PI*freq*t);}};
  for(const t of mode.times)if(!(accents&&barFrames.has(Math.round((t+shift)*rate))))tone(t,false);
  if(accents)for(const t of state.packet.bars)tone(t,true);
  state.clicks=buffer;
}
function start(){
  if(!state.music||!state.clicks)return;
  stopSources();if(state.position>=state.music.duration-.001)state.position=state.loop?state.loopStart:0;
  if(state.loop&&(state.position<state.loopStart||state.position>=state.loopEnd))state.position=state.loopStart;
  const when=state.context.currentTime+.06;
  const music=state.context.createBufferSource(), click=state.context.createBufferSource();music.buffer=state.music;click.buffer=state.clicks;
  for(const s of [music,click]){s.loop=state.loop;s.loopStart=state.loopStart;s.loopEnd=state.loopEnd;}
  music.connect(state.musicGain);click.connect(state.clickGain);state.sources=[music,click];state.startPosition=state.position;state.startedAt=when;state.playing=true;state.lastObserved=null;
  music.onended=()=>{if(state.sources[0]!==music||state.loop)return;pause();state.position=state.packet.duration_seconds;updateTransport();scheduleSave(false);};
  music.start(when,state.position);click.start(when,state.position);$("play").textContent="일시정지";
}
function makePeaks(){
  const channels=Array.from({length:state.music.numberOfChannels},(_,i)=>state.music.getChannelData(i)), size=512, length=Math.ceil(state.music.length/size), peaks=new Float32Array(length);
  for(let n=0;n<length;n++){let high=0;for(let k=n*size;k<Math.min((n+1)*size,state.music.length);k+=4)for(const ch of channels)high=Math.max(high,Math.abs(ch[k]));peaks[n]=high;}
  state.peaks={values:peaks,secondsPerPeak:size/state.music.sampleRate};
}
async function loadAudio(){
  const gen=state.generation,p=state.packet,context=ensureContext();await context.resume();if(gen!==state.generation)return false;
  state.loading=true;state.controller=new AbortController();$("play").disabled=true;
  status("player-status",`원음 불러오는 중 · ${(p.audio_bytes/1e6).toFixed(1)} MB`);
  try{const r=await fetch(p.audio_url,{signal:state.controller.signal});if(!r.ok){let message=`음원을 불러오지 못했습니다 (${r.status}).`;if(r.status===409)message=(await r.json()).error;throw Error(message);}const bytes=await r.arrayBuffer();if(gen!==state.generation)return false;status("player-status","원음 재생 준비 중…");const music=await context.decodeAudioData(bytes);if(gen!==state.generation)return false;state.music=music;makeClicks();makePeaks();status("player-status","음원과 클릭이 같은 오디오 시계로 준비되었습니다.");return true;
  }catch(e){if(gen===state.generation&&e.name!=="AbortError")status("player-status",e.message,"error");return false;}
  finally{if(gen===state.generation){state.loading=false;state.controller=null;$("play").disabled=false;}}
}
async function togglePlay(){
  if(state.loading||!state.packet)return;
  if(state.playing){pause();scheduleSave(false);return;}
  const gen=state.generation;try{if(!state.music&&!(await loadAudio()))return;await ensureContext().resume();if(gen===state.generation)start();}catch(e){status("player-status",e.message,"error");}
}
function seek(value){if(!state.packet)return;const resume=state.playing;pause();state.position=Math.max(0,Math.min(state.packet.duration_seconds,Number(value)));updateTransport();if(resume)start();}
function reconfigure(){const resume=state.playing;pause();state.clicks=null;makeClicks();if(resume)start();updateTransport();}
function setOffset(value){if(!Number.isFinite(value)||Math.abs(value)>600000)return;state.offset=value;$("offset").value=String(value);reconfigure();markDirty();updateOffset();}
function updateOffset(){const p=state.packet;if(!p)return;const base=p.stored_offset_seconds;$("offset-note").textContent=(base===null?"기록된 프로젝트→음원 오프셋 없음":`${p.group==="candidate"?"미확정 시작 제안":"저장된 프로젝트→음원 오프셋"}: ${(base*1000).toFixed(4)} ms`)+` · 현재 지도에 추가한 비교 이동: ${state.offset.toFixed(4)} ms`;}
function renderOffsetOptions(){
  const p=state.packet, container=$("candidate-offset-options");container.replaceChildren();
  if(p.group!=="candidate"||!p.available_map)return;
  const base=p.stored_offset_seconds;
  for(const option of [{label:"원본 시계 · 0 ms",offset_seconds:0},...p.candidate_offset_options]){
    const button=document.createElement("button");button.textContent=option.offset_seconds===0?option.label:`${option.label} · ${(option.offset_seconds*1000).toFixed(4)} ms`;
    button.onclick=()=>setOffset((option.offset_seconds-base)*1000);container.append(button);
  }
}
function setLoop(){
  const resume=state.playing;pause();const duration=state.packet.duration_seconds;
  state.loopStart=Math.max(0,Math.min(duration,Number($("loop-start").value)));state.loopEnd=Math.max(state.loopStart,Math.min(duration,Number($("loop-end").value)));state.loop=$("loop-enabled").checked&&state.loopEnd-state.loopStart>=.1;
  $("loop-start").value=state.loopStart.toFixed(3);$("loop-end").value=state.loopEnd.toFixed(3);$("loop-enabled").checked=state.loop;if(resume)start();
}
function windowListen(at){const p=state.packet,t=Math.max(0,Math.min(p.duration_seconds,at));$("loop-start").value=Math.max(0,t-5).toFixed(3);$("loop-end").value=Math.min(p.duration_seconds,t+5).toFixed(3);$("loop-enabled").checked=true;setLoop();seek(Math.max(0,t-5));}

function verdictSelect(key){
  const select=document.createElement("select");select.dataset.key=key;select.setAttribute("aria-label",key+" 판정");
  for(const [value,label] of Object.entries(verdicts)){const o=document.createElement("option");o.value=value;o.textContent=label;select.append(o);}select.value=state.decisions[key]||"unreviewed";
  select.onchange=()=>{state.decisions[key]=select.value;markDirty();};return select;
}
function listenButton(at){const b=document.createElement("button");b.textContent="앞뒤 반복";b.onclick=()=>windowListen(at);return b;}
function cell(text,className=""){const td=document.createElement("td");td.textContent=text;td.className=className;return td;}
function representation(event){
  const names={integer:"정수",simple_fraction:"간단 분수",storage_precision:"명목값 · 미세 저장 정밀도 차이",outside_vocabulary:"현재 표현 범위 밖",out_of_domain:"30–400 범위 밖"};
  return names[event.representation]+" · "+event.nearest_fraction;
}
function renderEvents(){
  const p=state.packet;$("tempo-body").replaceChildren();$("meter-body").replaceChildren();
  for(const e of p.tempos){const tr=document.createElement("tr");if(e.time<0||e.time>=p.duration_seconds)tr.className="context";tr.append(cell(time(e.time)),cell(number(e.bpm),"rate"),cell(representation(e)));const verdict=document.createElement("td");verdict.append(verdictSelect(e.key));const listen=document.createElement("td");listen.append(listenButton(e.time));tr.append(verdict,listen);$("tempo-body").append(tr);}
  for(const e of p.meters){const tr=document.createElement("tr");if(e.time<0||e.time>=p.duration_seconds)tr.className="context";tr.append(cell(time(e.time)),cell(e.numerator+"/"+e.denominator),cell(e.note||(e.time<0?"음원 시작 전 시계 문맥":"")));const verdict=document.createElement("td");verdict.append(verdictSelect(e.key));const listen=document.createElement("td");listen.append(listenButton(e.time));tr.append(verdict,listen);$("meter-body").append(tr);}
  $("issues").replaceChildren();$("issue-count").textContent=p.issues.length+"개";
  if(!p.issues.length){const text=document.createElement("p");text.className="muted";text.textContent="별도 구조상 의심 항목이 없습니다. 아래 템포·박자 선언과 음악의 대응은 청취로 확인해 주세요.";$("issues").append(text);}
  for(const issue of p.issues){const item=document.createElement("div");item.className="issue "+issue.kind;const content=document.createElement("div"),type=document.createElement("span"),text=document.createElement("p");type.className="kind";type.textContent=issue.kind==="attention"?"검토할 항목":"범위·원본 문맥";text.textContent=issue.text;content.append(type,text);const actions=document.createElement("div");actions.className="actions";actions.append(verdictSelect(issue.key),listenButton(issue.time));item.append(content,actions);$("issues").append(item);}
}
function bulkVerdict(kind){for(const e of state.packet[kind])state.decisions[e.key]="valid";renderEvents();markDirty();}
function updatePlayed(){if(!state.packet)return;const seconds=state.played.reduce((n,[a,b])=>n+b-a,0);$("played-note").textContent=`이 화면에서 음원이 재생된 구간: ${(seconds/60).toFixed(1)}분 / ${(state.packet.duration_seconds/60).toFixed(1)}분. 재생 기록만으로 검토 완료가 확정되지는 않습니다.`;}

function snapshot(statusName){return {reference_sha256:state.packet.reference_sha256,status:statusName,checks:Object.fromEntries(checks.map(k=>[k,$("check-"+k).checked])),decisions:{...state.decisions},note:$("review-note").value,comparison_offset_ms:state.offset,played_intervals:state.played.map(r=>r.slice())};}
function cacheDraft(){if(!state.packet)return;const r=state.records[state.packet.id],savedStatus=!state.dirty&&r?.reference_sha256===state.packet.reference_sha256?r.status:"draft";try{localStorage.setItem("sample-review:"+state.index.batch_id+":"+state.packet.id,JSON.stringify({...snapshot(savedStatus),answer_dirty:state.dirty,cached_at:Date.now()}));}catch{}}
function markDirty(){state.dirty=true;state.editVersion++;cacheDraft();updateProgress();scheduleSave(true);}
function scheduleSave(answerChanged){
  if(!state.packet)return;if(answerChanged)state.dirty=true;cacheDraft();clearTimeout(state.saveTimer);
  state.saveTimer=setTimeout(()=>saveReview("draft",false).catch(e=>status("save-status",e.message,"error")),1100);
}
async function saveReview(statusName,explicit=true){
  clearTimeout(state.saveTimer);if(!state.packet)return;observePlayback();const packet=state.packet,version=state.editVersion;
  if(!explicit&&!state.dirty){const existing=state.records[packet.id];statusName=existing?.reference_sha256===packet.reference_sha256?existing.status:"draft";}
  const payload=snapshot(statusName);status("save-status","검토 기록 저장 중…");
  const task=async()=>{const r=await fetch("/api/review/"+encodeURIComponent(packet.id),{method:"POST",headers:{"Content-Type":"application/json","X-Review-Session":state.token},body:JSON.stringify(payload)});const result=await r.json();if(!r.ok)throw Error(result.error||"검토 기록 저장에 실패했습니다.");state.records[packet.id]=result.record;
    if(state.packet?.id===packet.id&&version===state.editVersion){state.dirty=false;status("save-status",`${labels[result.record.status]} · 저장 완료`,"success");$("saved-at").textContent=new Date(result.record.saved_at_utc).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"});try{localStorage.removeItem("sample-review:"+state.index.batch_id+":"+packet.id);}catch{}}
    updateProgress();renderList();return result;};
  const queued=state.saveChain.catch(()=>{}).then(task);state.saveChain=queued;return queued;
}
async function selectTrack(id){
  if(state.packet){pause();if(state.dirty||state.played.length)await saveReview("draft",false);}
  clearTimeout(state.saveTimer);const gen=++state.generation;state.controller?.abort();state.controller=null;state.loading=false;const old=state.context;state.context=null;state.music=state.clicks=state.peaks=null;if(old)await old.close();if(gen!==state.generation)return;
  const row=state.index.tracks.find(t=>t.id===id);if(!row)return;const r=await fetch(row.packet_url);if(!r.ok)throw Error("검토 지도를 불러오지 못했습니다.");const p=await r.json();if(gen!==state.generation)return;
  state.packet=p;state.position=0;state.offset=0;state.playing=false;state.loop=false;state.dirty=false;state.editVersion=0;state.decisions={};state.played=[];
  let saved=state.records[p.id];if(saved?.reference_sha256!==p.reference_sha256)saved=null;
  let local;try{local=JSON.parse(localStorage.getItem("sample-review:"+state.index.batch_id+":"+p.id));}catch{}
  if(local?.reference_sha256===p.reference_sha256&&(!saved||local.cached_at>Date.parse(saved.saved_at_utc))){saved=local;state.dirty=local.answer_dirty===true;}
  if(saved){state.decisions={...saved.decisions};state.offset=saved.comparison_offset_ms||0;state.played=mergeIntervals(saved.played_intervals||[]);}
  for(const k of checks)$("check-"+k).checked=saved?.checks?.[k]===true;$("review-note").value=saved?.note||"";$("offset").value=state.offset;
  const roleNames={finished_recording_development:"완성 녹음",formal_original_recording_excerpt:"원곡 발췌",formal_synthetic_recording:"승인된 합성 표본",auxiliary_solo_guitar:"보조 · 독주 기타",auxiliary_synthetic_recording:"보조 · 합성",acquired_candidate:"미승인 후보"};
  $("role").textContent=roleNames[p.role]||p.role;$("previous").textContent=p.previous_approval?"정식/보조 등록 · 이전 승인 있음":"오프셋·음악적 해석 미승인";$("title").textContent=p.title;
  $("summary").textContent=`${time(p.duration_seconds,false)} · ${p.sample_rate.toLocaleString()} Hz · ${p.channels}채널 · ${(p.audio_bytes/1e6).toFixed(1)} MB`;$("notes").textContent=p.notes||"";$("duration").textContent=time(p.duration_seconds,false);$("seek").max=p.duration_seconds;$("seek").value=0;$("play").disabled=false;$("play").textContent="재생";
  $("loop-start").value=0;$("loop-end").value=Math.min(10,p.duration_seconds);$("loop-enabled").checked=false;state.loopStart=0;state.loopEnd=Math.min(10,p.duration_seconds);
  $("click-mode").replaceChildren();for(const mode of p.click_modes){const o=document.createElement("option");o.value=mode.id;o.textContent=mode.label;$("click-mode").append(o);}
  $("click-mode").disabled=!p.available_map;$("click-enabled").disabled=!p.available_map;$("accent").disabled=!p.available_map;$("offset").disabled=!p.available_map;
  for(const button of document.querySelectorAll("[data-offset], #reset-offset"))button.disabled=!p.available_map;
  $("scope-note").textContent=p.available_map?"지도 지원 범위: "+p.support_seconds.map(([a,b])=>`${time(a)}–${time(b)}`).join(" · ")+(p.no_grid_seconds.length?". 격자 밖 승인 구간: "+p.no_grid_seconds.map(([a,b])=>`${time(a)}–${time(b)}`).join(" · "):". 나머지 범위는 미확인입니다."):"제공된 템포·박자 시계가 없어 원음만 청취할 수 있습니다.";
  $("decision-scope").textContent=p.group==="candidate"?"이 곡은 미승인 후보이며 정식 표본 검증 분모에 포함되지 않습니다. 후보 검토 기록을 저장해도 기존 카탈로그에는 등록되지 않습니다.":(p.role==="formal_original_recording_excerpt"?"이번 판단의 대상은 보관된 원곡 발췌 음원과 표시된 지도 지원 범위입니다. 원곡 전체의 검증으로 확장되지 않습니다.":"이번 판단은 표시된 지도 지원 범위와 끝부분 처리에 대한 직접 청취 결과입니다.");
  $("confirm").textContent=p.group==="candidate"?"후보 검토 기록 저장":"현재 지도 확인 완료";$("saved-at").textContent=saved?.saved_at_utc?new Date(saved.saved_at_utc).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"}):"";
  renderEvents();updateProgress();renderList();updateOffset();renderOffsetOptions();updatePlayed();renderEvidence();updateTransport();$("main").setAttribute("aria-busy","false");
  status("player-status",p.available_map?"재생을 누르면 원음과 현재 지도의 클릭을 불러옵니다.":"이 후보는 원음만 재생됩니다. 제공된 정답 시계가 없습니다.");status("save-status",saved?"저장된 검토 기록을 불러왔습니다.":"이번 검토는 아직 완료되지 않았습니다.");
}
function renderEvidence(){
  const p=state.packet;$("evidence-summary").replaceChildren();
  const entries=[["음원",p.audio_path],["검토 지도",p.reference_path],["검토 지도 지문",p.reference_sha256],["음원 지문",p.audio_catalog_sha256?"카탈로그 기록: "+p.audio_catalog_sha256+" (이번에 음원 전체 바이트를 해시하지 않음)":"별도 미기록"],["현재 클릭 단위·범위 정책",p.click_unit_note||"기록된 박·마디 위치 사용"]];
  for(const [key,value] of entries){const text=document.createElement("p");text.textContent=key+": "+value;$("evidence-summary").append(text);}
  $("downloads").replaceChildren();for(const file of [{label:"현재 검토 지도 JSON",url:p.reference_url},{label:"원음",url:p.audio_url},...p.source_downloads]){const a=document.createElement("a");a.textContent=file.label;a.href=file.url;a.download="";$("downloads").append(a);}
}

function setupCanvas(id,height){const c=$(id),ratio=devicePixelRatio||1,w=Math.max(250,c.clientWidth);if(c.width!==Math.round(w*ratio)||c.height!==height*ratio){c.width=Math.round(w*ratio);c.height=Math.round(height*ratio);}const g=c.getContext("2d");g.setTransform(ratio,0,0,ratio,0,0);g.clearRect(0,0,w,height);return {c,g,w,h:height};}
function inside(t,ranges){return ranges.some(([a,b])=>a<=t&&t<=b);}
function drawOverview(){
  const p=state.packet;if(!p)return;const {g,w}=setupCanvas("overview",180),left=43,right=w-13,shift=state.offset/1000,x=t=>left+(right-left)*t/p.duration_seconds;
  g.fillStyle="#5c5035";g.fillRect(left,13,right-left,138);
  for(const [a,b] of p.support_seconds){g.fillStyle="#24493f";g.fillRect(x(Math.max(0,a+shift)),13,Math.max(0,x(Math.min(p.duration_seconds,b+shift))-x(Math.max(0,a+shift))),138);}
  for(const [a,b] of p.no_grid_seconds){g.fillStyle="#553535";g.fillRect(x(a),13,x(b)-x(a),138);}
  const values=p.tempos.map(e=>e.bpm),lo=values.length?Math.min(...values)-10:0,hi=values.length?Math.max(...values)+10:100,y=v=>78-(v-lo)/(hi-lo)*56;
  g.font="11px system-ui";g.fillStyle="#a6b4c0";g.fillText("BPM",5,29);g.fillText("박자",5,116);
  g.save();g.beginPath();for(const [a,b] of p.support_seconds){const begin=Math.max(0,a+shift),end=Math.min(p.duration_seconds,b+shift);if(end>begin)g.rect(x(begin),10,x(end)-x(begin),131);}g.clip();
  for(let i=0;i<p.tempos.length;i++){const e=p.tempos[i],a=Math.max(0,e.time+shift),b=Math.min(p.duration_seconds,(p.tempos[i+1]?.time??p.duration_seconds)+shift);if(b<=a)continue;g.strokeStyle="#8de1c4";g.lineWidth=2;g.beginPath();g.moveTo(x(a),y(e.bpm));g.lineTo(x(b),y(e.bpm));g.stroke();g.fillStyle="#b2e8d6";if(x(b)-x(a)>40){const label=e.representation==="storage_precision"?number(e.nominal_bpm)+" 명목":e.representation==="simple_fraction"?e.nearest_fraction:number(e.bpm).slice(0,9);g.fillText(label,x(a)+4,y(e.bpm)-6);}}
  for(let i=0;i<p.meters.length;i++){const e=p.meters[i],a=Math.max(0,e.time+shift),b=Math.min(p.duration_seconds,(p.meters[i+1]?.time??p.duration_seconds)+shift);if(b<=a)continue;g.fillStyle=i%2?"#334d6a":"#29435d";g.fillRect(x(a),98,x(b)-x(a),28);if(x(b)-x(a)>20){g.fillStyle="#e5edf5";g.fillText(`${e.numerator}/${e.denominator}`,x(a)+3,116);}}
  g.restore();
  g.strokeStyle="#e5c46e";g.lineWidth=1.5;g.beginPath();g.moveTo(x(currentPosition()),10);g.lineTo(x(currentPosition()),152);g.stroke();g.fillStyle="#a6b4c0";for(let i=0;i<=4;i++){const t=p.duration_seconds*i/4;g.fillText(time(t,false),Math.min(w-48,x(t)),169);}
}
function detailRange(){const d=state.packet.duration_seconds,pos=currentPosition(),span=Math.min(12,d),a=Math.max(0,Math.min(d-span,pos-span/2));return [a,a+span];}
function drawDetail(){
  const p=state.packet;if(!p)return;const {g,w}=setupCanvas("detail",130),[a,b]=detailRange(),x=t=>12+(w-24)*(t-a)/(b-a),shift=state.offset/1000;
  g.fillStyle="#5c5035";g.fillRect(12,12,w-24,91);for(const [lo,hi] of p.support_seconds){const begin=Math.max(a,lo+shift),end=Math.min(b,hi+shift);if(end>begin){g.fillStyle="#19332c";g.fillRect(x(begin),12,x(end)-x(begin),91);}}
  if(state.peaks){g.strokeStyle="#a8b8c499";g.lineWidth=1;g.beginPath();const step=state.peaks.secondsPerPeak,v=state.peaks.values;for(let i=0;i<w-24;i++){const lo=Math.max(0,Math.floor((a+(b-a)*i/(w-24))/step)),hi=Math.min(v.length,Math.ceil((a+(b-a)*(i+1)/(w-24))/step));let peak=0;for(let n=lo;n<hi;n++)peak=Math.max(peak,v[n]);g.moveTo(12+i,57-peak*35);g.lineTo(12+i,57+peak*35);}g.stroke();}
  const mode=p.click_modes.find(m=>m.id===$("click-mode").value)||p.click_modes[0];
  for(const t of mode.times){const at=t+shift;if(at<a||at>b)continue;g.strokeStyle="#68b59e88";g.beginPath();g.moveTo(x(at),13);g.lineTo(x(at),101);g.stroke();}
  if($("accent").checked)for(const t of p.bars){const at=t+shift;if(at<a||at>b)continue;g.strokeStyle="#e5c46e";g.beginPath();g.moveTo(x(at),13);g.lineTo(x(at),101);g.stroke();}
  g.strokeStyle="#eef3f7";g.beginPath();g.moveTo(x(currentPosition()),8);g.lineTo(x(currentPosition()),107);g.stroke();g.fillStyle="#a6b4c0";g.font="10px system-ui";for(let i=0;i<=4;i++){const t=a+(b-a)*i/4;g.fillText(time(t),Math.min(w-63,x(t)),123);}
}
function updateTransport(){
  if(!state.packet)return;const pos=currentPosition(),raw=pos-state.offset/1000;$("position").textContent=time(pos);if(document.activeElement!==$("seek"))$("seek").value=pos;
  const tempo=state.packet.tempos.filter(e=>e.time<=raw).at(-1),meter=state.packet.meters.filter(e=>e.time<=raw).at(-1);
  const rateLabel=tempo?(tempo.representation==="storage_precision"?number(tempo.nominal_bpm)+" BPM (명목)":number(tempo.bpm)+" BPM"):"";
  $("current-map").textContent=inside(raw,state.packet.support_seconds)&&state.packet.available_map?`${rateLabel} · ${meter?meter.numerator+"/"+meter.denominator:""}`:"표시 지도 범위 밖";
  $("current-map").title=tempo?`지도에 저장된 BPM: ${number(tempo.bpm)}. 클릭은 저장된 박 시각으로 재생합니다.`:"";
  drawOverview();drawDetail();
}

$("play").onclick=togglePlay;$("back").onclick=()=>seek(currentPosition()-5);$("forward").onclick=()=>seek(currentPosition()+5);$("seek").oninput=()=>seek($("seek").value);
$("jump-intro").onclick=()=>seek(0);$("jump-middle").onclick=()=>seek(state.packet.duration_seconds/2);$("jump-end").onclick=()=>seek(Math.max(0,state.packet.duration_seconds-25));$("jump-support-end").onclick=()=>seek(Math.max(0,(state.packet.support_seconds.at(-1)?.[1]||state.packet.duration_seconds)-8));
for(const id of ["music-gain","click-gain","click-enabled"])$(id).oninput=setGains;for(const id of ["accent","click-mode"])$(id).onchange=reconfigure;
for(const id of ["loop-enabled","loop-start","loop-end"])$(id).onchange=setLoop;$("loop-here").onclick=()=>windowListen(currentPosition());
$("offset").onchange=()=>setOffset(Number($("offset").value));$("reset-offset").onclick=()=>setOffset(0);for(const b of document.querySelectorAll("[data-offset]"))b.onclick=()=>setOffset(state.offset+Number(b.dataset.offset));
$("valid-tempos").onclick=()=>bulkVerdict("tempos");$("valid-meters").onclick=()=>bulkVerdict("meters");for(const k of checks)$("check-"+k).onchange=markDirty;$("review-note").oninput=markDirty;
$("confirm").onclick=()=>saveReview(state.packet.group==="candidate"?"candidate_reviewed":"confirmed_current_scope").catch(e=>status("save-status",e.message,"error"));
$("needs-correction").onclick=()=>saveReview("needs_correction").catch(e=>status("save-status",e.message,"error"));$("insufficient").onclick=()=>saveReview("insufficient_evidence").catch(e=>status("save-status",e.message,"error"));$("save-draft").onclick=()=>saveReview("draft").catch(e=>status("save-status",e.message,"error"));
for(const id of ["search","filter"])$(id).oninput=renderList;$("group").onchange=()=>{updateProgress();renderList();const first=filteredTracks()[0];if(first&&state.packet?.group!==$("group").value)selectTrack(first.id).catch(e=>status("save-status",e.message,"error"));};
$("export-all").onclick=async()=>{try{pause();if(state.dirty)await saveReview("draft",false);const r=await fetch("/api/export");if(!r.ok)throw Error("검토 결과를 불러오지 못했습니다.");const data=await r.json(),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)+"\n"],{type:"application/json"})),a=document.createElement("a");a.href=url;a.download=state.index.batch_id+"-owner-reviews.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){status("save-status",e.message,"error");}};
$("overview").onclick=e=>{const width=$("overview").clientWidth;seek((e.offsetX-43)/(width-56)*state.packet.duration_seconds);};$("detail").onclick=e=>{const [a,b]=detailRange();seek(a+(e.offsetX-12)/($("detail").clientWidth-24)*(b-a));};
window.addEventListener("keydown",e=>{if(["INPUT","SELECT","TEXTAREA","BUTTON"].includes(e.target.tagName)||e.ctrlKey||e.altKey||e.metaKey)return;if(e.code==="Space"){e.preventDefault();togglePlay();}else if(e.key==="ArrowLeft"){e.preventDefault();seek(currentPosition()-5);}else if(e.key==="ArrowRight"){e.preventDefault();seek(currentPosition()+5);}});
window.addEventListener("beforeunload",()=>{if(state.packet){observePlayback();cacheDraft();}});window.addEventListener("resize",updateTransport);
function frame(now){if(state.packet&&now-state.lastDraw>100){if(state.playing)observePlayback();updateTransport();state.lastDraw=now;}requestAnimationFrame(frame);}
(async()=>{try{
  const [index,review]=await Promise.all([fetch("index-data.json").then(r=>{if(!r.ok)throw Error("목록을 불러오지 못했습니다.");return r.json();}),fetch("/api/state").then(r=>r.json())]);
  state.index=index;state.records=review.records;state.token=review.session_token;
  const query=new URLSearchParams(location.search), requested=query.get("group")||index.default_group;
  $("group").value=["formal","auxiliary","candidate"].includes(requested)&&index.counts[requested]?requested:["formal","auxiliary","candidate"].find(group=>index.counts[group])||"formal";
  const requestedFilter=query.get("filter");if([...$("filter").options].some(option=>option.value===requestedFilter))$("filter").value=requestedFilter;
  if(index.review_title){document.title=index.review_title;document.querySelector("h1").textContent=index.review_title;}
  updateProgress();renderList();const tracks=filteredTracks(), first=tracks.find(track=>track.id===query.get("track"))||($("group").value==="formal"?tracks.find(track=>track.attention_count>0&&!reviewRecorded(track)):null)||tracks[0];
  if(first)await selectTrack(first.id);else status("player-status","이 목록에는 검토할 곡이 없습니다.");requestAnimationFrame(frame);
}catch(e){status("player-status",e.message,"error");}})();
