"""Prepare native listening cases and reference-informed timing diagnostics.

Diagnostics never enter source workers or comparator aggregate scores. They
retain the inferred pinned initial, complete audio and continuous old-beat map.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from experiments.continuous_beat_map_v1.map import validate
from experiments.continuous_beat_map_v1.native import project, reference_map
from .common import CONSTANT, HELD, HISTORICAL, ROOT, digest, guard, read, stamp, write
from .objective import load_native_api, score_one


def diagnostic_map(item, reference, first_offset_beats):
    """Known later rates only for review; never an inference candidate."""
    initial = item["pinned_initial"]
    if not initial:
        return {"status": "no_source_clock", "events": []}
    bpm = initial["bpm"]
    anchor_time, anchor_q, bar_q = initial["bar_zero_source_seconds"], 0.0, 0.0
    beat_q = 4 / initial["denominator"]
    events, provenance = [], []
    first = True
    for left, right in zip(reference["states"], reference["states"][1:]):
        if abs(left["bpm"] - right["bpm"]) < 1e-8 or abs(left["end"] - right["start"]) > 1e-7:
            continue
        target = right["start"]
        ideal_q = anchor_q + (target - anchor_time) * bpm / 60
        q = bar_q + math.floor((ideal_q - bar_q) / beat_q + 0.5) * beat_q
        if first:
            q += first_offset_beats * beat_q
            first = False
        time = anchor_time + (q - anchor_q) * 60 / bpm
        if events and time <= events[-1]["time"] + 1e-8:
            q += beat_q
            time = anchor_time + (q - anchor_q) * 60 / bpm
        if not 0 < time < item["source"]["duration_seconds"]:
            continue
        if abs(right["bpm"] - bpm) < 1e-8:
            continue
        events.append({"time": time, "quarter": q, "bpm": right["bpm"]})
        provenance.append({"reference_time": target, "realized_time": time,
            "error_seconds": time - target,
            "error_reference_beats": (time - target) / (60 / left["bpm"] * 4 / left["denominator"])})
        anchor_time, anchor_q, bpm = time, q, right["bpm"]
    return {"status": "map", "format": "joljak-continuous-beat-map", "version": 1,
            "duration_seconds": item["source"]["duration_seconds"], "initial": dict(initial),
            "events": events, "reference_informed_evaluation_diagnostic": True,
            "inference_candidate": False, "free_phase_parameters_after_start": 0,
            "diagnostic_first_offset_old_beats": first_offset_beats, "diagnostic_timing": provenance}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    guard(run, evaluation=True)
    index = read(run / "evaluation-index.json")["rows"]
    api = load_native_api(ROOT)
    old_manifest = ROOT / "data/research/runs/native_listening_review_v1/20261012-L2-all-weak-v1/listen-projects/manifest.json"
    old_rows = read(old_manifest)["rows"] if old_manifest.is_file() else []
    manifest, reference_problems, diagnostics = [], [], []
    guide = ["# Auto Research 준비 청취 자료", "", "Start Joljak.cmd로 현재 앱을 실행하고 아래 .joljak을 열어 Click을 켜세요.",
             "모든 프로젝트는 원음 전체를 참조하며 원음 속도·길이를 바꾸지 않습니다. 승인 범위 밖 꼬리는 점수로 보장하지 않습니다.",
             "Windows 재생·실제 청취 검증은 이 준비 작업에서 수행하지 않았습니다.",
             "threshold_*는 이후 정답 BPM을 사용한 평가 전용 진단 맵입니다. 자동 추론·후보 성능에 포함하지 않습니다.", ""]
    for item in index:
        key = item["key"]
        reference = read(item["reference_path"])
        selected = [(m, read(run / "predictions" / m / (key + ".json")))
                    for m in (HISTORICAL, HELD, CONSTANT)]
        canonical_item = {"canonical_reference_path": item["canonical_reference_path"],
                          "duration_seconds": item["source"]["duration_seconds"],
                          "reference_sha256": item["reference_sha256"]}
        raw_reference = reference_map(canonical_item, reference)
        if not validate(raw_reference)["legal"]:
            previous = next((r for r in old_rows if r["id"] == item["historical_id"]
                             and r["variant"] == "reference" and
                             r["accepted_reference_sha256"] == item["reference_sha256"]), None)
            if previous and Path(previous["map_path"]).is_file():
                raw_reference = read(previous["map_path"])
        if validate(raw_reference)["legal"]:
            selected.append(("reference", raw_reference))
        else:
            reference_problems.append({"key": key, "path": item["canonical_reference_path"],
                "reason": "Accepted raw reference is not an exact legal continuous-map conversion; not snapped or changed.",
                "validation": validate(raw_reference)})
        guide += [f"## {item['title']}", "", f"원음 {item['source']['duration_seconds']:.3f}초; 승인 범위 {reference['support']}.", ""]
        if item["role"] == "primary_known_development":
            for offset in (-1, 0, 1, 2, 4):
                mapping = diagnostic_map(item, reference, offset)
                name = f"threshold_first_{offset:+d}_old_beats"
                selected.append((name, mapping))
                detail = {"key": key, "original_id": item["original_id"], "title": item["title"],
                          "variant": name, "reference_informed_evaluation_only": True,
                          "not_an_inference_candidate": True,
                          "realized_transition_errors": mapping.get("diagnostic_timing", []), "scores": []}
                for limit in (0.5, 1.0, 2.0):
                    result = score_one(mapping, reference, api=api,
                        expected_initial=item["pinned_initial"], expected_duration=item["source"]["duration_seconds"],
                        hold_meter=True, config={"maximum_boundary_error_reference_beats": limit})
                    detail["scores"].append({"maximum_boundary_error_reference_beats": limit, **result})
                diagnostics.append(detail)
        cue_times = [s["start"] for s in reference["states"][1:]] if item["role"] == "primary_known_development" else [max(0, s["time"] - 3) for s in selected[0][1].get("events", [])]
        for variant, mapping in selected:
            if mapping.get("status") != "map" or not validate(mapping)["legal"]:
                continue
            target = run / "listen-projects" / key / (variant + ".joljak")
            native = project(mapping, item["source"], item["title"], variant, target)
            native["notes"] += " Approved source support: " + str(reference["support"])
            if variant.startswith("threshold_"):
                native["notes"] += " REFERENCE-INFORMED TIMING DIAGNOSTIC; NOT INFERENCE."
            write(target, native)
            write(target.with_suffix(".map.json"), mapping)
            origin = native["clips"][0]["start"]
            manifest.append({"key": key, "title": item["title"], "variant": variant,
                "project_path": str(target), "project_sha256": digest(target),
                "map_path": str(target.with_suffix(".map.json")),
                "audio_path": item["source"]["audio_path"], "audio_project_origin_seconds": origin,
                "cue_source_seconds": cue_times, "cue_project_seconds": [t + origin for t in cue_times],
                "approved_support_source_seconds": reference["support"],
                "reference_informed_diagnostic": variant.startswith("threshold_"),
                "project_metronome": True, "click_audio_tracks": 0})
            short = ", ".join(f"{t + origin:.3f}" for t in cue_times)
            guide.append(f"- `{key}/{variant}.joljak` — 프로젝트 이동 시간(초): {short or '전체 고정 구간'}")
        guide.append("")
    write(run / "listen-projects/manifest.json", {"at_utc": stamp(), "rows": manifest,
        "reference_export_problems": reference_problems, "Windows_playback_exercised": False,
        "original_audio_and_approved_references_preserved": True})
    write(run / "timing-review-diagnostics.json", {"cases": diagnostics,
        "excluded_from_comparator_aggregate_scores": True,
        "ordinary_beats_not_quarters": True, "new_optimization_iterations": 0})
    (run / "listen-projects/listen-guide.ko.md").write_text("\n".join(guide) + "\n", encoding="utf-8")
    guard(run, evaluation=True)
    print("REVIEW_PROJECTS", len(manifest), "TIMING_CASES", len(diagnostics),
          "REFERENCE_EXPORT_PROBLEMS", len(reference_problems), flush=True)


if __name__ == "__main__":
    main()
