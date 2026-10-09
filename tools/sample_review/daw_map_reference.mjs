/** Materialize saved DAW geometry on the unchanged source-audio axis. */
export function bpmDisplayLabel(rate) {
 let value=Math.round(rate),numerator=value,denominator=1;
 for(let d=2;d<=4;d++){
  const n=Math.round(rate*d);
  if(Math.abs(n/d-rate)<Math.abs(value-rate)-1e-10){value=n/d;numerator=n;denominator=d;}
 }
 if(Math.abs(60e6/rate-60e6/value)>1.00001)return Number(rate.toFixed(6)).toString();
 return denominator===1?String(numerator):`${numerator}/${denominator}`;
}

export function materializeDawMap(project, origin, start, end, music) {
 const eps=1e-9,inside=t=>Number.isFinite(t)&&t>=start-eps&&t<end-eps;
 const qstart=music.quarterAtTime(project,origin+start),qend=music.quarterAtTime(project,origin+end);
 const tempoDeclarations=[...project.tempos].sort((a,b)=>a.quarter-b.quarter).map((e,i)=>({
  source_event_index:i,quarter:e.quarter,time_seconds:music.timeAtQuarter(project,e.quarter)-origin,
  bpm_quarter:e.bpm,declaration_origin:'saved_daw_working_project'}));
 const sections=music.signatureSections(project);
 const meterDeclarations=sections.map((e,i)=>({source_event_index:i,quarter:e.quarter,
  time_seconds:music.timeAtQuarter(project,e.quarter)-origin,numerator:e.numerator,denominator:e.denominator,
  project_bar:e.bar,declaration_origin:'saved_daw_working_project'}));
 function effective(events,kind){
  const preceding=events.filter(e=>e.time_seconds<=start+eps).at(-1);
  if(!preceding)throw new Error('Missing state at the approved source start');
  const first={...preceding,time_seconds:start,quarter:qstart,source_declaration_audio_seconds:preceding.time_seconds,
   declaration_role:'inherited_initial_state',no_new_bar_anchor_at_audio_start:true};
  if(kind==='meter'){first.bar_action='continue';first.bar_origin_quarter=music.positionAtQuarter(project,qstart).barStart;}
  return [first,...events.filter(e=>e.time_seconds>start+eps&&e.time_seconds<end-eps).map(e=>({...e,
   declaration_role:'explicit_owner_working_map_change',...(kind==='meter'?{bar_action:'reset'}:{})}))];
 }
 const quarters=[],clicks=[],bars=[];
 for(let q=Math.ceil(qstart-1e-8),count=0;q<=qend+1e-8&&count<200000;q++,count++){
  const t=music.timeAtQuarter(project,q)-origin;
  if(inside(t))quarters.push({quarter:q,master_seconds:Math.max(start,t),bar_start:Math.abs(q-music.positionAtQuarter(project,q).barStart)<1e-7});
 }
 for(const [i,s] of sections.entries()){
  const stop=Math.min(qend,sections[i+1]?.quarter??qend),step=4/s.denominator;
  if(stop<qstart||s.quarter>=qend)continue;
  const first=Math.max(0,Math.ceil((Math.max(qstart,s.quarter)-s.quarter)/step-1e-8));
  for(let n=first,count=0;count<200000;n++,count++){
   const q=s.quarter+n*step;
   if(q>stop+1e-8||i+1<sections.length&&q>=sections[i+1].quarter-1e-8)break;
   const t=music.timeAtQuarter(project,q)-origin;
   if(inside(t)){clicks.push(Math.max(start,t));if(n%s.numerator===0)bars.push(Math.max(start,t));}
  }
 }
 const unique=a=>[...new Set(a)].sort((a,b)=>a-b);
 if(!quarters.length||!clicks.length||!bars.length)throw new Error('Approved map has no readable timing events');
 return {tempo_events:effective(tempoDeclarations,'tempo'),meter_events:effective(meterDeclarations,'meter'),
  tempo_declarations_audio_relative:tempoDeclarations,meter_declarations_audio_relative:meterDeclarations,
  quarter_events:quarters,quarter_beats_seconds:quarters.map(e=>e.master_seconds),beats_seconds:quarters.map(e=>e.master_seconds),
  downbeats_seconds:unique(bars),approved_click_beats_seconds:unique(clicks),
  evaluation_beat_unit:'quarter_note',approved_click_unit:'notated_signature_denominator',
  bar_anchor_quarter:0,bar_anchor_audio_seconds:-origin,
  quarter_axis:'Saved DAW project quarters; no original DAW bar-number claim.',
  declaration_origin_note:'Pre-audio declarations continue their state and phase; audio zero is not a new downbeat.',
  audio_relative_fields:['time_seconds','master_seconds','beats_seconds','downbeats_seconds','approved_click_beats_seconds'],
  additional_offset_to_apply_when_consuming_audio_relative_fields_seconds:0,
  render_policy:'Use stored source-audio-relative timing arrays directly; no second offset or bar reset at audio zero.'};
}
