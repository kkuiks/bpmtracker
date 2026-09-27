"""Independent spectral-flux evidence and explicit conditional grid refinement.

This does not identify musical quarter notes or downbeats. Transient alignment
is a diagnostic: a nearby instrument attack is not necessarily the correct beat.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from fit_clock import fit_clock, grid_events
from inspect_inputs import sha256


def spectral_flux(audio, sample_rate, analysis_rate=22050, hop=110, fft_size=1024):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("audio must be nonempty and finite")
    if sample_rate != analysis_rate:
        audio = soxr.resample(audio, sample_rate, analysis_rate, quality="HQ")
    padded = np.pad(audio, (fft_size//2, fft_size//2))
    windows = np.lib.stride_tricks.sliding_window_view(padded, fft_size)[::hop]
    frequencies = np.fft.rfftfreq(fft_size, 1/analysis_rate)
    bands = [(frequencies >= low) & (frequencies < high) for low,high in [(30,200),(200,2000),(2000,10000)]]
    features = []
    previous = np.zeros(fft_size//2+1)
    hann = np.hanning(fft_size)
    for start in range(0, len(windows), 1024):
        spectrum = np.log1p(10*np.abs(np.fft.rfft(windows[start:start+1024]*hann, axis=1)))
        difference = np.maximum(0, np.diff(np.vstack([previous, spectrum]), axis=0))
        features.append(np.column_stack([difference[:,mask].mean(axis=1) for mask in bands]))
        previous = spectrum[-1]
    features = np.concatenate(features)
    scale = np.quantile(features, .9, axis=0)
    normalized = np.minimum(features / np.maximum(scale, 1e-8), 8.)
    return np.arange(len(features))*hop/analysis_rate, normalized


def periodicity_candidates(times, features, window_seconds=24., step_seconds=6., min_rate=40., max_rate=300.):
    signal = features.mean(axis=1)
    fps = 1/(times[1]-times[0])
    windows = []
    for center in np.arange(window_seconds/2, times[-1]-window_seconds/2, step_seconds):
        subset = signal[(times >= center-window_seconds/2) & (times < center+window_seconds/2)]
        weights = np.hanning(len(subset))
        centered = (subset - np.sum(subset*weights)/np.sum(weights))*weights
        nfft = 2**int(np.ceil(np.log2(max(1, len(subset)*16))))
        amplitudes = np.abs(np.fft.rfft(centered, n=nfft)) / max(np.sum(np.abs(centered)), 1e-12)
        rates = np.fft.rfftfreq(nfft, 1/fps)*60
        peaks = np.flatnonzero((amplitudes[1:-1] > amplitudes[:-2]) & (amplitudes[1:-1] >= amplitudes[2:]))+1
        peaks = peaks[(rates[peaks]>=min_rate)&(rates[peaks]<=max_rate)]
        selected = []
        for peak in sorted(peaks, key=lambda p: -amplitudes[p]):
            if all(abs(rates[peak]/rates[old]-1) > .02 for old in selected):
                selected.append(peak)
            if len(selected) == 5:
                break
        windows.append({"center_seconds": float(center), "candidates": [
            {"rate_per_minute": float(rates[p]), "normalized_fourier_amplitude": float(amplitudes[p])} for p in selected]})
    return windows


def nearby_attacks(times, features, grid, radius_seconds=.035):
    """Pick nearby maxima, retaining the declared bound and positive-time mapping."""
    signal = features.mean(axis=1)
    refined, strengths = [], []
    for event in grid:
        left, right = np.searchsorted(times, [event-radius_seconds, event+radius_seconds])
        if right <= left:
            refined.append(float(event))
            strengths.append(0.)
            continue
        index = left + int(np.argmax(signal[left:right]))
        refined.append(float(times[index]) if signal[index] > 1e-8 else float(event))
        strengths.append(float(signal[index]))
    return np.asarray(refined), np.asarray(strengths)


def rank_periodic_levels(windows, clock):
    """Rank observed periodicities, never equating strongest subdivision with meter."""
    evidence = []
    for factor in (.5, 1, 2):
        support, strongest = [], []
        for window in windows:
            segment = next((s for s in clock["segments"] if s["start_seconds"] <= window["center_seconds"] < s["end_seconds"]), None)
            if segment is None:
                continue
            expected = segment["pulse_rate_per_minute"] * factor
            # An unsearched frequency is absent evidence, not negative evidence.
            if not 40 <= expected <= 300:
                continue
            matches = [p for p in window["candidates"] if abs(p["rate_per_minute"]/expected-1) <= .03]
            support.append(max((p["normalized_fourier_amplitude"] for p in matches), default=0.))
            strongest.append(bool(window["candidates"] and abs(window["candidates"][0]["rate_per_minute"]/expected-1) <= .03))
        evidence.append({"pulses_per_input_pulse": factor, "eligible_window_count": len(support),
                         "mean_matched_periodicity_amplitude": float(np.mean(support)) if support else None,
                         "strongest_peak_match_fraction": float(np.mean(strongest)) if strongest else None})
    ranked = sorted(evidence, key=lambda item: -(item["mean_matched_periodicity_amplitude"] or 0))
    return {"ranking": ranked, "preferred_periodicity_factor": ranked[0]["pulses_per_input_pulse"] if (ranked[0]["mean_matched_periodicity_amplitude"] or 0) > 1e-8 else None,
            "musical_quarter_note_factor": None, "meter": None,
            "scope": "periodicity support only; repeated subdivisions can win; not calibrated confidence"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--clock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    audio, sr = sf.read(args.audio, dtype="float32", always_2d=True)
    if not np.isfinite(audio).all():
        parser.error("audio contains nonfinite samples")
    clock = json.loads(args.clock.read_text())
    if clock.get("preview_audio_sha256") and clock["preview_audio_sha256"] != sha256(args.audio):
        parser.error("audio does not match clock provenance")
    if clock["support_seconds"][-1] >= len(audio)/sr:
        parser.error("audio does not cover clock support")
    times, features = spectral_flux(audio, sr)
    report = {"audio_sha256": sha256(args.audio), "clock_sha256": sha256(args.clock), "runner_sha256": sha256(__file__),
              "feature_config": {"analysis_rate": 22050, "hop_samples": 110, "fft_size": 1024,
                                 "frame_origin": "centered STFT; zero source shift", "bands_hz": [[30,200],[200,2000],[2000,10000]]},
              "periodicity_windows": periodicity_candidates(times, features),
              "reference_used": False, "selected_pulse_interpretation": None,
              "accuracy_metrics": None, "conditional_refinements": {}}
    report["level_evidence"] = rank_periodic_levels(report["periodicity_windows"], clock)
    args.output_dir.mkdir(parents=True)
    np.savez_compressed(args.output_dir / "onsets.npz", time=times, features=features)
    for factor in (1,2):
        grid = grid_events(clock, factor)
        attacks, strength = nearby_attacks(times, features, grid)
        proposal = fit_clock(attacks)
        proposal["scope"] = "conditional nearby-transient fit; no independent beat labels; do not accept automatically"
        proposal["audio_sha256"] = report["audio_sha256"]
        proposal["source_clock_sha256"] = report["clock_sha256"]
        report["conditional_refinements"][str(factor)] = {
            "pulses_per_input_pulse": factor, "search_radius_seconds": .035,
            "attack_shift_ms_p05_p50_p95": (1000*np.quantile(attacks-grid, [.05,.5,.95])).tolist(),
            "fraction_at_search_edge": float(np.mean(np.abs(attacks-grid) >= .030)),
            "mean_feature_strength": float(strength.mean()), "clock": proposal,
        }
        (args.output_dir / f"attacks-x{factor}.json").write_text(json.dumps({"beats_seconds": attacks.tolist()}, indent=2)+"\n")
        (args.output_dir / f"clock-x{factor}.json").write_text(json.dumps(proposal, indent=2, allow_nan=False)+"\n")
    (args.output_dir / "analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(report["conditional_refinements"], indent=2))


if __name__ == "__main__":
    main()
