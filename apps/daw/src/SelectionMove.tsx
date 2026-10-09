import { useState } from "react";
import { NumberField } from "./controls";
import { TimeField } from "./Transport";
import type { ArrangementSelection, Project } from "./model";
import { arrangementBounds, arrangementDestination, arrangementShift } from "./arrangement";

export default function SelectionMove({project,selection,linked,onMove,compact=false}:{
  project:Project;selection:ArrangementSelection;linked:boolean;onMove:(delta:number)=>void;compact?:boolean;
}) {
  const [unit,setUnit]=useState<"bars"|"beats">("bars"),[error,setError]=useState("");
  const bounds=arrangementBounds(project,selection,linked);
  if(!bounds)return null;
  const grid=arrangementDestination(project,selection);
  const shift=(amount:number)=>{try{const delta=arrangementShift(project,selection,linked,amount,unit);setError("");onMove(delta);}catch(e){setError(String(e));}};
  return <div className={compact?"selection-move compact-selection":"selection-move"}>
    <span className="selection-summary">{bounds.audioCount} audio · {bounds.tempoCount} tempo · {bounds.signatureCount} signature</span>
    <TimeField project={grid} label="Selection position" value={bounds.start} onChange={target=>onMove(target-bounds.start)}/>
    <div className="selection-shift">
      <NumberField key={`${bounds.start}:${unit}`} label="Move by" value={0} step={unit==="bars"?1:.25} suffix={unit} onChange={shift}/>
      <select aria-label="Selection movement unit" value={unit} onChange={e=>setUnit(e.target.value as "bars"|"beats")}><option value="bars">Bars</option><option value="beats">Beats</option></select>
      <button onClick={()=>shift(-1)} title={`Move selection one ${unit=== "bars"?"bar":"beat"} earlier`}>−1</button>
      <button onClick={()=>shift(1)} title={`Move selection one ${unit=== "bars"?"bar":"beat"} later`}>+1</button>
    </div>
    {!compact&&<p className="field-help">The earliest selected item sets the destination. Audio and selected clock points move together. Signature points require whole-bar placement.</p>}
    {error&&<p className="form-error">{error}</p>}
  </div>;
}
