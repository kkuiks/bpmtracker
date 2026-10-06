"""Evaluate saved tap-only proposals without re-running any inference."""

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import csv
import html
import json
from pathlib import Path
import shutil

import numpy as np

from .benchmark import diagnostic_plot
from .evaluate import reference_events, score_map
from .infer import make_evidence


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def summarize(rows, variants):
    result = {}
    for variant in variants:
        available = [row for row in rows if row["conditions"][variant].get("metrics")]
        condition = {
            "valid_denominator": len(rows), "scored_maps": len(available),
            "failed_or_abstained_maps": len(rows) - len(available),
            "nominal_bpm_matches": sum(row["conditions"][variant]["nominal_bpm_match"] for row in available),
            "time_signature_inferred_matches": sum(row["conditions"][variant]["metrics"]["time_signature_exact_match"] for row in available),
            "quarter_and_bar_max_error_within_ms": {}, "quarter_and_bar_p95_error_within_ms": {},
            "quarter_max_error_within_ms": {},
            "macro_f1": {"quarter": {}, "downbeat": {}},
        }
        for limit in (10, 20, 30, 70):
            key = str(limit)
            def within(row, metric):
                m = row["conditions"][variant]["metrics"]
                return (m["time_signature_exact_match"]
                        and m["paired_quarter_clock"][metric] <= limit + 1e-9
                        and m["paired_bar_clock"][metric] <= limit + 1e-9)
            condition["quarter_and_bar_max_error_within_ms"][key] = sum(within(row, "max_absolute_error_ms") for row in available)
            condition["quarter_and_bar_p95_error_within_ms"][key] = sum(within(row, "p95_absolute_error_ms") for row in available)
            condition["quarter_max_error_within_ms"][key] = sum(row["conditions"][variant]["metrics"]["paired_quarter_clock"]["max_absolute_error_ms"] <= limit + 1e-9 for row in available)
            for name, channel in (("quarter", "quarter_events"), ("downbeat", "downbeat_events")):
                condition["macro_f1"][name][key] = sum(row["conditions"][variant].get("metrics", {}).get(channel, {}).get("tolerances_ms", {}).get(key, {}).get("f1", 0) for row in rows) / len(rows)
        result[variant] = condition
    return result


