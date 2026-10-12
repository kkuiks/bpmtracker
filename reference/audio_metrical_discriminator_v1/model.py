"""Small conditional unit rankers learned with song-balanced loss."""
import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from .common import FACTORS,CONFIG

def design(feat,packet,options):
    n,k=feat['valid_candidates'].shape;pieces=[]
    for key in ['audio','neural']:
        if not options.get(key,False):continue
        x=feat[key];pieces.append(x)
        use=options.get('anchor',False) and packet is not None and packet.get('available',False)
        if options.get('anchor',False):
            if use:
                anchor=feat['anchor_'+key][packet['unit_index']]
                pieces.append(abs(x-anchor[None,None,:]))
                norm=np.linalg.norm(x,axis=2)*max(np.linalg.norm(anchor),1e-6)
                cosine=np.sum(x*anchor[None,None,:],axis=2)/np.maximum(norm,1e-6)
                pieces.append(cosine[:,:,None])
            else:
                pieces.append(np.zeros_like(x));pieces.append(np.zeros((n,k,1),np.float32))
    factors=np.asarray(FACTORS);pieces.append(np.broadcast_to(np.eye(k,dtype=np.float32),(n,k,k)))
    pieces.append(np.broadcast_to(np.log2(factors)[None,:,None],(n,k,1)))
    if options.get('anchor',False):
        if packet is not None and packet.get('available',False):
            difference=abs(np.log2(factors/factors[packet['unit_index']]))
            pieces.append(np.broadcast_to(difference[None,:,None],(n,k,1)))
            pieces.append(np.broadcast_to((difference<1e-8)[None,:,None],(n,k,1)).astype(np.float32))
        else:pieces.extend([np.zeros((n,k,1),np.float32),np.zeros((n,k,1),np.float32)])
    result=np.concatenate(pieces,axis=2).astype(np.float32)
    # Shared song/window offsets cancel in conditional scores. Removing them
    # explicitly also prevents constant acoustic descriptors becoming identities.
    v=feat['valid_candidates'];mean=np.sum(result*v[:,:,None],axis=1)/np.maximum(v.sum(axis=1)[:,None],1)
    result-=mean[:,None,:]
    return result

def fit(x,mask,y,groups,regularizer):
    allvalid=x[mask];mean=allvalid.mean(axis=0);scale=allvalid.std(axis=0)
    scale=np.maximum(scale,.05);z=np.clip((x-mean)/scale,-8,8).astype(np.float64)
    n,k,d=z.shape;weights=np.zeros(n)
    for ident in np.unique(groups):
        use=groups==ident;weights[use]=1/use.sum()
    weights/=weights.sum()
    def objective(beta):
        logits=np.einsum('nkd,d->nk',z,beta,optimize=True);logits[~mask]=-1e9
        norm=logsumexp(logits,axis=1);loss=np.sum(weights*(norm-logits[np.arange(n),y]))
        probability=np.exp(logits-norm[:,None]);probability[np.arange(n),y]-=1
        gradient=np.einsum('nk,nkd->d',probability*weights[:,None],z,optimize=True)
        return float(loss+regularizer/2*np.dot(beta,beta)),gradient+regularizer*beta
    optimum=minimize(objective,np.zeros(d),jac=True,method='L-BFGS-B',
                     options={'maxiter':CONFIG['optimizer_iterations'],'ftol':1e-9,'gtol':1e-6})
    return {'weights':optimum.x,'mean':mean,'scale':scale,
            'optimizer_success':bool(optimum.success),'optimizer_message':str(optimum.message),
            'iterations':int(optimum.nit),'objective':float(optimum.fun),'regularizer':regularizer,
            'training_rows':n,'feature_dimensions':d,'song_balanced':True}

def scores(model,x,mask):
    z=np.clip((x-model['mean'])/model['scale'],-8,8)
    result=np.einsum('nkd,d->nk',z,model['weights'],optimize=True);result[~mask]=-1e9
    return result

def heuristic(feat,method,packet):
    n,k=feat['valid_candidates'].shape;f=np.asarray(FACTORS);available=packet is not None and packet.get('available',False)
    if method=='N0_NATIVE' or (not available and method!='P0_PATTERN_NEAREST'):
        result=np.broadcast_to(-abs(np.log2(f))[None,:],(n,k)).copy()
    elif method=='N2_INITIAL_RELATION':
        result=np.broadcast_to(-abs(np.log2(f/f[packet['unit_index']]))[None,:],(n,k)).copy()
    elif method=='P0_PATTERN_NEAREST':
        if available:
            anchor=feat['anchor_audio'][packet['unit_index']];body=feat['audio']
            result=-np.mean((body-anchor[None,None,:])**2,axis=2)
        else:result=np.broadcast_to(-abs(np.log2(f))[None,:],(n,k)).copy()
    else:raise ValueError(method)
    result[~feat['valid_candidates']]=-1e9;return result
