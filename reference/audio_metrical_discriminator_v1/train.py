"""Group-CV and final fitting use development songs only."""
import argparse
from pathlib import Path
import sys
import numpy as np
from .common import CONFIG,LEARNED,DEVELOPMENT,FOLDS,read,write,digest,guard,stamp
from .worker import arrays
from .model import design,fit,scores

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run)
    features={};labels={};packets={};opened=[];active=[False]
    def audit(event,args):
        if event!='open' or not active[0] or not isinstance(args[0],str):return
        path=args[0];mode=args[1] if isinstance(args[1],str) else ''
        if any(c in mode for c in 'wax+'):return
        if Path(path).suffix not in ['.json','.npz']:return
        opened.append(path)
        if '/references/' in path or 'evaluation-index' in path or '/raw-proxies/' in path:
            raise RuntimeError('Reference read during fitting')
        if any(s in path for s in ['/features/','/development-labels/','/encoded-units/']) and Path(path).stem not in DEVELOPMENT:
            raise RuntimeError('Validation data read during fitting')
    sys.addaudithook(audit);active[0]=True;model_records=[]
    try:
        for ident in DEVELOPMENT:
            features[ident]=arrays(run/'features'/f'{ident}.npz');labels[ident]=arrays(run/'development-labels'/f'{ident}.npz')
            packets[ident]=read(run/'encoded-units/proxy100'/f'{ident}.json')
        for method,options in LEARNED.items():
            designs={};cv=[]
            for ident in DEVELOPMENT:
                designs[ident]=design(features[ident],packets[ident],options)
            def dataset(ids):
                xs=[];ms=[];ys=[];gs=[]
                for ident in ids:
                    mask=labels[ident]['train_mask'];variants=[designs[ident]]
                    if options['anchor']:variants.append(design(features[ident],None,options))
                    for x in variants:
                        xs.append(x[mask]);ms.append(features[ident]['valid_candidates'][mask]);ys.append(labels[ident]['unit_index'][mask]);gs.extend([ident]*int(mask.sum()))
                return np.concatenate(xs),np.concatenate(ms),np.concatenate(ys),np.asarray(gs)
            for regularizer in CONFIG['regularizers']:
                fold_scores=[];fold_meta=[]
                for fold in FOLDS:
                    train_ids=[i for i in DEVELOPMENT if i not in fold]
                    model=fit(*dataset(train_ids),regularizer)
                    per_song=[]
                    for ident in fold:
                        out=scores(model,designs[ident],features[ident]['valid_candidates']);chosen=np.argmax(out,axis=1)
                        chosen[~features[ident]['source_available']]=-1
                        support=labels[ident]['in_support'];correct=(chosen==labels[ident]['unit_index'])&(chosen>=0)
                        per_song.append(float(correct[support].mean()))
                    fold_scores.extend(per_song);fold_meta.append({k:model[k] for k in ['iterations','optimizer_success','optimizer_message']})
                cv.append({'regularizer':regularizer,'development_song_accuracy':fold_scores,
                           'macro':float(np.mean(fold_scores)),'optimizer':fold_meta})
            selected=max(cv,key=lambda r:(r['macro'],r['regularizer']))['regularizer']
            model=fit(*dataset(DEVELOPMENT),selected)
            target=run/'models'/f'{method}.npz';target.parent.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(target,**{k:model[k] for k in ['weights','mean','scale']})
            meta={k:v for k,v in model.items() if k not in ['weights','mean','scale']}
            write(run/'models'/f'{method}.json',{'method':method,'options':options,'development_cv':cv,**meta,
                    'training_song_ids':DEVELOPMENT,'no_input_augmentation':options['anchor']})
            model_records.append({'method':method,'model_sha256':digest(target),
                                  'metadata_sha256':digest(run/'models'/f'{method}.json'),'selected_regularizer':selected})
            print('TRAINED',method,'lambda',selected,'CV',round(max(r['macro'] for r in cv),4),'rows',model['training_rows'],flush=True)
    finally:active[0]=False
    write(run/'model-freeze.json',{'frozen_at_utc':stamp(),'models':model_records,
          'development_only':True,'validation_predictions_not_scored':True})
    write(run/'worker-audit/train.json',{'actual_read_hook':True,'opened_data_paths':sorted(set(opened)),
          'validation_features_labels_references_read':False,'not_OS_sandbox':True})
    guard(run)

if __name__=='__main__':main()
