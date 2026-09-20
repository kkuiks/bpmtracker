"""Fit a continuous, piecewise constant pulse clock to a proposed event sequence.

The input must represent consecutive pulses at one interpretation level. Musical
quarter-note level and meter remain unresolved; this fitter does not infer them.
No reference annotations are consumed. This is an offline experimental proposal.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from inspect_inputs import sha256
from run_beat_this import validate_events


def event_indices(times, pulse_indices=None):
    x = np.arange(len(times), dtype=float) if pulse_indices is None else np.asarray(pulse_indices, dtype=float)
    if x.ndim != 1 or len(x) != len(times) or not np.isfinite(x).all():
        raise ValueError('pulse indices must be finite and match event count')
    if len(x) and (x[0] != 0 or np.any(np.diff(x) < 1) or np.any(x != np.rint(x))):
        raise ValueError('pulse indices must start at zero and increase by whole pulses')
    return x


def propose_splits(times, min_events=8, split_penalty=0.01, pulse_indices=None):
    """Penalized least-squares segmentation; penalty has units of seconds squared."""
    times = validate_events(times)
    if min_events < 3 or len(times) < min_events:
        raise ValueError("need at least min_events >= 3 consecutive events")
    if not np.isfinite(split_penalty) or split_penalty <= 0:
        raise ValueError("split_penalty must be finite and positive")
    x = event_indices(times, pulse_indices)
    y = times - times[0]
    sums = [np.r_[0, np.cumsum(v)] for v in (x, y, x*x, x*y, y*y)]
    costs = np.full(len(y) + 1, np.inf)
    costs[0] = 0
    previous = np.zeros(len(y) + 1, dtype=int)
    for end in range(min_events, len(y) + 1):
        starts = np.arange(end - min_events + 1)
        count = end - starts
        sx, sy, sxx, sxy, syy = [s[end] - s[starts] for s in sums]
        xx = sxx - sx*sx/count
        xy = sxy - sx*sy/count
        residual = np.maximum(0, syy - sy*sy/count - xy*xy/xx)
        candidates = costs[starts] + residual + split_penalty
        best = int(np.argmin(candidates))
        costs[end], previous[end] = candidates[best], starts[best]
    boundaries = [len(y)]
    while boundaries[-1]:
        boundaries.append(int(previous[boundaries[-1]]))
    return list(reversed(boundaries))


def design_matrix(x, knots):
    return np.column_stack([np.ones_like(x), x] + [np.maximum(0, x-k) for k in knots])


def solve_clock(x, times, knots, robust=False):
    matrix = design_matrix(x, knots)
    weights = np.ones(len(x))
    for _ in range(6 if robust else 1):
        root = np.sqrt(weights)
        coefficients = np.linalg.lstsq(matrix * root[:, None], times * root, rcond=None)[0]
        residual = times - matrix @ coefficients
        # Huber IRLS; 20 ms is an explicit event-jitter scale, not a confidence.
        weights = np.minimum(1., .020 / np.maximum(np.abs(residual), 1e-12))
    return coefficients, residual


def clock_time(pulse_indices, knots, coefficients):
    return design_matrix(np.asarray(pulse_indices, dtype=float), knots) @ coefficients


def refine_knots(x, centered, knots, min_events):
    knots = np.asarray(knots, dtype=float).copy()
    # Jointly refit slopes/phase while refining each knot. Continuity is built
    # into the hinge basis, so no independent segment clock is spliced in.
    for radius in (4., 2., .5, .125, .03125):
        for _ in range(2):
            for i in range(len(knots)):
                low = (knots[i-1] + min_events) if i else x[min_events-1]
                high = (knots[i+1] - min_events) if i+1 < len(knots) else x[-min_events]
                choices = np.unique(np.clip(knots[i] + np.linspace(-radius, radius, 17), low, high))
                objectives = []
                for candidate in choices:
                    trial = knots.copy()
                    trial[i] = candidate
                    _, residual = solve_clock(x, centered, trial)
                    objectives.append(float(residual @ residual))
                knots[i] = choices[int(np.argmin(objectives))]
    return knots


def select_continuous_knots(x, centered, knots, min_events, split_penalty):
    """Bounded add/remove search using the continuous clock objective.

