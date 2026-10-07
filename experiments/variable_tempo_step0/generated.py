"""Same-composition step-tempo music with independent coordinate verification."""

from __future__ import annotations

import argparse
from decimal import Decimal, localcontext, ROUND_HALF_UP
from fractions import Fraction
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf

from experiments.metronome_benchmark_v1.generated_controls import voice
from .common import write_json

RATE = 32000
LEAD = Fraction(137, 1000)
CASES = {
    "step": [(130, 64), (140, 64)],
    "return": [(130, 96), (140, 32), (130, 32)],
    "large": [(120, 64), (150, 32), (120, 32)],
    "octave": [(160, 64), (80, 64)],
    "small": [(120, 128), (Fraction(481, 4), 128)],
    "short_bar": [(130, 64), (140, 4), (130, 64)],
    "silent_change": [(130, 64), (140, 64)],
    "fixed": [(120, 128)],
    "fixed_gap": [(120, 128)],
    "fixed_fill": [(120, 128)],
}


def frac(value):
    value = Fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator}


def unpack(value):
    return Fraction(value["numerator"], value["denominator"])


def renderer_time(quarter, segments):
    t = LEAD
    used = Fraction(0)
    for bpm, length in segments:
        take = min(max(Fraction(quarter) - used, 0), length)
        t += take * 60 / Fraction(bpm)
        used += length
    return t


def reference_time(quarter, clock):
    """Separate decimal integration of authored segments, not renderer/grid calls."""
    with localcontext() as context:
        context.prec = 50
        lead = clock["lead_fraction"]
        t = Decimal(lead["numerator"]) / Decimal(lead["denominator"])
        q = Decimal(str(quarter))
        used = Decimal(0)
        for segment in clock["segments"]:
            rate = segment["bpm_fraction"]
            bpm = Decimal(rate["numerator"]) / Decimal(rate["denominator"])
            length = Decimal(segment["quarters"])
            take = min(max(q - used, Decimal(0)), length)
            t += take * Decimal(60) / bpm
            used += length
        return t


