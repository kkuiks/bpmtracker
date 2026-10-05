"""Sparse within-source repeated-context links, never bar-period labels."""
import numpy as np
from .latent_clock import time_at


def links(obs):
    features=obs.get('features')
    if features is None:return []
    # Fixed random projection, not trained on evaluation maps or song IDs.
    rng=np.random.default_rng(61001);project=rng.normal(size=(features.shape[1],12))/np.sqrt(features.shape[1])
    seconds=np.arange(0,obs['duration'],1.)
    reduced=[]
    for s in seconds:
        chunk=features[int(s*obs['fps']):int((s+1)*obs['fps'])].astype(float)
        reduced.append(chunk.mean(0)@project if len(chunk) else np.zeros(12))
    reduced=np.asarray(reduced);vectors=[];centers=[];durations=[]
    for duration in (4.,8.,12.):
        for center in np.arange(duration/2,obs['duration']-duration/2,4.):
            t=center+np.linspace(-duration/2,duration/2,8)
            v=np.stack([np.interp(t,seconds,reduced[:,j]) for j in range(12)],1)
            v=v-v.mean(0);norm=np.linalg.norm(v)
            if norm<1e-6:continue
            vectors.append((v/norm).ravel());centers.append(center);durations.append(duration)
    if len(vectors)<2:return []
    x=np.asarray(vectors);similarity=x@x.T;centers=np.asarray(centers);durations=np.asarray(durations)
    allowed=abs(centers[:,None]-centers)>np.maximum(durations[:,None],durations)*2
    similarity[~allowed]=-np.inf
    best=np.argmax(similarity,axis=1);result=[]
    for i,j in enumerate(best):
        if i<j and best[j]==i and similarity[i,j]>.9:
            # Correspondence permits tempo-scaled repeats through duration ratio.
            result.append(dict(a=float(centers[i]),b=float(centers[j]),
                duration_a=float(durations[i]),duration_b=float(durations[j]),weight=float(similarity[i,j])))
    return result


def messages(clock,bars,graph):
    if not graph:return None
    bq=np.array([b['q'] for b in bars]);length=np.array([4*b['n']/b['d'] for b in bars])
    anchors=[];phases=[];weights=[]
    for edge in graph:
        for a,b in [(edge['a'],edge['b']),(edge['b'],edge['a'])]:
            qa,qb=np.interp([a,b],clock[:,1],clock[:,0])
            k=np.clip(np.searchsorted(bq,qa,side='right')-1,0,len(bq)-1)
            anchors.append(qb);phases.append(float(((qa-bq[k])/length[k])%1));weights.append(edge['weight'])
    return np.asarray(anchors),np.asarray(phases),np.asarray(weights)


def consistency(clock,bars,graph):
    if not graph:return 0.
    bq=np.array([b['q'] for b in bars]);length=np.array([4*b['n']/b['d'] for b in bars]);penalty=0.
    for edge in graph:
        qa,qb=np.interp([edge['a'],edge['b']],clock[:,1],clock[:,0])
        i,j=np.clip(np.searchsorted(bq,[qa,qb],side='right')-1,0,len(bq)-1)
        pa=((qa-bq[i])/length[i])%1;pb=((qb-bq[j])/length[j])%1
        d=abs(pa-pb);penalty+=edge['weight']*min(d,1-d)
    return float(penalty)
