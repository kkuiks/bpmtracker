"""Bounded, source-clock MERT features for the approved comparison arm."""
import argparse
import json
import os
from pathlib import Path
import time
import numpy as np
import soundfile as sf
import soxr
from .probe_resources import digest


class MertExtractor:
    def __init__(self, model_root):
        import torch
        from transformers import AutoModel, AutoConfig
        torch.set_num_threads(4)
        self.torch=torch
        config=AutoConfig.from_pretrained(str(model_root),trust_remote_code=True,local_files_only=True)
        self.model=AutoModel.from_config(config,trust_remote_code=True)
        weights=torch.load(Path(model_root)/'pytorch_model.bin',map_location='cpu',weights_only=True)
        # PyTorch's weight_norm serialization changed; preserve the actual tensors.
        for old,new in [('encoder.pos_conv_embed.conv.weight_g','encoder.pos_conv_embed.conv.parametrizations.weight.original0'),
                        ('encoder.pos_conv_embed.conv.weight_v','encoder.pos_conv_embed.conv.parametrizations.weight.original1')]:
            if old in weights and new in self.model.state_dict():weights[new]=weights.pop(old)
        self.model.load_state_dict(weights,strict=True)
        del weights
        self.model=self.model.cuda().eval()
        self.weight_hash=digest(Path(model_root)/'pytorch_model.bin')

    def extract(self,audio,output,count):
        started=time.perf_counter();audio=Path(audio);output=Path(output)
        info=sf.info(audio);source_hash=digest(audio)
        binding=dict(source_sha256=source_hash,model_sha256=self.weight_hash,
                     implementation_sha256=digest(__file__),output_frames=count,output_fps=12.5,
                     layers='mean final four',core_seconds=4,context_seconds=1,precision='float32')
        side=output.with_suffix('.json')
        if output.exists():
            if not side.exists() or json.loads(side.read_text())['binding']!=binding:raise ValueError('MERT cache binding mismatch')
            return json.loads(side.read_text())|dict(cache_hit=True)
        output.parent.mkdir(parents=True,exist_ok=True)
        self.torch.cuda.reset_peak_memory_stats();target=np.arange(count)/12.5
        result=np.empty((count,768),np.float32);coverage=np.zeros(count,bool)
        with sf.SoundFile(audio) as stream,self.torch.inference_mode():
            for core in np.arange(0,info.duration,4.):
                lo=max(0.,core-1);hi=min(info.duration,core+5)
                first=round(lo*info.samplerate);last=round(hi*info.samplerate)
                stream.seek(first);samples=stream.read(last-first,dtype='float32',always_2d=True).mean(1)
                samples=soxr.resample(samples,info.samplerate,24000,quality='HQ').astype(np.float32)
                if len(samples)<400:samples=np.pad(samples,(0,400-len(samples)))
                samples=(samples-samples.mean())/np.sqrt(samples.var()+1e-7)
                outputs=self.model(input_values=self.torch.from_numpy(samples).cuda()[None],output_hidden_states=True)
                hidden=self.torch.stack(outputs.hidden_states[-4:]).mean(0)[0].cpu().numpy()
                if not np.isfinite(hidden).all():raise ValueError('nonfinite MERT features')
                centers=first/info.samplerate+(np.arange(len(hidden))*320+199.5)/24000
                ix=np.flatnonzero((target>=core)&(target<min(info.duration,core+4)))
                for channel in range(768):result[ix,channel]=np.interp(target[ix],centers,hidden[:,channel])
                coverage[ix]=True
                del outputs,hidden
        if not coverage.all():raise ValueError('MERT time coverage incomplete')
        np.savez_compressed(output,features=result.astype(np.float16))
        receipt=dict(binding=binding,elapsed_seconds=time.perf_counter()-started,
                     peak_reserved_bytes=self.torch.cuda.max_memory_reserved(),cache_hit=False)
        side.write_text(json.dumps(receipt,indent=2)+'\n');return receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--learning',type=Path,required=True);p.add_argument('--sources',type=Path,required=True)
    p.add_argument('--model-root',type=Path,required=True);p.add_argument('--cache-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--limit',type=int)
    a=p.parse_args();rows=json.loads(a.learning.read_text())['rows']+json.loads(a.sources.read_text())['rows']
    unique={r['audio_sha256']:r for r in rows};rows=list(unique.values())
    if a.limit:rows=rows[:a.limit]
    extractor=MertExtractor(a.model_root);records=[]
    for i,row in enumerate(rows):
        acoustic=Path(row.get('cache',str(Path('data/cache/tempo-meter-v3/acoustic-v1')/(row['audio_sha256']+'.npz'))))
        with np.load(acoustic) as z:count=len(z['logits'][::4])
        output=a.cache_root/(row['audio_sha256']+'.npz');record=extractor.extract(row['audio'],output,count)
        records.append(dict(id=row['id'],cache=str(output),**record));a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(dict(complete=i+1==len(rows),rows=records),indent=2)+'\n')
        print('MERT',i+1,'/',len(rows),row['id'],round(record['elapsed_seconds'],2),'sec',flush=True)


if __name__=='__main__':main()
