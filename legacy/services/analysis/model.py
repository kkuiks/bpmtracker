"""Supervised chronological event model; no meter grammar or path ranking."""
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .timeline import DENOMINATORS


class ChronologicalModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.local = nn.Sequential(nn.Linear(516, 64), nn.GELU())
        self.context = nn.GRU(64, 64, num_layers=2, batch_first=True,
                              bidirectional=True, dropout=.1)
        self.output = nn.Linear(192, 4+len(DENOMINATORS))
        nn.init.zeros_(self.output.weight); nn.init.zeros_(self.output.bias)
        with torch.no_grad():self.output.bias[3] = np.log(120.)

    def forward(self, values, base):
        local = self.local(values)
        pooled = F.avg_pool1d(local.transpose(1, 2), 4, ceil_mode=True).transpose(1, 2)
        context, _ = self.context(pooled)
        context = F.interpolate(context.transpose(1, 2), size=local.shape[1],
                                mode='linear', align_corners=False).transpose(1, 2)
        logits = self.output(torch.cat([local, context], dim=-1))
        logits = torch.cat([logits[:, :, :2]+base, logits[:, :, 2:]], dim=-1)
        return logits


def feature_inputs(features, logits, energy):
    log_energy = np.log(np.maximum(energy, 1e-6))
    flux = np.maximum(0., np.diff(log_energy, prepend=log_energy[0]))
    return np.concatenate([features.astype(np.float32), logits, log_energy[:, None], flux[:, None]], axis=1).astype(np.float32)


def predict(features, base, energy, package, *, device='cpu', chunk_frames=4096, context_frames=1024):
    model = ChronologicalModel().to(device); model.load_state_dict(package['state_dict']); model.eval()
    x = feature_inputs(features, base, energy)
    x = (x-np.asarray(package['mean'], np.float32))/np.asarray(package['std'], np.float32)
    results = np.empty((len(x), 9), np.float32)
    with torch.inference_mode():
        for start in range(0, len(x), chunk_frames):
            stop = min(len(x), start+chunk_frames); lo = max(0, start-context_frames); hi = min(len(x), stop+context_frames)
            output = model(torch.from_numpy(x[lo:hi]).unsqueeze(0).to(device),
                           torch.from_numpy(base[lo:hi]).unsqueeze(0).to(device))[0].cpu().numpy()
            results[start:stop] = output[start-lo:stop-lo]
    weights = np.asarray(package['positive_weights'], np.float32)
    probabilities = 1/(1+np.exp(-np.clip(results[:, :3]-np.log(weights), -30, 30)))
    denominator = results[:, 4:]; denominator = np.exp(denominator-denominator.max(axis=1, keepdims=True)); denominator /= denominator.sum(axis=1, keepdims=True)
    return dict(quarter=probabilities[:, 0], bar=probabilities[:, 1], grid=probabilities[:, 2],
                quarter_bpm=np.exp(np.clip(results[:, 3], np.log(20.), np.log(500.))), denominator=denominator)
