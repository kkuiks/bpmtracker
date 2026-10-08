"""Evaluate frozen predictions on the common 26-sample set and make artifacts.

Reference-informed oracle runs are explicitly diagnostic and are performed only
after the source-only predictions exist. They never replace those predictions.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from fractions import Fraction
import html
import json
import os
from pathlib import Path
from tools.project_storage import resolve_path
import shutil
import time

os.environ.setdefault("MPLCONFIGDIR", str(Path("data/research/state/experiment/metronome-v1/matplotlib")))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

from .evaluate import event_metrics, reference_events, regression_baseline, score_map
from .grid import restrict
from .infer import make_evidence, optimize


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def diagnostic_plot(path, title, evidence, beat_ref, down_ref, beats, downbeats,
                    quarter_error, bar_error, prediction):
    font_path = Path("/mnt/c/Windows/Fonts/malgun.ttf")
    if font_path.exists():
        font_manager.fontManager.addfont(str(font_path))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
        plt.rcParams["axes.unicode_minus"] = False
    duration = evidence["duration"]
    fig, axes = plt.subplots(4, 1, figsize=(13, 12), constrained_layout=True)
    stride = max(1, int(np.ceil(len(evidence["channels"]["beat"]["probability"]) / 2000)))
    for channel, color in (("beat", "#2563eb"), ("downbeat", "#dc2626")):
        p = evidence["channels"][channel]["probability"]
        count = len(p) // stride
        pooled = p[:count * stride].reshape(count, stride).max(axis=1) if count else p
        t = np.arange(len(pooled)) * stride / evidence["fps"]
        axes[0].plot(t, pooled, color=color, alpha=0.7, linewidth=0.7, label=channel)
    axes[0].set(title="Official sensor evidence over the complete input (plot-only max pooling)", ylabel="Activation")
    axes[0].legend(loc="upper right")
    for axis, start, end, label in ((axes[1], 0, min(8, duration), "Input beginning"),
                                    (axes[2], max(0, duration - 8), duration, "Input ending")):
        for values, y, color, name in ((beat_ref, 0, "#111827", "reference quarters"),
                                       (beats, 1, "#2563eb", "predicted quarters"),
                                       (down_ref, 2, "#111827", "reference downbeats"),
                                       (downbeats, 3, "#dc2626", "predicted downbeats")):
            points = values[(values >= start) & (values <= end)]
            axis.scatter(points, np.full(len(points), y), marker="|", s=160, color=color)
        axis.set(xlim=(start, end), ylim=(-0.5, 3.5), title=label, xlabel="Audio seconds")
        axis.set_yticks([0, 1, 2, 3], ["Ref quarter", "Pred quarter", "Ref downbeat", "Pred downbeat"])
    axes[3].plot(beat_ref, quarter_error * 1000, color="#2563eb", label="Quarter clock")
    axes[3].plot(down_ref, bar_error * 1000, color="#dc2626", label="Bar clock")
    axes[3].axhline(0, color="#64748b", linewidth=0.7)
    axes[3].set(title="Clock-index error without wrapping away BPM drift", xlabel="Audio seconds", ylabel="Predicted minus reference (ms)")
    axes[3].legend()
    fig.suptitle(f"{title}\n{prediction['quarter_bpm']:.6f} quarter BPM · {prediction['time_signature']['numerator']}/4 · offset {prediction['offset_seconds']:.6f}s")
    fig.savefig(path, dpi=140)
    plt.close(fig)


def summarize(rows, config, extraction):
    count = len(rows)
    metrics = {}
    for method in ("proposed", "raw_beat_this", "consecutive_regression", "oracle_structure_diagnostic"):
        channel_rows = {}
        for channel in ("quarter_events", "downbeat_events"):
            channel_rows[channel] = {}
            for tolerance in config["evaluation_tolerances_seconds"]:
                key = str(int(round(tolerance * 1000)))
                # Failures remain in the fixed denominator. A missing map is
                # not represented as a measured zero timing error.
                total = sum((row.get(method) or {}).get(channel, {}).get("tolerances_ms", {}).get(key, {}).get("f1", 0) for row in rows)
                channel_rows[channel][key] = total / count
        metrics[method] = channel_rows
    successful = [row for row in rows if row.get("proposed")]
    signature_count = sum(row["proposed"]["time_signature_exact_match"] for row in successful)
    nominal_count = sum(row["prediction"]["bpm_fraction"] == row["reference_nominal_bpm_display_only"] for row in successful)
    counts = {}
    for limit in (10, 20, 30, 70):
        counts[str(limit)] = sum(
            row["proposed"]["time_signature_exact_match"]
            and row["proposed"]["paired_quarter_clock"]["p95_absolute_error_ms"] <= limit + 1e-9
            and row["proposed"]["paired_bar_clock"]["p95_absolute_error_ms"] <= limit + 1e-9
            for row in successful
        )
    return {
        "valid_denominator": count, "completed_predictions": len(successful),
        "failed_or_unscored_predictions": count - len(successful),
        "one_common_result_group": True, "nominal_bpm_candidate_matches": nominal_count,
        "nominal_bpm_count_is_not_exact_reference_equality": True,
        "time_signature_exact_matches": signature_count,
        "clock_alignment_diagnostic_counts": counts,
        "clock_alignment_count_definition": "Correct stored time signature AND paired quarter-clock P95 AND paired bar-clock P95 within the stated milliseconds; not maximum error or a predeclared complete-song acceptance gate.",
        "uncertain_predictions": sum(bool(row.get("prediction", {}).get("confidence_flags")) for row in successful),
        "confidence_flags_are_uncalibrated_sensor_diagnostics": True,
        "no_uncertainty_flag_but_wrong_nominal_bpm": sum(
            not row["prediction"]["confidence_flags"]
            and row["prediction"]["bpm_fraction"] != row["reference_nominal_bpm_display_only"]
            for row in successful
        ),
        "macro_event_f1_common_denominator": metrics,
        "mechanism_counts": dict(Counter(reason for row in rows for reason in row.get("failure_observations", []))),
        "total_fresh_sensor_seconds": sum(row.get("seconds", 0) for row in extraction),
        "total_fitting_seconds": sum(row.get("prediction", {}).get("fit_elapsed_seconds", 0) for row in rows),
        "formal_pass_threshold_selected": False,
        "historical_constant_grid_baseline": "Not rerun or promoted; no frozen output is available for the common new 26-sample set. Full-cohort comparisons use raw official events and new simple consecutive-event regression.",
    }


def number(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


def html_report(output, summary, rows):
    cards = [f"<div class='card'><b>{summary['valid_denominator']}</b><span>동일한 valid 표본</span></div>",
             f"<div class='card'><b>{summary['nominal_bpm_candidate_matches']}/26</b><span>명목 BPM 후보 일치</span></div>",
             f"<div class='card'><b>{summary['time_signature_exact_matches']}/26</b><span>박자표 일치</span></div>",
             f"<div class='card'><b>{summary['clock_alignment_diagnostic_counts']['20']}/26</b><span>박·마디 P95 모두 20ms 이내*</span></div>"]
    comparison = []
    labels = {"raw_beat_this": "Beat This 원래 검출", "consecutive_regression": "연속 박 가정의 단순 회귀", "proposed": "새 고정 템포 맵", "grid_only_ablation": "역방향 설명 항목을 뺀 점수 진단", "oracle_structure_diagnostic": "정답 BPM·박자표 제공 진단"}
    methods = ["raw_beat_this", "consecutive_regression", "proposed"]
    if "grid_only_ablation" in summary["macro_event_f1_common_denominator"]:
        methods.append("grid_only_ablation")
    methods.append("oracle_structure_diagnostic")
    for method in methods:
        values = summary["macro_event_f1_common_denominator"][method]
        cells = [f"<td>{100 * values[channel][tol]:.2f}%</td>" for channel in ("quarter_events", "downbeat_events") for tol in ("10", "20", "30", "70")]
        comparison.append(f"<tr><td>{labels[method]}</td>{''.join(cells)}</tr>")
    table = []
    details = []
    for row in rows:
        title, ident = html.escape(row["title"]), html.escape(row["id"])
        if not row.get("proposed"):
            table.append(f"<tr><td>{title}</td><td colspan='8'>실행/평가 실패: {html.escape(row.get('error', 'unknown'))}</td></tr>")
            continue
        prediction, metrics = row["prediction"], row["proposed"]
        bp = prediction["quarter_bpm"]
        meter = prediction["time_signature"]["numerator"]
        expected_meter = row["reference_meter"]["numerator"]
        qerr = metrics["paired_quarter_clock"]["p95_absolute_error_ms"]
        berr = metrics["paired_bar_clock"]["p95_absolute_error_ms"]
        qf1 = metrics["quarter_events"]["tolerances_ms"]["20"]["f1"] * 100
        bf1 = metrics["downbeat_events"]["tolerances_ms"]["20"]["f1"] * 100
        table.append(f"<tr><td><a href='#{ident}'>{title}</a></td><td>{row['reference_bpm_exact']:.6f} → {bp:.6f}</td><td>{expected_meter}/4 → {meter}/4</td><td>{prediction['offset_seconds']:.6f}s</td><td>{qf1:.1f}%</td><td>{bf1:.1f}%</td><td>{qerr:.2f}</td><td>{berr:.2f}</td><td>{html.escape(', '.join(row['failure_observations']) or '이 진단 범위에서 큰 불일치 없음')}</td></tr>")
        candidates = []
        for candidate in prediction["top_candidates"][:8]:
            candidates.append(f"<tr><td>{candidate['quarter_bpm']:.6f}</td><td>{candidate['time_signature']['numerator']}/4</td><td>{candidate['offset_seconds']:.6f}</td><td>{candidate['score']:.5f}</td><td>{candidate['beat_evidence']['weighted_smooth_f1']:.4f}</td><td>{candidate['downbeat_evidence']['weighted_smooth_f1']:.4f}</td></tr>")
        provenance = html.escape(row["catalog_role"])
        flags = html.escape(', '.join(prediction["confidence_flags"]) or 'none')
        details.append(f"<section id='{ident}'><h2>{title}</h2><p>출처 역할: {provenance} · 추론 진단: {flags}</p><p>이 역할은 평가 집단을 나누지 않습니다. <a href='tempo-maps/{ident}.json'>예측 템포 맵</a> · <a href='predictions/{ident}.json'>전체 후보 진단</a></p><img loading='lazy' src='figures/{ident}.png' alt='Sensor evidence, grid alignment and drift'><details><summary>상위 후보</summary><table><tr><th>BPM</th><th>박자표</th><th>오프셋(s)</th><th>점수</th><th>박 일치</th><th>마디 첫 박 일치</th></tr>{''.join(candidates)}</table></details></section>")
    document = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Fixed metronome · First 26</title><style>body{{font:15px/1.65 system-ui,sans-serif;background:#f8fafc;color:#172033;margin:0}}main{{max-width:1500px;margin:auto;padding:32px}}h1{{font-size:32px}}.cards{{display:flex;gap:14px;flex-wrap:wrap}}.card{{padding:18px 24px;background:white;border:1px solid #d8e2ed;border-radius:12px;min-width:160px}}.card b{{display:block;font-size:30px}}.card span{{color:#475569}}table{{border-collapse:collapse;background:white;width:100%;font-variant-numeric:tabular-nums}}th,td{{padding:10px;border:1px solid #dbe2eb;text-align:left}}th{{background:#edf2f8}}.scroll{{overflow-x:auto;margin:20px 0}}section{{background:white;margin:32px 0;padding:24px;border:1px solid #dbe2eb;border-radius:12px}}img{{width:100%;height:auto}}a{{color:#1456a0}}.note{{background:#fff5da;padding:18px;border-radius:10px}}input{{padding:10px;width:320px;max-width:90%}}</style><main><h1>첫 고정 BPM·박자표 실험</h1><p>26개를 하나의 valid 집합으로 사용했습니다. 추론은 원음의 새 Beat This 1.1.0 단서만 사용하며, 같은 설정에서 BPM·박자표·전체 오프셋을 선택했습니다.</p><div class='cards'>{''.join(cards)}</div><p class='note'>*20ms 수치는 박자표가 일치하고 박·마디 시계의 P95 오차가 각각 20ms 이내인 표본 수입니다. 최대 오차나 제품 합격 판정이 아닙니다. 사전 검토한 참조와의 비교이며 독립적인 원제작 클릭의 밀리초 인증을 뜻하지 않습니다. 표본 분모는 모든 결과에서 26개입니다.</p><h2>같은 26개에서의 비교</h2><p>각 표본의 F1을 동일한 비중으로 평균했습니다. 정답 BPM·박자표 제공 진단은 자동 모델 성능에 포함하지 않습니다.</p><div class='scroll'><table><tr><th rowspan='2'>방법</th><th colspan='4'>박 F1</th><th colspan='4'>마디 첫 박 F1</th></tr><tr><th>10ms</th><th>20ms</th><th>30ms</th><th>70ms</th><th>10ms</th><th>20ms</th><th>30ms</th><th>70ms</th></tr>{''.join(comparison)}</table></div><h2>표본별 결과</h2><input id='filter' placeholder='곡 이름으로 찾기'><div class='scroll'><table id='samples'><tr><th>표본</th><th>참조 → 예측 BPM</th><th>박자표</th><th>전체 오프셋</th><th>박 F1 20ms</th><th>첫 박 F1 20ms</th><th>박 P95(ms)</th><th>마디 P95(ms)</th><th>관측된 불일치</th></tr>{''.join(table)}</table></div><p>오프셋은 새 맵의 마디 첫 박 기준 위치를 한 마디 길이 안에서 표현합니다. 과거 원본 프로젝트의 오프셋 값과 직접 비교하지 않습니다. 참조 없는 여백은 미평가로 남깁니다. 큰 시계 오차는 BPM 또는 마디 길이 오류를 주기적으로 감추지 않고 보여준 값입니다.</p>{''.join(details)}</main><script>document.getElementById('filter').addEventListener('input',e=>{{let q=e.target.value.toLowerCase();document.querySelectorAll('#samples tr').forEach((r,i)=>{{if(i)r.style.display=r.textContent.toLowerCase().includes(q)?'':'none'}})}})</script></html>"""
    (output / "report.html").write_text(document)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-manifest", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((args.run / "config.json").read_text())
    metadata = json.loads(args.evaluation_manifest.read_text())["samples"]
    inference_receipt = json.loads((args.run / "inference-receipt.json").read_text())
    if not inference_receipt.get("completed_at_utc"):
        raise ValueError("Finish source-only predictions before reading evaluation references")
    shutil.copyfile(args.evaluation_manifest, args.run / "evaluation-manifest.json")
    (args.run / "figures").mkdir(exist_ok=True)
    (args.run / "oracle-diagnostics").mkdir(exist_ok=True)
    rows = []
    for index, meta in enumerate(metadata, 1):
        ident = meta["id"]
        print(f"EVALUATE {index}/{len(metadata)} {ident}", flush=True)
        row = {"id": ident, "title": meta["title"], "catalog_role": meta["catalog_role"],
               "valid": True, "reference_support_seconds": meta["reference_support_seconds"],
               "qualification": meta["qualification"], "reference_scope_note": meta["reference_scope_note"]}
        try:
            prediction = json.loads((args.run / "predictions" / (ident + ".json")).read_text())
            ref = json.loads(resolve_path(args.samples_root / meta["reference"]["path"]).read_text())
            beat_ref, down_ref = reference_events(ref, meta["reference_support_seconds"])
            with np.load(args.evidence / (ident + ".npz")) as arrays:
                evidence = make_evidence(arrays["beat_logits"], arrays["downbeat_logits"], float(arrays["duration_seconds"]), config)
                raw_beats = restrict(arrays["official_beats"], meta["reference_support_seconds"])
                raw_downbeats = restrict(arrays["official_downbeats"], meta["reference_support_seconds"])
                full_beats, full_downbeats = arrays["official_beats"].copy(), arrays["official_downbeats"].copy()
            proposed, beats, downbeats, quarter_error, bar_error = score_map(prediction, beat_ref, down_ref, meta, config)
            baseline = regression_baseline(full_beats, full_downbeats, meta["duration_seconds"], config)
            baseline_metrics = score_map(baseline, beat_ref, down_ref, meta, config)[0] if baseline else None
            oracle_config = {**config, "meters": [meta["reference_meter_values"][0]["numerator"]]}
            oracle_start = time.perf_counter()
            oracle = optimize(evidence, oracle_config, fixed_bpm=meta["reference_quarter_bpm_values_exact_as_stored"][0])
            oracle["diagnostic_only_reference_bpm_and_meter_supplied"] = True
            oracle["elapsed_seconds"] = time.perf_counter() - oracle_start
            write_json(args.run / "oracle-diagnostics" / (ident + ".json"), oracle)
            oracle_metrics = score_map(oracle, beat_ref, down_ref, meta, config)[0]
            fraction = Fraction(meta["reference_quarter_bpm_values_exact_as_stored"][0]).limit_denominator(config["denominator_max"])
            row.update({"prediction": prediction, "proposed": proposed,
                        "reference_bpm_exact": meta["reference_quarter_bpm_values_exact_as_stored"][0],
                        "reference_meter": meta["reference_meter_values"][0],
                        "reference_nominal_bpm_display_only": {"numerator": fraction.numerator, "denominator": fraction.denominator},
                        "raw_beat_this": {"quarter_events": event_metrics(raw_beats, beat_ref, config["evaluation_tolerances_seconds"]),
                                           "downbeat_events": event_metrics(raw_downbeats, down_ref, config["evaluation_tolerances_seconds"])},
                        "consecutive_regression": baseline_metrics, "consecutive_regression_prediction": baseline,
                        "oracle_structure_diagnostic": oracle_metrics,
                        "independent_original_click_millisecond_accuracy_certified": meta["independent_original_click_millisecond_accuracy_certified"]})
            observations = []
            ratio = prediction["quarter_bpm"] / row["reference_bpm_exact"]
            if abs(ratio - 0.5) < 0.005:
                observations.append("half_quarter_rate")
            elif abs(ratio - 2) < 0.005:
                observations.append("double_quarter_rate")
            elif proposed["bpm_absolute_error"] > 0.01:
                observations.append("other_bpm_difference_over_0.01")
            if not proposed["time_signature_exact_match"]:
                observations.append("time_signature_mismatch")
            if proposed["bpm_absolute_error"] <= 0.01 and proposed["paired_quarter_clock"]["p95_absolute_error_ms"] > 30:
                observations.append("quarter_phase_error_over_30ms")
            if proposed["time_signature_exact_match"] and proposed["bpm_absolute_error"] <= 0.01 and proposed["paired_bar_clock"]["p95_absolute_error_ms"] > 30:
                observations.append("bar_phase_error_over_30ms")
            row["failure_observations"] = observations
            diagnostic_plot(args.run / "figures" / (ident + ".png"), meta["title"], evidence,
                            beat_ref, down_ref, beats, downbeats, quarter_error, bar_error, prediction)
            print(json.dumps({"id": ident, "bpm": prediction["quarter_bpm"], "meter": prediction["time_signature"],
                              "quarter_f1_20ms": proposed["quarter_events"]["tolerances_ms"]["20"]["f1"],
                              "downbeat_f1_20ms": proposed["downbeat_events"]["tolerances_ms"]["20"]["f1"],
                              "observations": observations}), flush=True)
        except Exception as exc:
            row["error"] = repr(exc)
            row["failure_observations"] = ["execution_or_evaluation_failure"]
            print(json.dumps({"id": ident, "error": repr(exc)}), flush=True)
        rows.append(row)
        write_json(args.run / "metrics-in-progress.json", rows)
    extraction = json.loads((args.evidence / "extraction-receipt.json").read_text())
    summary = summarize(rows, config, extraction)
    write_json(args.run / "results.json", {"completed_at_utc": datetime.now(timezone.utc).isoformat(), "summary": summary, "samples": rows})
    with (args.run / "results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["id","title","valid","reference_bpm","predicted_bpm","reference_meter","predicted_meter","offset_seconds","bpm_absolute_error","quarter_f1_20ms","downbeat_f1_20ms","quarter_clock_p95_ms","bar_clock_p95_ms","quarter_clock_max_ms","bar_clock_max_ms","quarter_drift_ms","uncertainty_flags","observed_mismatches","error"])
        for row in rows:
            if not row.get("proposed"):
                writer.writerow([row["id"],row["title"],True]+[""]*15+[row.get("error","")])
                continue
            p,m=row["prediction"],row["proposed"]
            writer.writerow([row["id"],row["title"],True,row["reference_bpm_exact"],p["quarter_bpm"],row["reference_meter"]["numerator"],p["time_signature"]["numerator"],p["offset_seconds"],m["bpm_absolute_error"],m["quarter_events"]["tolerances_ms"]["20"]["f1"],m["downbeat_events"]["tolerances_ms"]["20"]["f1"],m["paired_quarter_clock"]["p95_absolute_error_ms"],m["paired_bar_clock"]["p95_absolute_error_ms"],m["paired_quarter_clock"]["max_absolute_error_ms"],m["paired_bar_clock"]["max_absolute_error_ms"],m["paired_quarter_clock"]["accumulated_drift_ms"],';'.join(p["confidence_flags"]),';'.join(row["failure_observations"]),""])
    html_report(args.run, summary, rows)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
