"""Score accepted saved formal vectors; never reconstruct or fit a reference map."""
from pathlib import Path
import json
import math
import numpy as np
from shared_event_metrics import geometry, matching, event_score, TOLERANCES
from experiments.continuous_beat_map_v1.map import grid, sections

RUN = Path(__file__).resolve().parent
EDGE_SEMANTICS = json.loads((RUN / "qualification/support-boundary-semantics.json").read_text())
CHANGE_TOLERANCES = (.07, 1., 2.)


def in_interval(t, mask, duration):
    return 0 <= t < duration and mask["left"] - 1e-9 <= t and (
        t <= mask["right"] + 1e-9 if mask["right_inclusive"] else t < mask["right"] - 1e-9)


def count_metrics(tp, nr, npred):
    return {"true_positive": tp, "reference_count": nr, "prediction_count": npred,
            "precision": tp / npred if npred else (1. if not nr else 0.),
            "recall": tp / nr if nr else 1., "f1": 2 * tp / (nr + npred) if nr + npred else 1.}


def masked_event_score(ref_times, pred_times, ident, duration, available):
    segments = []
    for mask in EDGE_SEMANTICS[ident]["intervals"]:
        refs = [t for t in ref_times if in_interval(t, mask, duration)]
        preds = [t for t in pred_times if in_interval(t, mask, duration)]
        if refs:
            segments.append(event_score(refs, preds, duration, available))
    if not segments:
        return None
    result = {"valid_map_available": available, "accepted_support_intervals": EDGE_SEMANTICS[ident]["intervals"],
              "metric_specific_segments": segments, "tolerances_seconds": {}}
    for tolerance in map(str, TOLERANCES):
        values = [s["tolerances_seconds"][tolerance] for s in segments]
        result["tolerances_seconds"][tolerance] = count_metrics(
            sum(v["true_positive"] for v in values), sum(v["reference_count"] for v in values),
            sum(v["prediction_count"] for v in values))
    assert result["tolerances_seconds"]["0.03"]["reference_count"] == len(ref_times)
    return result


def tempo_agreement(prediction, reference, available):
    refs, predicted = reference["tempos"], sections(prediction)
    total = absolute = log_error = within1 = within3 = covered = 0.
    for left, right in reference["support_seconds"]:
        bounds = sorted({left, right} | {r["time"] for r in refs if left < r["time"] < right}
                        | {r["start"] for r in predicted if left < r["start"] < right})
        for a, b in zip(bounds, bounds[1:]):
            middle = (a + b) / 2
            past = [r for r in refs if r["time"] <= middle]
            if not past:
                continue
            total += b - a
            active = [p for p in predicted if p["start"] <= middle < p["end"]]
            if not active:
                continue
            ratio = active[-1]["bpm"] / past[-1]["bpm"]
            covered += b - a
            absolute += abs(ratio - 1) * (b - a)
            log_error += abs(math.log2(ratio)) * (b - a)
            within1 += (abs(ratio - 1) <= .01 + 1e-12) * (b - a)
            within3 += (abs(ratio - 1) <= .03 + 1e-12) * (b - a)
    def interior(t):
        return any(a < t < b for a, b in reference["support_seconds"])
    ref_changes = [new["time"] for old, new in zip(refs, refs[1:])
                   if abs(old["bpm"] - new["bpm"]) > 1e-9 and interior(new["time"])]
    pred_changes, old = [], prediction.get("initial")
    if old:
        rate = old["bpm"]
        for event in prediction["events"]:
            new_rate = event.get("bpm", rate)
            if abs(new_rate - rate) > 1e-9 and interior(event["time"]):
                pred_changes.append(event["time"])
            rate = new_rate
    changes = {str(t): matching(ref_changes, pred_changes, t) for t in CHANGE_TOLERANCES}
    if not available:
        for values in changes.values():
            values.update(precision=0., recall=0., f1=0.)
    return {"reference_duration_seconds": total, "map_covered_duration_seconds": covered,
            "duration_fraction_within_1_percent": within1 / total if total else 0.,
            "duration_fraction_within_3_percent": within3 / total if total else 0.,
            "mean_absolute_relative_error_available_map": absolute / covered if covered else None,
            "mean_absolute_log2_error_available_map": log_error / covered if covered else None,
            "reference_tempo_changes": ref_changes, "predicted_quarter_tempo_changes": pred_changes,
            "change_event_agreement": changes,
            "meaning": "Accepted quarter-tempo agreement; keep model-origin and known-development provenance."}


def meter_declarations(prediction, reference, available):
    def interior(t):
        return any(a < t < b for a, b in reference["support_seconds"])
    refs = [(e["time"], e["numerator"], e["denominator"]) for e in reference["meters"][1:] if interior(e["time"])]
    preds = []
    initial = prediction.get("initial")
    if initial:
        n, d = initial["numerator"], initial["denominator"]
        for e in prediction["events"]:
            n, d = e.get("numerator", n), e.get("denominator", d)
            if ("numerator" in e or "denominator" in e) and interior(e["time"]):
                preds.append((e["time"], n, d))
    labels = {(n, d) for t, n, d in refs + preds}
    agreement = {}
    for tolerance in CHANGE_TOLERANCES:
        tp = sum(matching([t for t, n, d in refs if (n, d) == label],
                          [t for t, n, d in preds if (n, d) == label], tolerance)["true_positive"] for label in labels)
        values = count_metrics(tp, len(refs), len(preds))
        if not available:
            values.update(precision=0., recall=0., f1=0.)
        agreement[str(tolerance)] = values
    return {"reference_post_initial_declarations": refs, "predicted_declarations": preds,
            "same_value_reference_declarations_preserved": True,
            "event_agreement_same_signature": agreement,
            "meaning": "Accepted declaration time and value, including equal-valued phase declarations; not independent written-meter certification."}


def score(receipt, capability, reference):
    duration, ident = capability["whole_source_duration_seconds"], capability["id"]
    raw = receipt.get("prediction") or {"status": "no_source_clock"}
    native = geometry(raw, duration)
    available = bool(native["legal"])
    pred = raw if available else {"status": "no_source_clock", "duration_seconds": duration, "events": []}
    return {"id": ident, "condition": receipt["condition"], "method": receipt["method"],
            "status": receipt["status"], "valid_map_available": available,
            "native_contract_independent_check": native,
            "accepted_quarter": masked_event_score(reference["quarter_times"], grid(pred, "quarter"), ident, duration, available),
            "accepted_click": masked_event_score(reference["approved_click_times"], grid(pred, "beat"), ident, duration, available),
            "accepted_bar": masked_event_score(reference["bar_times"], grid(pred, "bar"), ident, duration, available),
            "accepted_quarter_tempo": tempo_agreement(pred, reference, available),
            "accepted_meter_declarations": meter_declarations(pred, reference, available),
            "declaration_count_whole_source": len(pred["events"]) if available else None,
            "whole_source_duration_seconds": duration,
            "prediction_origin_disclosed": capability.get("prediction_origin_disclosed", False),
            "independent_native_clock_certification": None,
            "native_ideal_map_C_P": None, "independently_certified_intentional_change_accuracy": None}
