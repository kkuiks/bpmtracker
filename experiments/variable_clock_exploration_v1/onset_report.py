"""Evaluate the separately frozen onset challenger, including domain abstentions."""
import argparse
from collections import defaultdict
import hashlib
import json

from .evaluate import aggregate, read, reference, score, write
from .report import table
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run
    output=run/'onset-domain-guard-predictions'
    receipt=read(output/'receipt.json')
    if not receipt['completed'] or receipt['reference_files_read']:raise ValueError('Onset source stage incomplete')
    freeze=read(run/'onset-domain-guard-predictions-freeze.json')
    for name,value in freeze['source_hashes'].items():
        if hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=value:raise ValueError('Onset freeze mismatch')
    sources={r['id']:r for r in read(run/'source-inputs.json')['samples']}
    index=read(run/'evaluation-index.json')['rows'];result={};summaries={}
    for folder in sorted(p for p in output.iterdir() if p.is_dir()):
        rows=[]
        for row in index:
            if not sources[row['id']].get('audio_path'):continue
            path=folder/f"{row['id']}.json"
            if not path.exists():raise ValueError('Onset case missing')
            prediction=read(path)
            for region in prediction['regions']:
                if region.get('confidence_state')=='SUPPORTED' and not 30<=region['bpm_continuous']<=400:
                    raise ValueError('Unsupported scaled audio unit emitted as supported')
            duration=sources[row['id']]['duration_seconds']
            rows.append({'id':row['id'],'role':row['role'],'score':score(prediction,reference(row,duration),duration)})
        groups=defaultdict(list)
        for row in rows:groups[row['role']].append(row)
        result[folder.name]=rows;summaries[folder.name]={k:aggregate(v) for k,v in groups.items()}
    write(run/'onset-evaluation.json',{'summaries':summaries,'rows':result,
                                      'original_five_arm_freeze_unchanged':True,'no_real_reference_parameter_tuning':True})
    lines=['# Source-onset challenger — separate frozen follow-up','',
           'Two additional generic arms use source multiband attack events directly, without depending on neural beat-peak recall. The second optionally chooses one discrete pulse-level relation from initial source neural events. The numeric initial rate never targets fine BPM. Keeping this pulse-level relation for the entire input is an experimental assumption, not a rule for future variable analysis.',
           '', 'All 132 waveform input IDs are retained: all relevant real cases, formal fixed controls, constructed controls and twelve prospective inputs. GTZAN waveforms are unavailable, so its 367 feature cases are not evaluated by this challenger. These are repeated development/constructed comparisons, not new independent real tests.',
           '', 'The initial source-only run exposed 43 scaled latent clocks above the allowed BPM domain. Its source and predictions are preserved. Before onset-reference scoring, a generic domain guard was added: unsupported audio-unit intervals become UNKNOWN and their definite changes are omitted. No reference values, per-song thresholds or model weights changed. The final source hash and all supported-clock domain checks passed.',
           '', 'UNKNOWN remains a miss/coverage loss. Native versus octave interpretations, nominal exactness, phase F1 and exact-before/after boundary counts stay separate.']
    for role in ('real_variable','prospective_constructed','formal_fixed','generated_fixed','synthetic_prior_evaluation'):
        lines+=['',f'## {role}','',table(summaries,role)]
    (run/'onset-report.md').write_text('\n'.join(lines)+'\n')
    main=read(run/'comparison-summary.json');main.update(summaries)
    write(run/'all-directions-summary.json',main)
    for config,groups in summaries.items():
        print(config,json.dumps(groups.get('real_variable',{})),flush=True)


if __name__=='__main__':main()
