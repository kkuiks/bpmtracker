import { useEffect,useState } from "react";
import { NumberField } from "./controls";
import { scopeText } from "./samples";
import type { Project } from "./model";

export default function SampleReviewPanel({project,onPreview,onProject,onNote,onSave,onAlignment}:{
  project:Project;onPreview:(comparison:boolean)=>void;onProject:()=>void;onNote:(note:string)=>void;
  onSave:()=>void;onAlignment:(milliseconds:number)=>void;
}) {
  const review=project.sampleReview!;
  const [note,setNote]=useState(review.note);
  useEffect(()=>setNote(review.note),[review.note,review.reference.id]);
  const ref=review.reference,clip=project.clips.find(c=>c.id===review.clipId);
  const suppliedClock=ref.availableClock!==false;
  const alignment=clip?(review.initialAudioOrigin-clip.start+clip.sourceStart)*1000:0;
  return <section className="sample-review-panel">
    <h4>{ref.previouslyAccepted?"Sample Reference":suppliedClock?"Candidate · unaccepted":"Candidate · source only"}</h4><strong>{ref.title}</strong>
    {ref.description&&<p className="field-help">{ref.description}</p>}
    <dl><dt>Quarter BPM</dt><dd>{suppliedClock?ref.bpmLabels.join(" / "):"Not supplied"}</dd><dt>Signature</dt><dd>{suppliedClock?ref.meterLabels.join(" / "):"Not supplied"}</dd>
      <dt>{ref.previouslyAccepted?"Approved offset":"Initial proposal"}</dt><dd>{ref.offset===null?(suppliedClock?"Annotation clock":"Not supplied"):`${(ref.offset*1000).toFixed(3)} ms`}</dd>
      <dt>Total working offset</dt><dd>{ref.offset===null?(suppliedClock?"Annotation clock":"Not supplied"):`${(ref.offset*1000+alignment).toFixed(3)} ms`}</dd>
      <dt>Reference scope</dt><dd>{scopeText(ref.support)}</dd><dt>No-grid scope</dt><dd>{scopeText(ref.noGrid)}</dd>
      <dt>Unannotated</dt><dd>{scopeText(ref.unknown)}</dd></dl>
    {suppliedClock&&<NumberField label="Alignment adjustment" value={alignment} suffix="ms" step={1}
      max={clip?(review.initialAudioOrigin+clip.sourceStart)*1000:0} onChange={onAlignment}/>}
    <p className="field-help">{suppliedClock?"Positive moves the audio earlier relative to the working grid. The original offset remains source evidence. Total working offset includes this adjustment.":"Listen to the original recording and save a manual working-map draft or a note. A source offset requires an established reference clock."}</p>
    {ref.sourceOffsetAlternatives?.map((alternative,i)=><button key={i} className="secondary-button full" onClick={()=>onAlignment((alternative.offset_seconds-(ref.offset??0))*1000)}>Try source offset {(alternative.offset_seconds*1000).toFixed(3)} ms</button>)}
    {!!ref.audit?.previousComparisonOffsetMs&&<p className="field-help">Previous comparison draft: {ref.audit.previousComparisonOffsetMs>0?"+":""}{ref.audit.previousComparisonOffsetMs} ms. Apply an adjustment above to review it; it is unaccepted.</p>}
    {review.mapImportWarning&&<p className="form-error">{review.mapImportWarning}</p>}
    <button className="secondary-button full" disabled={!clip||!suppliedClock} onClick={()=>onPreview(false)}>{ref.previouslyAccepted?"Audition approved click":"Audition original candidate click"}</button>
    {ref.comparison&&<button className="secondary-button full" disabled={!clip} onClick={()=>onPreview(true)}>Compare 102 / 110 BPM</button>}
    <button className="secondary-button full" onClick={onProject}>Audition edited project map</button>
    <label className="sample-note">Reference draft note<textarea value={note} onChange={e=>setNote(e.target.value)} onBlur={()=>note!==review.note&&onNote(note)}/></label>
    <button className="primary-button full" disabled={!clip} onClick={()=>{if(note!==review.note)onNote(note);onSave();}}>Save sample draft</button>
    <p className="field-help">Saves the project and proposed reference separately. Approving a new formal reference is a separate step.</p>
  </section>;
}
