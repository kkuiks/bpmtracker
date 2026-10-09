import { useEffect, useState } from "react";
import { scopeText, type SampleLibrary, type SampleReference } from "./samples";
import type { DesktopApi } from "./model";

export default function SampleLibraryDialog({api,busy,onOpen,onClose}:{
  api:DesktopApi|undefined;busy:boolean;onOpen:(ref:SampleReference,comparison:boolean)=>void;onClose:()=>void;
}) {
  const [library,setLibrary]=useState<SampleLibrary>({root:null,tracks:[]});
  const [query,setQuery]=useState(""),[selected,setSelected]=useState<SampleReference|null>(null);
  const [loading,setLoading]=useState(false),[error,setError]=useState("");
  const reload=async(choose=false)=>{
    if(!api)return;
    setLoading(true);setError("");setSelected(null);
    try{setLibrary(await api.sampleLibrary(choose));}catch(e){setError(String(e));}
    finally{setLoading(false);}
  };
  useEffect(()=>{void reload();},[]);
  const choose=async(id:string)=>{
    if(!api||busy)return;
    setLoading(true);setError("");setSelected(null);
    try{setSelected(library.descriptorPath?await api.candidateReference(library.descriptorPath,id):await api.sampleReference(id));}catch(e){setError(String(e));}
    finally{setLoading(false);}
  };
  const openCandidates=async()=>{
    if(!api)return;
    setLoading(true);setError("");
    try{const result=await api.chooseCandidateReview();if(result){setLibrary(result);setSelected(null);}}
    catch(e){setError(String(e));}finally{setLoading(false);}
  };
  const tracks=library.tracks.filter(t=>(t.title+" "+t.id).toLowerCase().includes(query.toLowerCase()));
  return <>
    <h2>{library.descriptorPath?"Candidate Review":"Formal Samples"}</h2>
    <p>{library.descriptorPath?"Review supplied clocks and offsets, or open a source-only recording without a supplied metronome. Save a separate proposal for each recording.":"Open an enrolled recording with its approved reference. Edit the Tempo and Signature tracks in the DAW, then save a separate reference draft."}</p>
    <div className="sample-library-toolbar">
      <input aria-label="Search formal samples" placeholder="Search recordings…" value={query} onChange={e=>setQuery(e.target.value)}/>
      <button disabled={busy||loading} onClick={()=>void reload(true)}>Select catalog…</button>
      <button disabled={busy||loading} onClick={()=>void openCandidates()}>Open candidate review…</button>
      {library.descriptorPath&&<button disabled={busy||loading} onClick={()=>void reload()}>Formal library</button>}
      <span>{library.tracks.length} {library.descriptorPath?"candidates":"enrolled"}</span>
    </div>
    {loading&&<p>Reading sample references…</p>}
    {error&&<p className="form-error">{error}</p>}
    {!library.root&&!loading&&<p>Select the library's data/samples/catalog.json to begin.</p>}
    <div className="sample-library-body">
      <div className="sample-list"><table><thead><tr><th>Recording</th><th>Quarter BPM</th><th>Signature</th></tr></thead><tbody>
        {tracks.map(t=><tr key={t.id} className={selected?.id===t.id?"selected":""}>
          <td><button disabled={busy||loading||!!t.error} onClick={()=>void choose(t.id)}>{t.title}</button>
            <small>{t.error??(t.role==="unreviewed_source_only"?"Source only · unaccepted":t.role==="unreviewed_candidate"?"Candidate · unaccepted":t.role==="finished_recording_development"?"Complete recording":t.role.includes("synthetic")?"Approved synthetic":"Original recording excerpt")}</small></td>
          <td>{t.availableClock===false?"Not supplied":t.bpmLabels?.join(" / ")}</td><td>{t.availableClock===false?"Not supplied":t.meterLabels?.join(" / ")}</td>
        </tr>)}
      </tbody></table></div>
      <div className="sample-detail">{selected?<>
        <h3>{selected.title}</h3>
        {selected.description&&<p className="field-help">{selected.description}</p>}
        <dl><dt>Duration</dt><dd>{selected.duration.toFixed(3)} s</dd>
          <dt>{selected.previouslyAccepted?"Approved source offset":"Initial proposed offset"}</dt><dd>{selected.offset===null?(selected.availableClock===false?"Not supplied":"Annotation clock"):`${(selected.offset*1000).toFixed(3)} ms`}</dd>
          <dt>Reference scope</dt><dd>{scopeText(selected.support)}</dd>
          <dt>Approved no-grid scope</dt><dd>{scopeText(selected.noGrid)}</dd>
          <dt>Unannotated margins</dt><dd>{scopeText(selected.unknown)}</dd>
          <dt>First audible downbeat</dt><dd>{selected.bars.length?`${selected.bars[0].toFixed(6)} s`:"Not supplied"}</dd></dl>
        <p className="field-help">{selected.availableClock===false?"This recording has no supplied tempo/signature clock. The entire source remains unannotated; the DAW opens a working grid for manual editing.":"Readable BPM labels preserve the original clock. Negative declarations supply the initial state. Repeated signatures retain their bar-phase context."}</p>
        {selected.audit?.notes.map(note=><p key={note} className="field-help">{note}</p>)}
        {!!selected.audit?.previousComparisonOffsetMs&&<p>Previous comparison draft: {selected.audit.previousComparisonOffsetMs>0?"+":""}{selected.audit.previousComparisonOffsetMs} ms. Unaccepted.</p>}
        <h4>{selected.previouslyAccepted?"Approved":"Supplied"} tempo declarations</h4>
        <div className="sample-events">{selected.tempos.map((e,i)=><div key={i}><span>{e.seconds.toFixed(3)} s</span><b>{Number(e.bpm.toFixed(6))} BPM</b></div>)}</div>
        <h4>{selected.previouslyAccepted?"Approved":"Supplied"} signature declarations</h4>
        <div className="sample-events">{selected.meters.map((e,i)=><div key={i}><span>{e.seconds.toFixed(3)} s</span><b>{e.numerator}/{e.denominator}</b></div>)}</div>
        {selected.comparison&&<p>102 / 110 BPM comparison ready. Largest computed beat shift: {selected.comparison.maxShiftMs.toFixed(2)} ms. The comparison remains a proposal.</p>}
      </>:<p>Select a recording to inspect its approved map.</p>}</div>
    </div>
    <div className="modal-actions"><button onClick={onClose}>Close</button>
      {selected?.comparison&&<button disabled={busy||loading} onClick={()=>onOpen(selected,true)}>Open 102 / 110 draft</button>}
      <button className="primary-button" disabled={!selected||busy||loading} onClick={()=>selected&&onOpen(selected,false)}>{busy?"Preparing sample…":"Open sample workspace"}</button>
    </div>
  </>;
}
