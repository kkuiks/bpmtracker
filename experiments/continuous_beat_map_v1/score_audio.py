"""Scores the actual affine pieces of a continuous map against source peaks."""
from __future__ import annotations
import numpy as np
from .common import CONFIG

class AudioScore:
    def __init__(self, events):
        self.events = events; self.duration = float(events['duration'])
        self.channels = [(np.asarray(events[a], float), np.asarray(events[b], float)) for a,b in
            [('times','weights'), ('downbeat_times','downbeat_weights'), ('pcm_times','pcm_weights')]]

    def channel(self, channel, period, phase, left, right, sigma):
        period, phase, left, right = [np.atleast_1d(np.asarray(v, float)) for v in (period,phase,left,right)]
        period, phase, left, right = np.broadcast_arrays(period, phase, left, right)
        times, weights = self.channels[channel]
        left = np.maximum(0.,left); right = np.minimum(self.duration,right)
        lo = int(np.searchsorted(times, float(left.min())-1e-8))
        hi = int(np.searchsorted(times, float(right.max())+1e-8))
        obs, mass = times[lo:hi], weights[lo:hi]
        if not len(times) or not len(obs): return np.zeros(len(period))
        first = phase+np.ceil((left-phase-1e-8)/period)*period
        count = np.maximum(0, np.ceil((right-first-1e-8)/period).astype(int))
        ticks = first[:,None]+np.arange(int(count.max(initial=0)))[None,:]*period[:,None]
        valid = np.arange(ticks.shape[1])[None,:] < count[:,None]
        index = np.searchsorted(times, ticks)
        previous, following = np.clip(index-1,0,len(times)-1), np.clip(index,0,len(times)-1)
        values = np.maximum(weights[previous]*np.exp(-.5*((ticks-times[previous])/sigma)**2),
                            weights[following]*np.exp(-.5*((ticks-times[following])/sigma)**2))
        coverage = (values*valid).sum(axis=1)/np.maximum(count,1)
        residual = obs[None,:]-(phase[:,None]+np.rint((obs[None,:]-phase[:,None])/period[:,None])*period[:,None])
        use = (obs[None,:]>=left[:,None]-1e-8)&(obs[None,:]<right[:,None]-1e-8)
        explanation = (np.exp(-.5*(residual/sigma)**2)*mass[None,:]*use).sum(axis=1)/np.maximum((mass[None,:]*use).sum(axis=1),1e-9)
        return 2*coverage*explanation/np.maximum(coverage+explanation,1e-9)

    def batch(self, bpm, phase, numerator, denominator, left, right):
        bpm, phase, n, d, left, right = [np.atleast_1d(np.asarray(v,float)) for v in (bpm,phase,numerator,denominator,left,right)]
        bpm, phase, n, d, left, right = np.broadcast_arrays(bpm,phase,n,d,left,right)
        period = 60/bpm; neural = []
        for factor in CONFIG['pulse_factors']:
            value = self.channel(0,period/factor,phase,left,right,CONFIG['neural_sigma_seconds'])
            preferred = np.where((d==8)&(n%3==0), 2/3, np.where(d==2,.5,1.))
            cost = CONFIG['pulse_factor_cost']*abs(np.log2(factor/preferred))
            neural.append(value-cost)
        beat = np.maximum(0.,np.max(neural,axis=0))
        bar = self.channel(1,period*n*4/d,phase,left,right,CONFIG['neural_sigma_seconds'])
        pcm = self.channel(2,period*4/d,phase,left,right,CONFIG['pcm_sigma_seconds'])
        prior = np.array([CONFIG['meter_prior'][f'{int(a)}/{int(b)}'] for a,b in zip(n,d)])
        value = CONFIG['neural_beat_weight']*beat+CONFIG['neural_bar_weight']*bar+CONFIG['pcm_weight']*pcm-prior
        return value

    def one(self, bpm, phase, numerator, denominator, left, right):
        return float(self.batch([bpm],[phase],[numerator],[denominator],[left],[right])[0])
