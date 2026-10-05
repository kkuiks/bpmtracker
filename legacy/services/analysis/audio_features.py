"""Portable WAV-to-frozen acoustic observations, with source-bound caching.

Uses the official Beat This Audio2Frames interface. This front end contains no
tempo reconstruction, reference lookup, meter search or song-specific rule.
"""
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import soundfile as sf


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def extract(audio, checkpoint, cache_root, *, device='cpu'):
    import torch
    from beat_this.inference import Audio2Frames
    audio=Path(audio);checkpoint=Path(checkpoint);cache_root=Path(cache_root)
    info=sf.info(audio);source=dict(sha256=digest(audio),sample_rate=info.samplerate,sample_frames=info.frames)
    binding=dict(source=source,checkpoint_sha256=digest(checkpoint),implementation_sha256=digest(__file__),fps=50,core_seconds=24,context_seconds=4)
    path=cache_root/(source['sha256']+'.npz');receipt=path.with_suffix('.json')
    if path.exists():
        record=json.loads(receipt.read_text())
        if record['binding']!=binding or record['feature_sha256']!=digest(path):raise ValueError('acoustic cache binding differs')
        return source,path,dict(cache_hit=True,elapsed_seconds=0.,binding=binding)
    tick=time.perf_counter();model=Audio2Frames(str(checkpoint.resolve()),device,float16=False)
    count=int(np.ceil(info.duration*50));features=np.zeros((count,512),np.float16);logits=np.zeros((count,2),np.float32);energy=np.zeros(count,np.float32)
    captured=[];hook=model.model.transformer_blocks.register_forward_hook(lambda m,i,o:captured.append(o))
    try:
        for core in range(0,count,1200):
            end=min(count,core+1200);left=max(0,core-200);right=min(count,end+200)
            signal,sr=sf.read(audio,start=round(left/50*info.samplerate),stop=min(info.frames,round(right/50*info.samplerate)),dtype='float32',always_2d=True)
            if not np.isfinite(signal).all():raise ValueError('nonfinite audio')
            with torch.inference_mode():values=model.model(model.signal2spect(signal,sr).unsqueeze(0))
            emb=captured.pop().squeeze(0);indices=np.arange(core,end);local=indices-left
            if local[-1]>=len(emb):raise ValueError('incomplete feature context')
            features[indices]=emb[local].cpu().numpy().astype(np.float16)
            logits[indices]=np.stack([values[k][0,local].cpu().numpy() for k in ('beat','downbeat')],axis=1)
            mono=signal.mean(1);squares=np.r_[0.,np.cumsum(mono.astype(np.float64)**2)]
            centers=np.rint(local/50*sr).astype(int);lo=np.clip(centers-round(sr/100),0,len(mono));hi=np.clip(centers+round(sr/100),0,len(mono))
            energy[indices]=np.sqrt((squares[hi]-squares[lo])/np.maximum(hi-lo,1))
    finally:hook.remove();captured.clear()
    cache_root.mkdir(parents=True,exist_ok=True);np.savez_compressed(path,features=features,logits=logits,energy=energy,fps=50)
    record=dict(binding=binding,feature_sha256=digest(path),elapsed_seconds=time.perf_counter()-tick,references_read=False)
    receipt.write_text(json.dumps(record,indent=2)+'\n')
    return source,path,dict(record,cache_hit=False)