Independent line segmentation can explain a brief tempo excursion with an
impossible phase jump. Reconsider its knot count after enforcing continuity.
This bounded local search is not claimed to be a globally optimal segmentation.
"""
    for _ in range(3):
        _, residual = solve_clock(x, centered, knots)
        current = float(residual @ residual) + split_penalty*len(knots)
        proposals = []
        for location in np.arange(x[min_events-1], x[-min_events]+1, dtype=float):
            if len(knots) and np.min(np.abs(knots-location)) < min_events:
                continue
            candidate = np.sort(np.r_[knots, location])
            _, r = solve_clock(x, centered, candidate)
            proposals.append((float(r @ r)+split_penalty*len(candidate), candidate))
        for index in range(len(knots)):
            candidate = np.delete(knots, index)
            _, r = solve_clock(x, centered, candidate)
            proposals.append((float(r @ r)+split_penalty*len(candidate), candidate))
        best_cost, best = current, knots
        for _, candidate in sorted(proposals, key=lambda p: p[0])[:3]:
            candidate = refine_knots(x, centered, candidate, min_events)
            _, r = solve_clock(x, centered, candidate)
            cost = float(r @ r)+split_penalty*len(candidate)
            if cost < best_cost-1e-10:
                best_cost, best = cost, candidate
        if best is knots:
            break
        knots = best
    return knots


def fit_clock(times, min_events=8, split_penalty=0.01, continuous_selection=False, pulse_indices=None):
    times = validate_events(times)
    x = event_indices(times, pulse_indices)
    boundaries = propose_splits(times, min_events, split_penalty, x)
    # Center source times for numerical stability; retain their absolute origin.
    centered = times - times[0]
    knots = np.asarray([(x[b-1]+x[b])/2 for b in boundaries[1:-1]])
    knots = refine_knots(x, centered, knots, min_events)
    if continuous_selection:
        knots = select_continuous_knots(x, centered, knots, min_events, split_penalty)
    coefficients, residual = solve_clock(x, centered, knots, robust=True)
    coefficients[0] += times[0]
    slopes = np.cumsum(np.r_[coefficients[1], coefficients[2:]])
    if np.any(slopes <= 0):
        raise ValueError("fitted clock runs backwards; event indexing is not usable")
    intervals = np.diff(times) / np.diff(x)
    suspicious = []
    for i, interval in enumerate(intervals):
        local = np.median(intervals[max(0, i-8):i+9])
        if interval / local < .625 or interval / local > 1.6:
            suspicious.append(i)
    starts = np.r_[0, knots]
    ends = np.r_[knots, x[-1]]
    start_times = clock_time(starts, knots, coefficients)
    end_times = clock_time(ends, knots, coefficients)
    absolute = np.abs(residual)
    review = bool(suspicious or absolute.max() > .050)
    missing_pulses = int(x[-1] + 1 - len(x))
    status = 'event_indexing_or_fit_requires_review' if review else 'unreviewed_clock_proposal'
    if missing_pulses and not review:
        status = 'unreviewed_clock_with_missing_pulse_hypotheses'
    return {
        "status": status,
        "accepted": False, "pulse_unit": "input_event_interval; musical beat unit unresolved",
        "meter": None, "parameters": {"min_events": min_events, "split_penalty_seconds_squared": split_penalty,
                                      "continuous_model_selection": continuous_selection},
        "resolution_warning": "Shorter or weakly supported tempo excursions can be missed; a low residual does not certify absence of changes.",
        "initial_segmentation_indices": boundaries, "knot_pulse_indices": knots.tolist(),
        "coefficients": coefficients.tolist(), "input_event_count": len(times),
        "input_pulse_indices": x.tolist(), "pulse_index_span": [0, float(x[-1])],
        "support_seconds": [float(times[0]), float(times[-1])],
        "segments": [{"start_pulse": float(a), "end_pulse": float(b),
                      "start_seconds": float(t0), "end_seconds": float(t1),
                      "pulse_rate_per_minute": float(60/slope)}
                     for a,b,t0,t1,slope in zip(starts, ends, start_times, end_times, slopes)],
        "diagnostics": {"event_fit_residual_ms_p50_p95_max": (1000*np.quantile(absolute, [.5,.95,1])).tolist(),
                        "suspicious_interval_indices": suspicious, "inferred_missing_pulse_count": missing_pulses,
                        "accuracy_metrics": None},
    }


def grid_events(proposal, pulses_per_input_pulse=1):
    if pulses_per_input_pulse not in (.5, 1, 2):
        raise ValueError("supported explicit pulse interpretations are 0.5, 1 and 2")
    last = proposal.get('pulse_index_span', [0, proposal['input_event_count']-1])[1]
    x = np.arange(0, last + 1e-9, 1 / pulses_per_input_pulse)
    events = clock_time(x, proposal["knot_pulse_indices"], proposal["coefficients"])
    # Fitting can move the first event slightly across zero. Never wrap a click.
    return events[events >= 0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True, help="JSON containing beats_seconds")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-events", type=int, default=8)
    parser.add_argument("--split-penalty", type=float, default=.01)
    parser.add_argument("--continuous-selection", action="store_true", help="experimental bounded knot-count refinement")
    parser.add_argument("--audio", type=Path, help="optional preview using unchanged source time")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    event_input = json.loads(args.events.read_text())
    events = event_input["beats_seconds"]
    started = time.perf_counter()
    proposal = fit_clock(events, args.min_events, args.split_penalty, args.continuous_selection)
    proposal["fit_seconds"] = time.perf_counter() - started
    proposal["input_events_sha256"] = sha256(args.events)
    proposal["fitter_sha256"] = sha256(__file__)
    proposal["reference_used_for_fitting"] = False
    proposal["reference_alignment"] = "unverified"
    proposal["source_audio"] = event_input.get("audio")
    proposal["interpretations"] = [
        {"pulses_per_input_pulse": factor,
         "segment_rates_per_minute": [s["pulse_rate_per_minute"] * factor for s in proposal["segments"]],
         "selected": False, "meter": None}
        for factor in (.5, 1, 2)
    ]
    args.output_dir.mkdir(parents=True)
    if args.audio:
        import soundfile as sf
        from compare_decoders import write_preview
        audio_hash = sha256(args.audio)
        if proposal["source_audio"] and proposal["source_audio"]["sha256"] != audio_hash:
            parser.error("preview audio differs from event input provenance")
        audio, sr = sf.read(args.audio, dtype="float32", always_2d=True)
        if not np.isfinite(audio).all() or events[-1] >= len(audio)/sr:
            parser.error("audio must be finite and cover the input event sequence")
        proposal["preview_audio_sha256"] = audio_hash
        proposal["preview_source_verified_against_event_input"] = proposal["source_audio"] is not None
        proposal["preview_scope"] = "no downbeat accents; no extrapolation before/after event support"
        for factor in (1, 2):
            target = args.output_dir / f"pulse-x{factor}"
            target.mkdir()
            preview = write_preview(target, grid_events(proposal, factor), [], audio, sr)
            proposal[f"preview_x{factor}"] = preview
    (args.output_dir / "clock.json").write_text(json.dumps(proposal, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": proposal["status"], "segments": proposal["segments"],
                      "diagnostics": proposal["diagnostics"], "fit_seconds": proposal["fit_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
