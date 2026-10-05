"""Small task-specific temporal observation model on frozen acoustic features."""
import numpy as np
import torch
from torch import nn
from .observations import prepare

CONFIG=dict(projection_dim=64,hidden=64,dilations=[1,4,16,64,256],kernel_size=3,fps=50,context_frames=512)


def projection():
    generator=np.random.default_rng(20261001)
    return (generator.standard_normal((512,64))/np.sqrt(512)).astype(np.float32)


def inputs(features,logits,energy):
    reduced=features.astype(np.float32)@projection()
    flux=np.maximum(0,np.diff(np.log(np.maximum(energy,1e-6)),prepend=np.log(max(energy[0],1e-6))))
    return np.concatenate([reduced,logits,np.log(np.maximum(energy[:,None],1e-6)),flux[:,None]],1).astype(np.float32)


class ObservationModel(nn.Module):
    def __init__(self):
        super().__init__();self.start=nn.Conv1d(68,64,1)
        self.blocks=nn.ModuleList([nn.Conv1d(64,64,3,padding=d,dilation=d) for d in CONFIG['dilations']])
        self.finish=nn.Conv1d(64,3,1)
        nn.init.zeros_(self.finish.weight);nn.init.zeros_(self.finish.bias)

    def forward(self,x,base):
        hidden=torch.nn.functional.gelu(self.start(x.transpose(1,2)))
        for layer in self.blocks:hidden=hidden+.25*torch.nn.functional.gelu(layer(hidden))
        correction=16*torch.tanh(self.finish(hidden).transpose(1,2)/16)
        prior=torch.cat([base,torch.full_like(base[:,:,:1],4.)],dim=-1)
        return prior+correction


def predict_values(x,base,package,device='cpu'):
    model=ObservationModel().to(device);model.load_state_dict(package['state_dict']);model.eval()
    mean=np.asarray(package['mean'],np.float32);std=np.asarray(package['std'],np.float32)
    x=(x-mean)/std;values=np.empty((len(base),3),np.float32);context=CONFIG['context_frames']
    with torch.inference_mode():
        for start in range(0,len(x),2048):
            end=min(len(x),start+2048);lo=max(0,start-context);hi=min(len(x),end+context)
            result=model(torch.from_numpy(x[lo:hi]).unsqueeze(0).to(device),torch.from_numpy(base[lo:hi]).unsqueeze(0).to(device))[0].cpu().numpy()
            values[start:end]=result[start-lo:end-lo]
    return values-np.log(np.asarray(package.get('positive_weights',[1.,1.,1.]),np.float32))[None,:]


def observed(row,package,device='cpu'):
    with np.load(row['features']) as z:
        features=z['features'].copy();base=z['logits'].copy();energy=z['energy'].copy()
    x=inputs(features,base,energy)
    logits=predict_values(x,base,package,device)
    obs=prepare(logits[:,:2],energy,features=features)
    obs['quarter_probability_supervision']=True
    obs['acoustic_beat']=1/(1+np.exp(-np.clip(base[:,0],-30,30)))
    obs['grid_probability']=1/(1+np.exp(-np.clip(logits[:,2],-30,30)))
    return obs