def composition(seed, quarters, variant):
    roots = [40 + seed % 5, 43 + seed % 5, 38 + seed % 5, 45 + seed % 5]
    events = []
    def add(q, kind, pitch=36, gain=1):
        q = Fraction(q)
        if variant == "silent_change" and 60 <= q < 68:
            return
        if variant == "fixed_gap" and 48 <= q < 64:
            return
        events.append((q, kind, pitch, gain))
    for q in range(quarters):
        beat, bar = q % 4, q // 4
        root = roots[(bar // 2) % 4]
        fill = variant == "fixed_fill" and 56 <= q < 64
        if fill:
            for sub in range(4):
                add(Fraction(q) + Fraction(sub, 4), "snare", gain=.4 + .12 * sub)
        else:
            add(q, "kick" if beat in (0, 2) else "snare", gain=1 if beat == 0 else .7)
        add(q, "bass", root + (7 if beat % 2 else 0), .55 if beat == 0 else .3)
        for sub in range(2):
            add(Fraction(q) + Fraction(sub, 2), "hat", gain=.5 if sub == 0 else .25)
        if beat == 0:
            for pitch in (root + 24, root + 27, root + 31):
                add(q, "chord", pitch, .38)
        if beat % 2 == 0:
            add(q, "chord", root + 36 + [0, 3, 7][(beat // 2 + bar) % 3], .15)
    return events


def render(root, ident, seed, variant):
    segments = CASES[variant]
    quarters = sum(length for _, length in segments)
    duration = renderer_time(quarters, segments) + 1
    frames = math.ceil(duration * RATE)
    music = np.zeros(frames)
    marker = np.zeros(frames)
    rng = np.random.default_rng(seed)
    ledger = []
    for q, kind, pitch, gain in composition(seed, quarters, variant):
        value = renderer_time(q, segments) * RATE
        whole, rest = divmod(value.numerator, value.denominator)
        frame = whole + int(2 * rest >= value.denominator)
        signal = voice(kind, pitch, gain, rng)
        end = min(frames, frame + len(signal))
        music[frame:end] += signal[:end - frame]
        ledger.append({"quarter_fraction": frac(q), "frame": frame, "voice": kind, "pitch": pitch})
    for q in range(quarters):
        marker[round(renderer_time(q, segments) * RATE)] = .8
    music *= .85 / max(float(np.max(abs(music))), 1e-12)
    directory = root / "inputs" / ident
    directory.mkdir(parents=True, exist_ok=False)
    sf.write(directory / "music.wav", music, RATE, subtype="PCM_24")
    sf.write(directory / "transport-marker.wav", marker, RATE, subtype="PCM_24")
    clock = {"schema_version": 1, "id": ident, "composition_seed": seed,
             "parent_group": f"step0_composition:{seed}", "variant": variant,
             "segments": [{"bpm_fraction": frac(bpm), "quarters": length} for bpm, length in segments],
             "lead_fraction": frac(LEAD), "meter": {"numerator": 4, "denominator": 4},
             "sample_rate": RATE, "sample_frames": frames, "total_quarters": quarters,
             "model_receives_transport_marker": False, "latency_changing_postprocessing": False,
             "reference_tier": "tier1_exact_constructed_transport", "perceptual_uniqueness_certified": False}
    write_json(directory / "clock.json", clock)
    write_json(directory / "event-ledger.json", {"events": ledger})
    reference_quarters = [float(reference_time(q, clock)) for q in range(quarters)]
    reference_bars = [float(reference_time(q, clock)) for q in range(0, quarters, 4)]
    marker_data, marker_rate = sf.read(directory / "transport-marker.wav")
    actual = np.flatnonzero(abs(marker_data) > .4)
    expected = np.array([int((reference_time(q, clock) * RATE).to_integral_value(rounding=ROUND_HALF_UP)) for q in range(quarters)])
    marker_error = int(np.max(abs(actual - expected))) if len(actual) == len(expected) else frames
    event_error = max(abs(e["frame"] - int((reference_time(float(unpack(e["quarter_fraction"])), clock) * RATE)
                    .to_integral_value(rounding=ROUND_HALF_UP))) for e in ledger)
    if marker_rate != RATE or marker_error > 1 or event_error > 1:
        raise ValueError("Constructed transport failed independent decimal coordinate checks")
    authored, q0 = [], 0
    for bpm, length in segments:
        authored.append({"quarter": q0, "time_seconds": float(reference_time(q0, clock)), "bpm_quarter": float(bpm)})
        q0 += length
    support = [[float(LEAD), float(reference_time(quarters, clock))]]
    ref = {"id": ident, "tempo_events": authored,
           "meter_events": [{"time_seconds": float(LEAD), "numerator": 4, "denominator": 4}],
           "quarter_beats_seconds": reference_quarters, "downbeats_seconds": reference_bars,
           "support_seconds": support, "absolute_audio_origin_verified": True,
           "coordinate_bound_ms": 1000 / RATE, "independent_real_producer_clock": False,
           "expected_unknown_intervals": [[float(reference_time(60, clock)), float(reference_time(68, clock))]]
           if variant == "silent_change" else [[float(reference_time(48, clock)), float(reference_time(64, clock))]]
           if variant == "fixed_gap" else []}
    write_json(root / "references" / f"{ident}.json", ref)
    write_json(directory / "origin-verification.json", {"marker_frame_error": marker_error,
               "music_ledger_frame_error": event_error, "bound_ms": 1000 / RATE,
               "independent_decimal_integration": True, "marker_never_model_input": True})
    click = np.zeros(frames)
    tone_t = np.arange(round(.015 * RATE)) / RATE
    for q, t in enumerate(reference_quarters):
        begin = round(t * RATE)
        signal = .3 * np.sin(2 * np.pi * (1900 if q % 4 == 0 else 1300) * tone_t) * np.exp(-tone_t / .003)
        click[begin:begin + len(signal)] += signal
    sf.write(directory / "music-with-click.wav", music * .8 + click, RATE, subtype="PCM_24")
    return {"id": ident, "audio_path": str((directory / "music.wav").resolve()),
            "sample_rate": RATE, "sample_frames": frames, "channels": 1,
            "duration_seconds": frames / RATE}, {"id": ident, "variant": variant,
            "parent_group": clock["parent_group"], "role": "calibration" if seed == 5100 else "diagnostic",
            "reference_path": str((root / "references" / f"{ident}.json").resolve()),
            "support_seconds": support, "reference_tier": clock["reference_tier"]}


def listening(root, rows):
    import html
    lines = ["<!doctype html><html lang='en'><meta charset='utf-8'><title>Step 0 constructed music</title>",
             "<style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;background:#101820;color:#e4edf2}section{padding:18px;border-bottom:1px solid #40505e}audio{width:100%;margin:8px 0}a{color:#79d5e8}</style>",
             "<h1>Constructed step-tempo music</h1><p>Listen for musical plausibility. The authored transport remains ground truth. Listening does not tune the estimator.</p>"]
    for row in rows:
        ident = row["id"]
        clock = read_clock(root, ident)
        rates = " → ".join(str(float(unpack(s["bpm_fraction"]))) for s in clock["segments"])
        lines += [f"<section><h2>{html.escape(ident)}</h2><p>{html.escape(rates)} BPM · 4/4</p>",
                  f"<p>Music</p><audio controls preload='none' src='inputs/{ident}/music.wav'></audio>",
                  f"<p>Music with authored click</p><audio controls preload='none' src='inputs/{ident}/music-with-click.wav'></audio></section>"]
    lines.append("<script>document.addEventListener('play',e=>{for(const a of document.querySelectorAll('audio'))if(a!==e.target)a.pause()},true)</script></html>")
    (root / "index.html").write_text("\n".join(lines), encoding="utf-8")


def read_clock(root, ident):
    return json.loads((root / "inputs" / ident / "clock.json").read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new constructed corpus directory")
    sources, references = [], []
    for seed in (5100, 5101, 5102):
        for variant in CASES:
            ident = f"step0_{seed}_{variant}"
            source, reference = render(args.output, ident, seed, variant)
            sources.append(source)
            references.append(reference)
            print("RENDER " + ident, flush=True)
    write_json(args.output / "source-inputs.json", {"schema_version": 1, "samples": sources})
    write_json(args.output / "admission.json", {"rows": references, "selected_before_inference": True})
    write_json(args.output / "corpus.json", {"count": len(sources), "parent_compositions": 3,
               "tempo_cases_per_parent": len(CASES), "sources_exclude_markers_and_reference_clicks": True})
    listening(args.output, references)


if __name__ == "__main__":
    main()
