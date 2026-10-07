"""Oracle fixed-clock support with explicit contradiction and information bands.

Only source evidence and a supplied rate/phase enter prediction. Sustained local
rhythmic evidence is required for contradiction; missing clicks are insufficient.
Phase contradiction and evidence for a different nominal rate stay separate.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import math
from pathlib import Path
import time

import numpy as np

from experiments.metronome_reconstruction_v1.grid import rational_pool
from experiments.metronome_reconstruction_v1.infer import make_evidence
from .common import SAMPLES, describe, digest, nearest_rate, read_json, write_json

UNKNOWN, MATCH, MISMATCH = 0, 1, 2
STATE_NAMES = {UNKNOWN: "UNKNOWN", MATCH: "MATCH", MISMATCH: "MISMATCH"}


def load_evidence(path, config):
    with np.load(path, allow_pickle=False) as data:
        if int(data["fps"]) != config["fps"]:
            raise ValueError("Observation frame rate differs")
        evidence = make_evidence(data["beat_logits"], data["downbeat_logits"], float(data["duration_seconds"]), config)
        if "silent_frame_mask" in data:
            silent = data["silent_frame_mask"].astype(bool)
            if silent.shape != evidence["channels"]["beat"]["probability"].shape:
                raise ValueError("Digital-silence and sensor axes differ")
            evidence["silent_intervals_seconds"] = data["silent_intervals_seconds"].copy()
        return evidence


def observable_channel(evidence, period):
    """Discard context-completed peaks only inside a whole-period silent run.

    Ordinary silence between audible beats is retained. One sensor frame at
    each edge allows timestamp quantization; no reference boundary is consulted.
    """
    channel = evidence["channels"]["beat"]
    events, weights = channel["events"], channel["weights"]
    keep = np.ones(len(events), dtype=bool)
    frame = 1 / evidence["fps"]
    for start, end in evidence.get("silent_intervals_seconds", []):
        if end - start >= period:
            keep &= ~((events >= start + frame) & (events < end - frame))
    return events[keep], weights[keep]


def source_fit(times, weights, fps, sigma):
    """Generic source-event fit with skipped indices, independent of oracle."""
    if len(times) < 4:
        return None
    seed = float(np.median(np.diff(times)))
    if seed <= 0:
        return None
    index = np.r_[0, np.cumsum(np.maximum(1, np.rint(np.diff(times) / seed)))].astype(float)
    w = weights.copy()
    for _ in range(3):
        total = w.sum()
        xmean, ymean = float(w @ index / total), float(w @ times / total)
        x, y = index - xmean, times - ymean
        sxx = float(w @ (x * x))
        if sxx <= 0:
            return None
        period = float((w * x) @ y / sxx)
        if period <= 0:
            return None
        residual = times - (ymean + period * x)
        w = weights * np.minimum(1, sigma / np.maximum(abs(residual), 1e-12))
    bpm = 60 / period
    if not 30 <= bpm <= 400:
        return None
    coherence = float(weights @ np.exp(-.5 * (residual / sigma) ** 2) / weights.sum())
    variance = max(float(weights @ (residual * residual) / weights.sum()), (1 / fps) ** 2 / 12)
    # This is an uncertainty proxy, not a calibrated musical correctness probability.
    source_sxx = max(float(weights @ (x * x)), 1e-12)
    period_error = math.sqrt(variance / source_sxx)
    # Frame rounding errors can be correlated, creating a staircase instead
    # of independent noise. Bound the weighted line slope for every event's
    # possible half-frame displacement; do not manufacture a precise rate.
    quantization_bound = .5 / fps * float(weights @ abs(x)) / source_sxx
    uncertainty = max(3 * period_error, quantization_bound)
    lower_period, upper_period = max(period - uncertainty, period / 4), period + uncertainty
    return {"nominal_bpm": float(nearest_rate(bpm)), "coherence": coherence,
            "bpm_low": 60 / upper_period, "bpm_high": 60 / lower_period}


def features(evidence, clock, span_quarters, step, config):
    period, phase = clock["period_seconds"], clock["phase_seconds"]
    events, weights = observable_channel(evidence, period)
    times = np.arange(0, evidence["duration"], step)
    values = {key: np.zeros(len(times)) for key in ("peak_count", "alignment", "occupancy", "coverage", "coherence",
                                                  "nominal_bpm", "fit_bpm_low", "fit_bpm_high")}
    sigma = config["residual_sigma_seconds"]
    for i, t in enumerate(times):
        lo, hi = max(0, t - span_quarters * period / 2), min(evidence["duration"], t + span_quarters * period / 2)
        first, last = np.searchsorted(events, [lo, hi])
        local, w = events[first:last], weights[first:last]
        values["peak_count"][i] = len(local)
        if not len(local):
            continue
        index = np.rint((local - phase) / period).astype(int)
        residual = local - (phase + index * period)
        reward = w * np.exp(-.5 * (residual / sigma) ** 2)
        order = np.lexsort((abs(residual), -reward, index))
        sorted_index = index[order]
        chosen = order[np.r_[True, sorted_index[1:] != sorted_index[:-1]]]
        values["alignment"][i] = float(reward[chosen].sum() / w.sum())
        grid_count = max(1, math.ceil((hi - phase) / period) - math.ceil((lo - phase) / period))
        values["occupancy"][i] = min(1, float(np.exp(-.5 * (residual[chosen] / sigma) ** 2).sum() / grid_count))
        values["coverage"][i] = float(np.ptp(local) / max(hi - lo, 1e-12))
        fit = source_fit(local, w, evidence["fps"], sigma)
        if fit:
            values["coherence"][i] = fit["coherence"]
            values["nominal_bpm"][i] = fit["nominal_bpm"]
            values["fit_bpm_low"][i], values["fit_bpm_high"][i] = fit["bpm_low"], fit["bpm_high"]
    digital_silence = np.zeros(len(times), dtype=bool)
    for start, end in evidence.get("silent_intervals_seconds", []):
        if end - start >= period:
            digital_silence |= (times >= start) & (times < end)
    return {"times": times, **values, "digital_silence": digital_silence}


def classify(values, clock, parameters):
    states = np.full(len(values["times"]), UNKNOWN, dtype=np.uint8)
    information = ((values["peak_count"] >= parameters["minimum_peaks"])
                   & (values["coherence"] >= parameters["coherence_floor"])
                   & (values["coverage"] >= parameters["coverage_floor"]))
    information &= ~values.get("digital_silence", np.zeros(len(states), dtype=bool))
    match_floor = max(parameters["alignment_match_floor"], parameters["alignment_mismatch_ceiling"])
    mismatch_ceiling = min(parameters["alignment_match_floor"], parameters["alignment_mismatch_ceiling"])
    states[information & (values["alignment"] >= match_floor) & (values["occupancy"] >= parameters["occupancy_floor"])] = MATCH
    states[information & (values["alignment"] <= mismatch_ceiling)] = MISMATCH
    pool = np.array([float(value) for value in rational_pool(30, 400, 4)])
    rate = float(nearest_rate(clock["quarter_bpm"]))
    index = int(np.argmin(abs(pool - rate)))
    cell_low = (pool[index - 1] + rate) / 2 if index else 30
    cell_high = (pool[index + 1] + rate) / 2 if index + 1 < len(pool) else 400
    different = abs(values["nominal_bpm"] - rate) > 1e-9
    uncertainty_excludes_cell = (values["fit_bpm_high"] < cell_low) | (values["fit_bpm_low"] > cell_high)
    change = (states == MISMATCH) & different & uncertainty_excludes_cell
    return states, change


def runs(mask, times, step):
    mask = np.asarray(mask, dtype=bool)
    starts = np.flatnonzero(mask & ~np.r_[False, mask[:-1]])
    ends = np.flatnonzero(mask & ~np.r_[mask[1:], False])
    return [{"start_seconds": float(times[a]), "end_seconds": float(times[b] + step),
             "duration_seconds": float((b - a + 1) * step)} for a, b in zip(starts, ends)]


def calibrate(run, output, model, protocol, fixed_library=False, fixed_development=False):
    rows = [r for r in read_json(run / "oracle-admission.json")["rows"]
            if r["role"] == "calibration" and r["variant"] in {"fixed", "fixed_gap", "fixed_fill"}]
    calibration = []
    for row in rows:
        ident = row["id"]
        calibration.append({"id": ident, "evidence": run / "original/evidence" / f"{ident}.npz",
                            "clock": read_json(run / "oracle-clocks" / f"{ident}.json")["clocks"][0]})
    if fixed_library:
        corpus = SAMPLES / "external/generated-clock-contrast-v1"
        cache = SAMPLES / "experiments/metronome_benchmark_v1/20261007-generated58-frozen-v1/evidence"
        for index in (4, 5, 6, 7):
            for variant in ("straight", "weak_downbeat", "dropout", "leading_shift"):
                ident = f"control{index:02d}_{variant}"
                ref = read_json(corpus / "references" / f"{ident}.json")
                calibration.append({"id": "existing_" + ident, "evidence": cache / f"{ident}.npz",
                                    "clock": {"quarter_bpm": ref["quarter_bpm"], "period_seconds": ref["period_seconds"],
                                              "phase_seconds": ref["offset_seconds"] % ref["period_seconds"]}})
    if fixed_development:
        for row in read_json(run / "negative-controls/oracle-inputs.json")["rows"]:
            if row["role"] == "development":
                calibration.append({"id": row["id"], "evidence": Path(row["evidence_path"]),
                                    "clock": next(c for c in row["clocks"] if c["clock_id"] == "annotation_fit_oracle")})
    write_json(output / "calibration-protocol.json", {"ids": [item["id"] for item in calibration],
               "fixed_library_added": fixed_library, "real_variable_labels_used": False,
               "fixed_development_added": fixed_development, "validation_used_for_calibration": False,
               "reason": "Compare constructed-only calibration with fixed development observations, whose timing and phase distributions differ. No real-variable support scores select these bands.",
               "comparison_original_calibration_preserved": True, "source_sha256": digest(Path(__file__))})
    parameters, distributions = {}, {}
    for span in protocol["support_diagnostic"]["span_quarters_sweep"]:
        true_values, wrong_values = [], []
        for row in calibration:
            evidence = load_evidence(row["evidence"], model)
            clock = row["clock"]
            values = features(evidence, clock, span, .1, model)
            usable = values["peak_count"] >= 4
            true_values.append({key: value[usable] for key, value in values.items() if key != "times"})
            for scale in (.9, 1.1):
                bpm = float(nearest_rate(clock["quarter_bpm"] * scale))
                if not 30 <= bpm <= 400:
                    continue
                wrong = {**clock, "quarter_bpm": bpm, "period_seconds": 60 / bpm}
                alternative = features(evidence, wrong, span, .1, model)
                wrong_values.append(alternative["alignment"][alternative["peak_count"] >= 4])
        combined = {key: np.concatenate([item[key] for item in true_values]) for key in true_values[0]}
        wrong = np.concatenate(wrong_values)
        parameters[str(span)] = {"minimum_peaks": 4, "alignment_match_floor": float(np.quantile(combined["alignment"], .05)),
            "alignment_mismatch_ceiling": float(np.quantile(wrong, .95)),
            "coherence_floor": float(np.quantile(combined["coherence"], .05)),
            "coverage_floor": float(np.quantile(combined["coverage"], .05)),
            "occupancy_floor": float(np.quantile(combined["occupancy"], .05))}
        distributions[str(span)] = {"true_alignment": describe(combined["alignment"]), "wrong_alignment": describe(wrong),
                                    "alignment_bands_separate": parameters[str(span)]["alignment_match_floor"] > parameters[str(span)]["alignment_mismatch_ceiling"]}
    write_json(output / "parameters.json", {"parameters": parameters, "distributions": distributions,
               "calibration_ids": [r["id"] for r in calibration], "calibration_reference_change_labels_used": False,
               "real_labels_used_for_parameter_selection": False, "timing_sigma_seconds": model["residual_sigma_seconds"],
               "percentile_bands_are_diagnostic_not_product_acceptance_thresholds": True,
               "local_rate_uncertainty_is_not_calibrated_correctness_probability": True})
    return parameters


def predict(run, output, parameters, model, protocol, acoustic_evidence=False):
    receipt = []
    for row in read_json(run / "oracle-admission.json")["rows"]:
        ident, started = row["id"], time.perf_counter()
        evidence = load_evidence(run / ("acoustic-evidence" if acoustic_evidence else "original/evidence") / f"{ident}.npz", model)
        clocks = read_json(run / "oracle-clocks" / f"{ident}.json")["clocks"]
        for clock in clocks:
            for span in protocol["support_diagnostic"]["span_quarters_sweep"]:
                values = features(evidence, clock, span, .1, model)
                states, change = classify(values, clock, parameters[str(span)])
                target = output / "predictions" / ident
                target.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(target / f"{clock['clock_id']}-span{span}.npz", **values, states=states, change_evidence=change)
        receipt.append({"id": ident, "clock_count": len(clocks), "seconds": time.perf_counter() - started})
        write_json(output / "prediction-receipt.json", {"rows": receipt, "oracle_rate_phase_supplied": True,
                   "reference_support_or_boundary_files_read": False, "completed": False})
        print("SUPPORT " + ident, flush=True)
    write_json(output / "prediction-receipt.json", {"rows": receipt, "oracle_rate_phase_supplied": True,
               "reference_support_or_boundary_files_read": False, "completed": True})


def evaluate(run, output, protocol):
    rows = []
    if not read_json(output / "prediction-receipt.json")["completed"]:
        raise ValueError("Support predictions must be saved first")
    for admitted in read_json(run / "oracle-admission.json")["rows"]:
        ident = admitted["id"]
        ref = read_json(run / "evaluation-references" / f"{ident}.json")
        clocks = {c["clock_id"]: c for c in ref["clocks"]}
        for segment in ref["labeled_segments"]:
            if not segment["clock_id"]:
                rows.append({"id": ident, "status": "missing_oracle_clock", "segment": segment})
                continue
            clock = clocks[segment["clock_id"]]
            compatible_segments = [s for s in ref["labeled_segments"] if s["clock_id"]
                                   and abs(clocks[s["clock_id"]]["period_seconds"] - clock["period_seconds"]) < 1e-9
                                   and abs((clocks[s["clock_id"]]["phase_seconds"] - clock["phase_seconds"] + clock["period_seconds"] / 2)
                                           % clock["period_seconds"] - clock["period_seconds"] / 2) < 1e-7]
            for span in protocol["support_diagnostic"]["span_quarters_sweep"]:
                with np.load(output / "predictions" / ident / f"{segment['clock_id']}-span{span}.npz") as data:
                    t, states, changes = data["times"], data["states"], data["change_evidence"]
                    scored = np.zeros(len(t), dtype=bool)
                    truth = np.zeros(len(t), dtype=bool)
                    expected_unknown = np.zeros(len(t), dtype=bool)
                    for start, end in ref["support_seconds"]:
                        scored |= (t >= start) & (t < end)
                    for s in compatible_segments:
                        truth |= (t >= s["start_seconds"]) & (t < s["end_seconds"])
                    for start, end in ref["expected_unknown_intervals"]:
                        expected_unknown |= (t >= start) & (t < end)
                    inside, outside = scored & truth, scored & ~truth
                    def coverage(mask):
                        count = int(mask.sum())
                        return {"points": count, **{name: float(np.mean(states[mask] == state)) if count else None
                                                  for state, name in STATE_NAMES.items()}}
                    mismatch_runs = runs((states == MISMATCH) & inside, t, .1)
                    change_runs = runs(changes & inside, t, .1)
                    rows.append({"id": ident, "variant": admitted["variant"], "role": admitted["role"],
                                 "reference_tier": admitted["reference_tier"], "clock_id": segment["clock_id"], "span_quarters": span,
                                 "quarter_bpm": segment["quarter_bpm"], "true_support": coverage(inside), "other_regions": coverage(outside),
                                 "constructed_expected_unknown": coverage(expected_unknown),
                                 "mismatch_runs_on_true_support": mismatch_runs,
                                 "different_nominal_rate_runs_on_true_support": change_runs,
                                 "run_duration_seconds": describe([r["duration_seconds"] for r in mismatch_runs]),
                                 "oracle_result_not_automatic_variable_accuracy": True})
    write_json(output / "results.json", {"rows": rows, "reference_labels_read_after_predictions": True,
               "global_bar_phase_not_evaluated": True, "scope": "quarter-clock support"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["calibrate", "predict", "evaluate"])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-name", default="support")
    parser.add_argument("--fixed-library", action="store_true")
    parser.add_argument("--fixed-development", action="store_true")
    parser.add_argument("--parameters-from")
    parser.add_argument("--acoustic-evidence", action="store_true")
    args = parser.parse_args()
    run = args.run.resolve()
    output = run / args.output_name
    model, protocol = read_json(run / "model-config.json"), read_json(run / "protocol.json")
    if args.stage == "calibrate":
        output.mkdir(exist_ok=False)
        calibrate(run, output, model, protocol, args.fixed_library, args.fixed_development)
    elif args.stage == "predict":
        if args.parameters_from:
            output.mkdir(exist_ok=False)
            import shutil
            shutil.copyfile(run / args.parameters_from / "parameters.json", output / "parameters.json")
            write_json(output / "protocol-addendum.json", {"parameters_unchanged_from": args.parameters_from,
                       "acoustic_evidence": args.acoustic_evidence,
                       "reason": "Strong sensor peaks occur in exact-zero audio. Use source-only observability; do not score context completions as local sound.",
                       "no_real_reference_changed": True, "no_waveforms_exist_for_gtzan_feature_controls": True})
        predict(run, output, read_json(output / "parameters.json")["parameters"], model, protocol, args.acoustic_evidence)
    else:
        evaluate(run, output, protocol)


if __name__ == "__main__":
    main()
