"""Conservative repeated short-bar proposal from source-only phrase and attack cues.

A 15-quarter motif can suggest one 3/4 bar per four-bar phrase. It does not
locate the bar by itself. This pilot uses broad-band attack agreement among
mix-derived sources and abstains unless that placement is well separated.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis_legacy"))
from music_map_contract import prepare_map, render_bars

from .constant_grid import _probability
from .diagnose_short_bar_candidates import low_frequency_attacks
from .tempo_segments import _sample


BANDS_HZ = ((60, 600), (80, 1200), (100, 2000))
RADII_SECONDS = (.03, .05, .07)
STEMS = ("mix", "drums", "bass", "other")
MIN_PHRASE_SCORE = .85
MIN_PHRASE_CONTRAST = .15
MIN_EARLY_PHASE_MARGIN = .25
MIN_CANDIDATE_MARGIN_Z = .30
MIN_VIEW_WIN_FRACTION = .5


def phrase15_trigger(phrase_scores):
    needed = ("lag14", "lag15", "lag16")
    if any(name not in phrase_scores or len(phrase_scores[name]) == 0 for name in needed):
        raise ValueError("neighboring phrase-length scores required")
    values = {name: float(phrase_scores[name][0]) for name in needed}
    if not all(np.isfinite(list(values.values()))):
        raise ValueError("finite phrase scores required")
    contrast = values["lag15"] - max(values["lag14"], values["lag16"])
    return (values["lag15"] >= MIN_PHRASE_SCORE and contrast >= MIN_PHRASE_CONTRAST,
            {**values, "contrast": float(contrast)})


def _starts(first_short):
    starts = [0]
    pulse = 0
    for bar in range(11):
        pulse += 3 if bar in (first_short, first_short+4) else 4
        starts.append(pulse)
    return starts


def propose_repeated_short_bars(final1, downbeat_logits, fps, phrase_scores,
                                source_paths):
    """Return (candidate, diagnostic); candidate is None if evidence is weak.

    ``source_paths`` supplies mix and three mix-derived stems keyed by STEMS.
    It is needed only when the 15-quarter phrase gate fires.
    """
    active, phrase = phrase15_trigger(phrase_scores)
    diag = {"source_only": True, "phrase15": phrase, "triggered": active,
            "accepted": False, "reason": None,
            "bands_hz": BANDS_HZ, "radii_seconds": RADII_SECONDS,
            "stems": STEMS, "minimum_phrase_score": MIN_PHRASE_SCORE,
            "minimum_phrase_contrast": MIN_PHRASE_CONTRAST,
            "minimum_early_phase_margin": MIN_EARLY_PHASE_MARGIN,
            "minimum_candidate_margin_z": MIN_CANDIDATE_MARGIN_Z,
            "minimum_view_win_fraction": MIN_VIEW_WIN_FRACTION}
    if not active:
        diag["reason"] = "no_distinct_fifteen_quarter_phrase"
        return None, diag
    grid = np.asarray(final1["beat_times_seconds"], dtype=float)
    if len(grid) < 44 or np.any(np.diff(grid) <= 0):
        raise ValueError("full ordered quarter grid required")
    down = _probability(downbeat_logits)
    first = _sample(down, fps, grid[:12])
    phases = [float(first[k::4].mean()) for k in range(4)]
    rank = np.argsort(-np.asarray(phases))
    margin = phases[rank[0]] - phases[rank[1]]
    diag["early_phase_scores"] = phases
    diag["early_phase_margin"] = float(margin)
    if rank[0] != 0 or margin < MIN_EARLY_PHASE_MARGIN:
        diag["reason"] = "unsupported_initial_bar_phase"
        return None, diag
    if set(source_paths) != set(STEMS):
        raise ValueError("mix, drums, bass and other source paths required")
    candidate_indices = [np.asarray([i for i in _starts(j) if i < 44],dtype=int)
                         for j in range(1,7)]
    evidence = []
    geometry = {}
    for stem in STEMS:
        geometry[stem] = []
        for low, high in BANDS_HZ:
            for radius in RADII_SECONDS:
                strength, details = low_frequency_attacks(
                    source_paths[stem], grid[:44],
                    seconds=float(grid[43]+.1), low=low, high=high,
                    radius=radius)
                if (details["sample_rate"] != final1["map"]["source"]["sample_rate"] or
                        details["sample_frames"] != final1["map"]["source"]["sample_frames"]):
                    raise ValueError("all separated sources must share the finished-mix clock")
                means = np.asarray([strength[indices].mean()
                                    for indices in candidate_indices])
                spread = float(means.std())
                z = (means-means.mean())/(spread+1e-12)
                evidence.append({"stem":stem,"band_hz":[low,high],
                                 "radius_seconds":radius,
                                 "scores":means.tolist(),"z_scores":z.tolist(),
                                 "winner":int(np.argmax(means))+1})
                geometry[stem].append(details)
    z_means = np.asarray([row["z_scores"] for row in evidence]).mean(axis=0)
    choice = np.argsort(-z_means)
    votes = sum(row["winner"] == int(choice[0])+1 for row in evidence)
    margin = float(z_means[choice[0]]-z_means[choice[1]])
    diag.update({"candidate_first_short_bar_indices":list(range(1,7)),
                 "candidate_bar_starts_first44":[x.tolist() for x in candidate_indices],
                 "candidate_mean_z_scores":z_means.tolist(),
                 "selected_first_short_bar_index":int(choice[0])+1,
                 "candidate_margin_z":margin,"view_win_count":votes,
                 "view_count":len(evidence),"evidence":evidence,
                 "feature_geometry":geometry})
    if margin < MIN_CANDIDATE_MARGIN_Z or votes/len(evidence) < MIN_VIEW_WIN_FRACTION:
        diag["reason"] = "weak_multiview_short_bar_consensus"
        return None, diag
    selected = int(choice[0])+1
    starts = _starts(selected)
    result = deepcopy(final1)
    result["map"]["bar_anchor_pulse"] = 0.0
    def event(pulse, numerator):
        return {"pulse":float(pulse),"numerator":numerator,"denominator":4,
                "grouping":[1]*numerator,"bar_action":"continue"}
    result["map"]["meter_events"] = [
        event(0,4),event(starts[selected],3),event(starts[selected+1],4),
        event(starts[selected+4],3),event(starts[selected+5],4)]
    prepared = prepare_map(result["map"])
    bars = render_bars(prepared)
    if bars["status"] != "rendered":
        raise ValueError("selected map cannot render bars")
    result["bar_starts_seconds"] = bars["bar_events_seconds"]
    result["diagnostics"]["constant_grid_only"] = False
    diag["accepted"] = True
    diag["reason"] = "repeated_short_bar_consensus"
    result["diagnostics"]["phrase_meter"] = diag
    return result, diag
