"""Meaningful observation/learning controls before target feature extraction."""
import argparse
from pathlib import Path
import numpy as np
from .common import CONFIG,FACTORS,write
from .features import patterns
from .model import fit,scores,design

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();results=[]
    rng=np.random.default_rng(3102026);n=80;k=len(FACTORS);d=5;x=rng.normal(size=(n,k,d));y=np.argmax(x[:,:,0]-.4*x[:,:,1],axis=1)
    model=fit(x,np.ones((n,k),bool),y,np.array(['s'+str(i%4) for i in range(n)]),.01)
    accuracy=float(np.mean(np.argmax(scores(model,x,np.ones((n,k),bool)),axis=1)==y))
    results.append({'name':'learn_known_candidate_discriminator','accuracy':accuracy,'pass':accuracy>=.90})
    t=np.arange(0,16,.01);data=np.zeros((len(t),4))
    for e in np.arange(0,16,.5):data[:,0]+=np.exp(-.5*((t-e)/.02)**2)
    for e in np.arange(.5,16,1):data[:,-1]+=np.exp(-.5*((t-e)/.02)**2)
    f=patterns(t,data,.5,0.);g=patterns(t+.317,data,.5,.317)
    results.append({'name':'original_coordinate_shift_equivariance','maximum_difference':float(abs(f-g).max()),'pass':bool(np.allclose(f,g,atol=1e-4))})
    h=patterns(t,data*3,.5,0.)
    results.append({'name':'amplitude_normalization','maximum_difference':float(abs(f-h).max()),'pass':bool(np.allclose(f,h,atol=1e-4))})
    silent=patterns(t,np.zeros_like(data),.5,0.)
    results.append({'name':'empty_accent_finite','pass':bool(np.isfinite(silent).all())})
    feat={'valid_candidates':np.ones((2,k),bool),'audio':np.ones((2,k,len(f)),np.float32),
          'neural':np.ones((2,k,12),np.float32),'anchor_audio':np.ones((k,len(f)),np.float32),
          'anchor_neural':np.ones((k,12),np.float32)}
    packet={'available':True,'unit_index':5};v=design(feat,packet,{'audio':True,'neural':True,'anchor':True})
    results.append({'name':'source_anchor_dimensions_finite','pass':bool(np.isfinite(v).all() and v.shape[:2]==(2,k))})
    write(a.run/'pre-target-controls.json',{'rows':results,'all_pass':all(r['pass'] for r in results),
          'not_real_audio_or_neural_generalization':True})
    print('CONTROLS',results,flush=True)
    if not all(r['pass'] for r in results):raise RuntimeError('Fix control failure before target use')

if __name__=='__main__':main()
