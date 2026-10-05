"""Explicit observer variants and acoustic-event controls."""
import numpy as np

from . import model


def predict(features,base,energy,package,*,event_policy='learned',**kwargs):
    if event_policy not in ('learned','frozen'):
        raise ValueError('unknown event policy')
    if package.get('model_variant')=='cadence_relative':
        from .cadence_model import predict as selected
        fields=selected(features,base,energy,package,**kwargs)
    else:
        fields=model.predict(features,base,energy,package,**kwargs)
    if event_policy=='frozen':
        probabilities=1/(1+np.exp(-np.clip(base,-30,30)))
        fields=dict(fields,quarter=probabilities[:,0],bar=probabilities[:,1])
    return fields


def model_filename(package):
    return 'cadence_model.py' if package.get('model_variant')=='cadence_relative' else 'model.py'
