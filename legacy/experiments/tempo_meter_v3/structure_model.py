"""Small contextual structure model; labels are masked per qualified field."""
import math
import torch
from torch import nn

CONFIG=dict(input_dim=514,hidden=128,layers=4,heads=4,context_frames=400,fps=12.5,
            numerator_classes=32,denominators=[2,4,8,16,32])


class StructureModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.input=nn.Linear(514,128)
        self.blocks=nn.TransformerEncoder(nn.TransformerEncoderLayer(128,4,512,.1,batch_first=True,norm_first=True),4,enable_nested_tensor=False)
        self.events=nn.Linear(128,4) # quarter, downbeat, change, grid support
        self.numerator=nn.Linear(128,32)
        self.denominator=nn.Linear(128,5)
        self.tempo=nn.Linear(128,1)

    def forward(self,x,padding=None):
        h=self.input(x)
        t=torch.arange(h.shape[1],device=h.device,dtype=h.dtype)[:,None]
        freq=torch.exp(torch.arange(0,128,2,device=h.device,dtype=h.dtype)*(-math.log(10000.)/128))
        pos=torch.zeros((h.shape[1],128),device=h.device,dtype=h.dtype)
        pos[:,0::2]=torch.sin(t*freq);pos[:,1::2]=torch.cos(t*freq)
        h=self.blocks(h+pos,src_key_padding_mask=padding)
        return dict(events=self.events(h),numerator=self.numerator(h),denominator=self.denominator(h),tempo=self.tempo(h).squeeze(-1))


def predict(features,logits,checkpoint,device='cuda'):
    import numpy as np
    model=StructureModel().to(device)
    package=torch.load(checkpoint,map_location=device,weights_only=False)
    model.load_state_dict(package['state_dict']);model.eval()
    x=np.concatenate([features[::4].astype(np.float32),logits[::4].astype(np.float32)],1)
    mean=np.asarray(package['mean'],np.float32);std=np.asarray(package['std'],np.float32)
    x=(x-mean)/std
    outputs={};counts=np.zeros(len(x),np.float32)
    with torch.inference_mode():
        for core in range(0,len(x),300):
            lo=max(0,core-50);hi=min(len(x),core+350);end=min(len(x),core+300)
            y=model(torch.from_numpy(x[lo:hi]).unsqueeze(0).to(device))
            for key,value in y.items():
                v=value[0].cpu().numpy()
                if key not in outputs:outputs[key]=np.zeros((len(x),*v.shape[1:]),np.float32)
                outputs[key][core:end]=v[core-lo:end-lo]
            counts[core:end]+=1
    if not np.all(counts==1):raise ValueError('structural coverage mismatch')
    return outputs