def render_report(run, rows, summary, baseline, invariance):
    n = len(rows)
    labels = {"audio_family_control": "같은 후보 처리 · 힌트 없음", "tap_only": "초기 BPM 단위 힌트만", "tap_minus5": "단위 힌트 −5 BPM", "tap_plus5": "단위 힌트 +5 BPM"}
    comparison = []
    b = baseline["summary"]
    comparison.append(f"<tr><td>보존된 첫 자동 실험</td><td>{b['nominal_bpm_candidate_matches']}/{n}</td><td>{b['time_signature_exact_matches']}/{n}</td><td>{b['maximum_error_alignment_diagnostic_counts']['20']}/{n}</td><td>{b['maximum_error_alignment_diagnostic_counts']['30']}/{n}</td><td>{100*b['macro_event_f1_common_denominator']['proposed']['quarter_events']['20']:.2f}%</td><td>{100*b['macro_event_f1_common_denominator']['proposed']['downbeat_events']['20']:.2f}%</td></tr>")
    for name, s in summary.items():
        comparison.append(f"<tr><td>{labels[name]}</td><td>{s['nominal_bpm_matches']}/{n}</td><td>{s['time_signature_inferred_matches']}/{n}</td><td>{s['quarter_and_bar_max_error_within_ms']['20']}/{n}</td><td>{s['quarter_and_bar_max_error_within_ms']['30']}/{n}</td><td>{100*s['macro_f1']['quarter']['20']:.2f}%</td><td>{100*s['macro_f1']['downbeat']['20']:.2f}%</td></tr>")
    table, details = [], []
    for row in rows:
        title, ident = html.escape(row["title"]), html.escape(row["id"])
        c = row["conditions"]["tap_only"]
        if not c.get("metrics"):
            table.append(f"<tr><td>{title}</td><td colspan='7'>{html.escape(c.get('error', c['prediction'].get('status','failed')))}</td></tr>")
            continue
        p, m = c["prediction"], c["metrics"]
        q, bar = m["paired_quarter_clock"], m["paired_bar_clock"]
        table.append(f"<tr><td><a href='#{ident}'>{title}</a></td><td>{row['original_automatic_bpm']:.6f} → {p['quarter_bpm']:.6f}</td><td>{row['reference_bpm_exact']:.6f}</td><td>{p['time_signature']['numerator']}/4</td><td>{p['offset_seconds']:.6f}</td><td>{q['max_absolute_error_ms']:.3f}</td><td>{bar['max_absolute_error_ms']:.3f}</td><td>{p['selected_audio_layer_power']:+d}</td></tr>")
        details.append(f"<section id='{ident}'><h2>{title}</h2><p>박자표 입력 없이 추정했습니다. <a href='tap_only/tempo-maps/{ident}.json'>템포 맵</a> · <a href='tap_only/predictions/{ident}.json'>선택 결과</a> · <a href='source-families/{ident}.json'>힌트 이전의 음원 후보</a></p><img loading='lazy' src='figures/{ident}.png' alt='Audio evidence and predicted/reference clocks'></section>")
    document = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Tap unit only · 26</title><style>body{{font:15px/1.65 system-ui,sans-serif;margin:0;background:#f8fafc;color:#172033}}main{{max-width:1450px;margin:auto;padding:30px}}table{{border-collapse:collapse;background:white;width:100%;font-variant-numeric:tabular-nums}}th,td{{border:1px solid #d9e2ed;padding:10px;text-align:left}}th{{background:#edf2f8}}.scroll{{overflow:auto;margin:20px 0}}.note{{background:#fff3d1;padding:20px;border-radius:12px}}section{{background:white;padding:24px;margin:30px 0;border-radius:12px;border:1px solid #d9e2ed}}img{{width:100%;height:auto}}a{{color:#1557a1}}input{{padding:10px;width:300px}}</style><main><h1>초기 탭을 박 단위 선택에만 사용하는 실험</h1><p>{n}개 모두 하나의 valid 집합입니다. 박자표 입력은 받지 않습니다. 후보·정확한 BPM·위상·점수는 힌트를 읽기 전에 음원으로 계산했고, 힌트는 정수 배율 선택으로만 바꿨습니다.</p><p class='note'>이번 힌트는 사람의 실제 탭을 수집한 값이 아니라 참조 BPM에서 만든 단위 제공 진단입니다. 정답 숫자로 BPM을 고정하거나 그 주변으로 탐색하지 않습니다. 이 수치는 올바른 박 단위가 제공된 조건의 성능이며 실제 탭의 정확도나 완전 자동 성능을 뜻하지 않습니다. 검토된 참조가 있는 구간에서 평가하며 독립적인 원제작 클릭의 밀리초 인증은 아닙니다.</p><h2>같은 26개에서의 비교</h2><div class='scroll'><table><tr><th>조건</th><th>명목 BPM 일치</th><th>박자표 추정 일치</th><th>박·마디 최대 20ms</th><th>박·마디 최대 30ms</th><th>박 F1 20ms</th><th>첫 박 F1 20ms</th></tr>{''.join(comparison)}</table></div><p>±5 BPM 힌트에서도 같은 단위와 전체 예측이 일치한 표본: <b>{invariance['identical_prediction_cases']}/{n}</b>. 시간 오차 기준은 진단 범위이며 정식 제품 합격선은 설정하지 않았습니다.</p><h2>표본별 결과</h2><input id='filter' placeholder='곡 이름 검색'><div class='scroll'><table id='samples'><tr><th>표본</th><th>첫 자동 BPM → 새 BPM</th><th>참조 BPM</th><th>추정 박자표</th><th>오프셋(s)</th><th>박 최대오차(ms)</th><th>마디 최대오차(ms)</th><th>배율 지수</th></tr>{''.join(table)}</table></div><p>배율 지수 +1은 음원 기준 후보의 2배, −1은 1/2배입니다. 탐색 이웃의 중심과 폭은 음원 기준 후보·길이로 정해졌으며 탭 값과 무관합니다. 같은 배율 선택 뒤에는 탭 원래 숫자가 모델에 남지 않습니다. 오프셋은 원음에 대한 기준 downbeat 위치를 한 마디 안에서 표현합니다.</p>{''.join(details)}</main><script>document.getElementById('filter').addEventListener('input',e=>{{let q=e.target.value.toLowerCase();document.querySelectorAll('#samples tr').forEach((r,i)=>{{if(i)r.style.display=r.textContent.toLowerCase().includes(q)?'':'none'}})}})</script></html>"""
    (run / "report.html").write_text(document)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--evaluation-manifest", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads((args.run / "inference-receipt.json").read_text())
    if not receipt.get("completed_at_utc"):
        raise ValueError("Finish every prediction variant before evaluation")
    config = json.loads((args.run / "config.json").read_text())
    metadata = json.loads(args.evaluation_manifest.read_text())["samples"]
    baseline = json.loads((args.baseline / "results.json").read_text())
    previous = {row["id"]: row for row in baseline["samples"]}
    variants = ["audio_family_control", "tap_only", "tap_minus5", "tap_plus5"]
    (args.run / "figures").mkdir(exist_ok=True)
    shutil.copyfile(args.evaluation_manifest, args.run / "evaluation-manifest.json")
    shutil.copytree(Path(__file__).parent, args.run / "evaluation-source-snapshot", ignore=shutil.ignore_patterns("__pycache__"))
    rows = []
    for index, meta in enumerate(metadata, 1):
        ident = meta["id"]
        print(f"EVALUATE TAP {index}/{len(metadata)} {ident}", flush=True)
        row = {"id": ident, "title": meta["title"], "valid": True,
               "catalog_role": meta["catalog_role"], "qualification": meta["qualification"],
               "reference_support_seconds": meta["reference_support_seconds"],
               "reference_bpm_exact": meta["reference_quarter_bpm_values_exact_as_stored"][0],
               "reference_meter": meta["reference_meter_values"][0],
               "original_automatic_bpm": previous[ident]["prediction"]["quarter_bpm"],
               "conditions": {}}
        ref = json.loads((args.samples_root / meta["reference"]["path"]).read_text())
        beat_ref, down_ref = reference_events(ref, meta["reference_support_seconds"])
        nominal = Fraction(row["reference_bpm_exact"]).limit_denominator(config["denominator_max"])
        for variant in variants:
            try:
                p = json.loads((args.run / variant / "predictions" / (ident + ".json")).read_text())
                condition = {"prediction": p}
                if p.get("period_seconds"):
                    m, beats, downbeats, quarter_error, bar_error = score_map(p, beat_ref, down_ref, meta, config)
                    condition["metrics"] = m
                    condition["nominal_bpm_match"] = p["bpm_fraction"] == {"numerator": nominal.numerator, "denominator": nominal.denominator}
                    if variant == "tap_only":
                        with np.load(args.evidence / (ident + ".npz")) as data:
                            evidence = make_evidence(data["beat_logits"], data["downbeat_logits"], float(data["duration_seconds"]), config)
                        diagnostic_plot(args.run / "figures" / (ident + ".png"), meta["title"], evidence,
                                        beat_ref, down_ref, beats, downbeats, quarter_error, bar_error, p)
            except Exception as exc:
                condition = {"prediction": {}, "error": repr(exc)}
            row["conditions"][variant] = condition
        rows.append(row)
        write_json(args.run / "metrics-in-progress.json", rows)
        tap = row["conditions"]["tap_only"]
        print(json.dumps({"id": ident, "tap_bpm": tap.get("prediction", {}).get("quarter_bpm"),
                          "meter": tap.get("prediction", {}).get("time_signature"),
                          "nominal_match": tap.get("nominal_bpm_match"),
                          "error": tap.get("error")}), flush=True)
    summary = summarize(rows, variants)
    invariance = json.loads((args.run / "hint-invariance.json").read_text())
    results = {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "hint_origin": receipt["hint_origin"], "time_signature_supplied": False,
        "reference_derived_hint_is_diagnostic_only": True,
        "all_sample_roles_share_one_denominator": True, "summary_by_condition": summary,
        "baseline_first_run_summary": baseline["summary"],
        "hint_invariance": invariance,
        "formal_pass_threshold_selected": False, "samples": rows,
    }
    write_json(args.run / "results.json", results)
    with (args.run / "results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["id", "title", "condition", "valid", "reference_bpm", "predicted_bpm", "reference_meter", "predicted_meter", "offset_seconds", "bpm_absolute_error", "quarter_f1_20ms", "downbeat_f1_20ms", "quarter_max_ms", "bar_max_ms", "quarter_p95_ms", "bar_p95_ms", "drift_ms", "layer_power", "error"])
        for row in rows:
            for variant in variants:
                c = row["conditions"][variant]
                if not c.get("metrics"):
                    writer.writerow([row["id"], row["title"], variant, True] + [""] * 14 + [c.get("error", c["prediction"].get("status", "failed"))])
                    continue
                p, m = c["prediction"], c["metrics"]
                writer.writerow([row["id"], row["title"], variant, True, row["reference_bpm_exact"], p["quarter_bpm"], row["reference_meter"]["numerator"], p["time_signature"]["numerator"], p["offset_seconds"], m["bpm_absolute_error"], m["quarter_events"]["tolerances_ms"]["20"]["f1"], m["downbeat_events"]["tolerances_ms"]["20"]["f1"], m["paired_quarter_clock"]["max_absolute_error_ms"], m["paired_bar_clock"]["max_absolute_error_ms"], m["paired_quarter_clock"]["p95_absolute_error_ms"], m["paired_bar_clock"]["p95_absolute_error_ms"], m["paired_quarter_clock"]["accumulated_drift_ms"], p["selected_audio_layer_power"], ""])
    render_report(args.run, rows, summary, baseline, invariance)
    print(json.dumps({"summary_by_condition": summary,
                      "identical_hint_variants": invariance["identical_prediction_cases"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
