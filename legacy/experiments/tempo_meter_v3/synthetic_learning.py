"""Procedural multivoice rhythm controls, not a studio-domain benchmark."""
from pathlib import Path
import numpy as np
import soundfile as sf
from .probe_resources import digest


def create(folder, count=32):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);rows=[]
    vocabulary=[(2,4),(3,4),(4,4),(5,4),(6,4),(5,8),(6,8),(7,8),(9,8),(12,8),(4,2),(7,16)]
    for index in range(count):
        rng=np.random.default_rng(76000+index);rate=22050
        t=1.;beats=[];bars=[];tempo=[];meters=[];notes=[];last_meter=None;last_rate=None
        base=float(rng.choice([72,86,100,120,140,160,190]));signature=vocabulary[index%len(vocabulary)]
        for bar in range(24):
            n,d=signature
            if index%2 and bar in (7,15):n,d=vocabulary[(index+bar)%len(vocabulary)]
            bpm=base*(1.12 if index%3 and 9<=bar<17 else 1)
            if bpm!=last_rate:tempo.append(dict(time_seconds=t,bpm_quarter=bpm));last_rate=bpm
            if (n,d)!=last_meter:meters.append(dict(time_seconds=t,numerator=n,denominator=d));last_meter=(n,d)
            bars.append(t);length=4*n/d;period=60/bpm
            # Continuous quarter phase is evaluated through the authored clock below.
            groups=([3]*(n//3) if d==8 and n%3==0 else [1]*n)
            group_start=np.cumsum([0]+groups[:-1]).tolist()
            for pulse in range(n):
                when=t+pulse*4/d*period
                accent=pulse==0;grouped=pulse in group_start
                notes.append((when,'kick' if grouped else 'hat',.7 if accent else .35))
                if pulse%2:notes.append((when,'snare',.2))
                notes.append((when,'bass',.12 if accent else .07))
                if accent:notes.append((when,'chord',.1))
            t+=length*period
        end=t;duration=end+8;frames=round(duration*rate);audio=np.zeros(frames,np.float32)
        # The beat grid follows the global quarter clock, including odd half quarters.
        q=0.;start=tempo[0]['time_seconds']
        for i,event in enumerate(tempo):
            stop=tempo[i+1]['time_seconds'] if i+1<len(tempo) else end
            count_q=(stop-event['time_seconds'])*event['bpm_quarter']/60
            for quarter in np.arange(np.ceil(q-1e-7),q+count_q-1e-7):
                beats.append(event['time_seconds']+(quarter-q)*60/event['bpm_quarter'])
            q+=count_q
        bass_frequency=float(rng.choice([55,65.4,73.4,82.4,98]))
        for when,instrument,amp in notes:
            at=round(when*rate);seconds={'kick':.15,'hat':.045,'snare':.12,'bass':.22,'chord':.7}[instrument]
            size=min(frames-at,round(seconds*rate));x=np.arange(size)/rate
            if instrument=='kick':wave=np.sin(2*np.pi*(52*x+1.7*(1-np.exp(-35*x))))*np.exp(-30*x)
            elif instrument in ('snare','hat'):wave=rng.standard_normal(size)*np.exp(-x*(65 if instrument=='hat' else 30))
            elif instrument=='bass':wave=np.tanh(2*np.sin(2*np.pi*bass_frequency*x))*np.exp(-12*x)
            else:wave=sum(np.sin(2*np.pi*f*x) for f in (bass_frequency*2,bass_frequency*2.5,bass_frequency*3))/3*np.exp(-5*x)
            audio[at:at+size]+=(amp*wave).astype(np.float32)
        tail_start=round(end*rate);x=np.arange(frames-tail_start)/rate
        audio[tail_start:]+=(.07*np.sin(2*np.pi*113*x)*np.exp(-x/4)).astype(np.float32)
        peak=np.max(abs(audio));audio*=.8/max(.8,peak)
        path=folder/f'procedure_{index:03d}.wav'
        sf.write(path,audio,rate,subtype='PCM_16')
        rows.append(dict(id=path.stem,audio=str(path.resolve()),audio_sha256=digest(path),group=path.stem,
            dataset='procedural',weight=.35,duration=frames/rate,split='validation' if index%5==0 else 'train',
            labels=dict(beats=beats,bars=bars,support=[start,end],tempo=tempo,meter=meters,meter_known=True,
                        no_grid=[[0,start],[end,frames/rate]]),
            provenance=dict(tier='exact_synthesis_clock',scope='procedural rhythm controls, no target-song motifs',
                            studio_generalization_claim=False)))
    return rows
