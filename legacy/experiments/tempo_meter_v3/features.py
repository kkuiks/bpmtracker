"""Reference-free, streamed acoustic features with explicit source-frame mapping."""
from pathlib import Path
import json
import math
import time
import numpy as np
import soundfile as sf
from .probe_resources import digest

FPS=50


class Extractor:
    def __init__(self, checkpoint, device='cuda'):
        import torch
        from beat_this.inference import Audio2Frames
        path=Path(checkpoint)
        if not path.is_file():raise FileNotFoundError(path)
        torch.set_num_threads(4)
        self.model=Audio2Frames(str(path.resolve()),device,float16=False)
        self.device=device
        self.binding=dict(checkpoint_sha256=digest(path),implementation_sha256=digest(__file__),
                          fps=FPS,core_seconds=24,context_seconds=4,precision='float32')

    def extract(self,audio,cache):
        import torch
        audio,cache=Path(audio),Path(cache)
        source_hash=digest(audio);info=sf.info(audio)
        binding={**self.binding,'source_sha256':source_hash,'sample_rate':info.samplerate,'sample_frames':info.frames}
        receipt=cache.with_suffix('.json')
        if cache.exists():
            meta=json.loads(receipt.read_text())
            if meta['binding']!=binding or digest(cache)!=meta['feature_sha256']:
                raise ValueError('feature cache binding mismatch; use a fresh cache')
            return meta
        count=math.ceil(info.duration*FPS)
        features=np.zeros((count,512),np.float16);logits=np.zeros((count,2),np.float32)
        energy=np.zeros(count,np.float32);seen=np.zeros(count,bool)
        captured=[]
        hook=self.model.model.transformer_blocks.register_forward_hook(lambda m,i,o:captured.append(o))
        started=time.perf_counter()
        try:
            for core in range(0,count,24*FPS):
                end=min(count,core+24*FPS);left=max(0,core-4*FPS);right=min(count,end+4*FPS)
                a=round(left/FPS*info.samplerate);b=min(info.frames,round(right/FPS*info.samplerate))
                signal,sr=sf.read(audio,start=a,stop=b,dtype='float32',always_2d=True)
                if not np.isfinite(signal).all():raise ValueError('nonfinite audio')
                with torch.inference_mode():
                    spect=self.model.signal2spect(signal,sr)
                    values=self.model.model(spect.unsqueeze(0))
                emb=captured.pop().squeeze(0)
                indices=np.arange(core,end);local=indices-left
                if local[-1]>=len(emb):raise ValueError('incomplete feature window')
                features[indices]=emb[local].cpu().numpy().astype(np.float16)
                logits[indices]=np.stack([values[k][0,local].cpu().numpy() for k in ('beat','downbeat')],1)
                # Source-relative, centered 20ms RMS, independent of model labels.
                mono=signal.mean(1);sq=np.r_[0.,np.cumsum(mono.astype(np.float64)**2)]
                centers=np.rint(local/FPS*sr).astype(int)
                lo=np.clip(centers-round(sr/FPS/2),0,len(mono));hi=np.clip(centers+round(sr/FPS/2),0,len(mono))
                energy[indices]=np.sqrt((sq[hi]-sq[lo])/np.maximum(1,hi-lo))
                seen[indices]=True
                del spect,values,emb,signal
        finally:hook.remove();captured.clear()
        if not seen.all() or not np.isfinite(features).all():raise ValueError('incomplete or nonfinite features')
        cache.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(cache,features=features,logits=logits,energy=energy,fps=FPS)
        meta=dict(binding=binding,feature_sha256=digest(cache),frames=count,
                  duration_seconds=info.duration,elapsed_seconds=time.perf_counter()-started,
                  source_path=str(audio.resolve()),frame_time='frame_index / 50; source origin unchanged',
                  references_read=False)
        receipt.write_text(json.dumps(meta,indent=2)+'\n')
        return meta


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--audio',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);a=p.parse_args()
    print(json.dumps(Extractor(a.checkpoint).extract(a.audio,a.cache)))

if __name__=='__main__':main()
