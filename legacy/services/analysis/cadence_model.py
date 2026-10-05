"""Chronological observer with an explicit acoustic period and relative rate.

This addresses the first pilot's absolute-rate predictions from timbre. The
period descriptor is source-only; production targets supervise the correction.
It is not a reference-derived BPM, fixed-range answer or meter grammar score.
"""
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .model import ChronologicalModel, feature_inputs as original_inputs


def cadence(logits, fps=50):
    beat=1/(1+np.exp(-np.clip(logits[:,0],-30,30)))
    centers=np.arange(0,len(beat),fps);descriptors=[]
    for center in centers:
        values=beat[max(0,center-4*fps):min(len(beat),center+4*fps)]
        x=values-values.mean();size=1<<(max(1,len(x))*2-1).bit_length()
        power=np.fft.rfft(x,size);correlation=np.fft.irfft(power*power.conjugate(),size)[:len(x)]
        lo=max(2,int(fps*60/400));hi=min(len(x)-2,int(fps*60/40))
        if hi<=lo or correlation[0]<=1e-8:
            descriptors.append([np.log(120.),0.,0.]);continue
        candidates=np.arange(lo,hi+1)
        peaks=candidates[(correlation[candidates]>correlation[candidates-1])&(correlation[candidates]>=correlation[candidates+1])]
        if not len(peaks):peaks=np.asarray([int(candidates[np.argmax(correlation[candidates])])])
        lag=int(peaks[np.argmax(correlation[peaks])]);curvature=correlation[lag-1]-2*correlation[lag]+correlation[lag+1]
        delta=float(np.clip(.5*(correlation[lag-1]-correlation[lag+1])/curvature,-.5,.5)) if curvature<0 else 0.
        bpm=60*fps/(lag+delta);regularity=float(correlation[lag]/max(correlation[0],1e-8))
        peaks_count=np.count_nonzero((values[1:-1]>.35)&(values[1:-1]>values[:-2])&(values[1:-1]>=values[2:]))
        descriptors.append([np.log(bpm),regularity,np.log(max(peaks_count/(len(values)/fps),.05))])
    descriptors=np.asarray(descriptors,np.float32);times=np.arange(len(beat))
    return np.column_stack([np.interp(times,centers,descriptors[:,i]) for i in range(3)]).astype(np.float32)


def feature_inputs(features,logits,energy):
    return np.column_stack([original_inputs(features,logits,energy),cadence(logits)]).astype(np.float32)


class CadenceModel(ChronologicalModel):
    def __init__(self):
        super().__init__();self.local=nn.Sequential(nn.Linear(519,64),nn.GELU())
        with torch.no_grad():self.output.bias[3]=0.

    def forward(self,values,base):
        local=self.local(values)
        pooled=F.avg_pool1d(local.transpose(1,2),4,ceil_mode=True).transpose(1,2)
        context,_=self.context(pooled)
        context=F.interpolate(context.transpose(1,2),size=local.shape[1],mode='linear',align_corners=False).transpose(1,2)
        output=self.output(torch.cat([local,context],dim=-1))
        return torch.cat([output[:,:,:2]+base[:,:,:2],output[:,:,2:3],output[:,:,3:4]+base[:,:,2:3],output[:,:,4:]],dim=-1)


def predict(features,base,energy,package,*,device='cpu',chunk_frames=4096,context_frames=1024):
    model=CadenceModel().to(device);model.load_state_dict(package['state_dict']);model.eval()
    x=feature_inputs(features,base,energy);extended_base=np.column_stack([base,x[:,-3]])
    x=(x-np.asarray(package['mean'],np.float32))/np.asarray(package['std'],np.float32)
    results=np.empty((len(x),9),np.float32)
    with torch.inference_mode():
        for start in range(0,len(x),chunk_frames):
            stop=min(len(x),start+chunk_frames);lo=max(0,start-context_frames);hi=min(len(x),stop+context_frames)
            out=model(torch.from_numpy(x[lo:hi]).unsqueeze(0).to(device),torch.from_numpy(extended_base[lo:hi]).unsqueeze(0).to(device))[0].cpu().numpy()
            results[start:stop]=out[start-lo:stop-lo]
    probabilities=1/(1+np.exp(-np.clip(results[:,:3]-np.log(np.asarray(package['positive_weights'],np.float32)),-30,30)))
    unit=results[:,4:];unit=np.exp(unit-unit.max(1,keepdims=True));unit/=unit.sum(1,keepdims=True)
    return dict(quarter=probabilities[:,0],bar=probabilities[:,1],grid=probabilities[:,2],quarter_bpm=np.exp(np.clip(results[:,3],np.log(20.),np.log(500.))),denominator=unit)
