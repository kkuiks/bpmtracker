"""Prepare frozen GTZAN roles, evaluate one role, and report coarse-label results."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .gtzan import SOURCE_FIELDS, aggregate_annotations, qualify_dataset, score_annotation, select_pilot
from .inference import write_json


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
MODEL = ROOT / "experiments/metronome_reconstruction_v1"
LABELS = {"audio_only": "고정 메트로놈 자동 분석", "correct_unit_diagnostic": "주석의 박 단위 제공 진단",
          "beat_this_events": "Beat This 기본 이벤트 출력"}


def render_report(results):
    summary = results["summary"]
    primary = str(results["protocol"]["primary_event_tolerance_ms"])
    escape = lambda value: html.escape(str(value))
    number = lambda value, digits=2: "—" if value is None else f"{value:.{digits}f}"
    methods = []
    for name, value in summary["conditions"].items():
        bpm = f"{value['bpm_within_relative_percent']['2']}/{value['pulse_bpm_denominator']}" if "pulse_bpm_denominator" in value else "—"
        meter = f"{value['bar_pulse_count_matches']}/{value['bar_pulse_count_denominator']}" if "bar_pulse_count_denominator" in value else "—"
        beat = value["beat_macro_f1"][primary]
        bar = value["downbeat_macro_f1"][primary]
        methods.append(f"<tr><td>{LABELS[name]}</td><td>{value['selected_denominator']}</td>"
            f"<td>{value['returned_predictions']}</td><td>{value['failed_or_abstained']}</td>"
            f"<td>{bpm}</td><td>{meter}</td><td>{number(beat * 100 if beat is not None else None)}%</td>"
            f"<td>{number(bar * 100 if bar is not None else None)}%</td></tr>")
    rows = []
    for row in results["rows"]:
        if not row.get("selected_for_inference"):
            reason = ", ".join(row["reasons"]) or f"{row.get('role', 'unknown')} 구간 보관"
            if row.get("error"):
                reason += ": " + row["error"]
            rows.append(f"<tr><td>{escape(row['id'])}</td><td>{escape(row['status'])}</td>"
                        f"<td colspan='6'>{escape(reason)}</td></tr>")
            continue
        for name, result in row["conditions"].items():
            prediction, score = result["prediction"], result["metrics"]
            reference = row["reference_fixed_fit"]
            meter = prediction.get("time_signature")
            downbeat = score["downbeat_f1"]
            rows.append(f"<tr><td>{escape(row['id'])}</td><td>{LABELS[name]}</td>"
                f"<td>{number(reference['pulse_bpm'], 4)} → {number(prediction.get('quarter_bpm'), 4)}</td>"
                f"<td>{escape(reference['bar_pulse_count'])} → {escape(meter['numerator'] if meter else '—')}</td>"
                f"<td>{number(score.get('pulse_bpm_relative_error_percent'), 3)}</td>"
                f"<td>{number(score['beat_f1'][primary]['f1'] * 100)}%</td>"
                f"<td>{number(downbeat[primary]['f1'] * 100 if downbeat else None)}%</td>"
                f"<td>{escape(', '.join(score.get('confidence_flags', [])) or score.get('failure') or score['status'])}</td></tr>")
    return f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GTZAN 자동 평가</title><style>body{{font:15px/1.7 system-ui,sans-serif;background:#f5f7fa;color:#182337;margin:0}}main{{max-width:1450px;margin:auto;padding:32px}}table{{border-collapse:collapse;width:100%;background:white;font-variant-numeric:tabular-nums}}td,th{{border:1px solid #d9e1ec;padding:9px;text-align:left}}th{{background:#eaf0f8}}.scroll{{overflow-x:auto;margin:20px 0}}.note{{background:#fff2cf;padding:18px;border-radius:10px}}a{{color:#1557a1}}</style><main>
<h1>GTZAN 실음악 주석 자동 평가</h1>
<p>공개 특징 {summary['catalog_count']}개 · 고정 박 간격 근사에 적합 {summary['qualified_count']}개 · 이번 분석 {summary['selected_count']}개 ({escape(summary['selected_role'])}) · 범위 밖 {summary['excluded_count']}개 · 자료 오류 {summary['source_error_count']}개.</p>
<p>평가 가능 표본의 역할: {escape(json.dumps(summary['qualified_by_role'], ensure_ascii=False))}. 곡별 수동 판단은 0회입니다. 적합성 판정과 그룹 배정은 예측 전에 기록했습니다.</p>
<p class="note">원음을 새로 확보하거나 앱의 디코더를 평가한 결과가 아닙니다. 공개된 50fps·128밴드 특징을 float32 모델에 입력합니다. 기존 박·마디 주석과의 일치도를 채점하며, 제작자의 정밀 시계나 정확한 악보 박자표를 인증하지 않습니다.</p>
<h2>사전 선정 규칙</h2><p>원래 박 주석을 모두 사용하여 일정한 박 간격을 최소제곱으로 맞춥니다. 절대 잔차의 95백분위가 30ms 이하, 최대가 70ms 이하인 표본만 고정 조건 근사에 포함합니다. 주석의 박 순서가 일정한 3박·4박 마디를 이루는지도 확인합니다. 주석을 제거하거나 이동하지 않으며, 이 근사는 실제 제작 템포가 일정하다는 증명과 구분됩니다.</p>
<p>동일한 특징은 같은 그룹으로 묶고 개발 60%·검증 20%·보관 20%에 결정적으로 배정합니다. 선택한 역할 안에서 장르·마디당 박 수를 순회하여 그룹을 선정합니다. 실행별 제한과 실제 ID는 split.json에 기록하며, 제한 0은 해당 역할의 전체 그룹을 뜻합니다. 보관 구간은 이번 추론에 들어가지 않습니다. 서로 다른 파일의 동일 원곡·아티스트 관계는 전부 확인하지 못했으므로 최종 독립 테스트로 취급하지 않습니다.</p>
<h2>선정 집합에서의 비교</h2><p>이벤트의 주 지표는 오차 허용 {primary}ms의 곡별 평균 F1입니다. 추론 실패는 선정 분모에 남고 F1은 0으로 집계합니다. JSON에는 20·30ms 진단과 이벤트 전체를 합친 F1도 기록합니다.</p>
<div class="scroll"><table><tr><th>조건</th><th>분모</th><th>예측 반환</th><th>실패·미반환</th><th>주석 박 BPM 오차 ≤2%</th><th>마디당 박 수 일치</th><th>박 F1</th><th>마디 첫 박 F1</th></tr>{''.join(methods)}</table></div>
<p>주석의 박을 4분음표로 읽는 단위 제공 조건은 참조 기반 진단입니다. 박자표·주석 시각·위상은 추론에 제공하지 않습니다. Beat This 기본 출력은 같은 관측에서 얻은 가변 이벤트열이며 고정 BPM·박자표·오프셋을 반환하는 모델과 출력 목표가 다릅니다.</p>
<h2>표본별 결과와 보관 상태</h2><div class="scroll"><table><tr><th>표본</th><th>조건·상태</th><th>주석 → 예측 BPM</th><th>마디당 박 수</th><th>BPM 오차(%)</th><th>박 F1</th><th>마디 첫 박 F1</th><th>판정·진단</th></tr>{''.join(rows)}</table></div>
<p><a href="results.json">전체 JSON</a> · <a href="results.csv">CSV</a> · <a href="qualification.json">사전 판정</a> · <a href="protocol.json">평가 규칙</a> · <a href="split.json">그룹 배정</a> · <a href="inference-receipt.json">실행 정보</a></p>
</main></html>"""


def prepare(args):
    protocol = json.loads(args.protocol.read_text())
    if sum(protocol["split_percentages"].values()) != 100:
        raise ValueError("Role percentages must sum to 100")
    rows, references = qualify_dataset(args.data_root.resolve(), protocol)
    selected_ids = select_pilot(rows, references, protocol, args.role, args.limit)
    args.output.mkdir(parents=True, exist_ok=False)
    for row in rows:
        row["selected_for_inference"] = row["id"] in selected_ids
    selected = [row for row in rows if row["selected_for_inference"]]
    shutil.copyfile(args.protocol, args.output / "protocol.json")
    shutil.copyfile(args.config, args.output / "model-config.json")
    write_json(args.output / "qualification.json", {"schema_version": 1, "rows": rows,
        "qualification_precedes_predictions": True, "manual_judgments": 0})
    write_json(args.output / "split.json", {"seed": protocol["split_seed"],
        "grouping": protocol["grouping"], "artist_independence_verified": False,
        "reserved_is_final_locked_test": False, "pilot_group_limit": args.limit,
        "pilot_selection": protocol["pilot_selection"], "selected_ids": sorted(selected_ids),
        "parent_group_roles": {row["parent_group"]: row["role"] for row in rows if "parent_group" in row}})
    write_json(args.output / "source-inputs.json", {"schema_version": 1,
        "samples": [{key: row[key] for key in SOURCE_FIELDS} for row in selected]})
    write_json(args.output / "unit-hints.json", {"schema_version": 1, "samples": [
        {"id": row["id"], "initial_quarter_bpm_tap": references[row["id"]]["pulse_bpm"],
         "scope": "initial_section", "origin": "published-annotation-pulse-unit-diagnostic"}
        for row in selected]})
    for ident, reference in references.items():
        write_json(args.output / "references" / f"{ident}.json", reference)
    snapshot = args.output / "source-snapshot"
    snapshot.mkdir()
    frozen_sources = {}
    for path in [MODEL / name for name in ("infer.py", "hinted.py", "grid.py")] + [args.config]:
        shutil.copyfile(path, snapshot / path.name)
        frozen_sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output / "benchmark-snapshot").mkdir()
    for path in PACKAGE.glob("*.py"):
        shutil.copyfile(path, args.output / "benchmark-snapshot" / path.name)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                            capture_output=True, check=True).stdout.strip()
    write_json(args.output / "run.json", {"schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "source_commit": commit,
        "data_root": str(args.data_root.resolve()), "dataset_role": args.role, "pilot_group_limit": args.limit,
        "checkpoint": str(args.checkpoint.resolve()), "checkpoint_bytes": args.checkpoint.stat().st_size,
        "frozen_model_sources": frozen_sources, "model_parameters_changed": False, "new_training": False,
        "reference_unit_hints_are_diagnostic": True, "beat_this_version": importlib.metadata.version("beat-this"),
        "source_audio_acquired": False, "precomputed_features_only": True,
        "complete_candidate_trace": args.trace})
    print(f"QUALIFY {len(rows)} total; {len(references)} qualified; {len(selected)} selected {args.role}; "
          f"{dict(Counter(row['status'] for row in rows))}", flush=True)
    return rows, references, protocol


def build_results(args, rows, references, protocol):
    for row in rows:
        if not row["selected_for_inference"]:
            continue
        row["conditions"] = {}
        for name in protocol["conditions"]:
            path = args.output / "predictions" / name / f"{row['id']}.json"
            prediction = json.loads(path.read_text()) if path.is_file() else {"status": "inference_failed", "error": "missing_prediction"}
            row["conditions"][name] = {"prediction": prediction,
                "metrics": score_annotation(prediction, references[row["id"]], protocol, events_only=name == "beat_this_events")}
    summary = aggregate_annotations(rows, references, protocol, args.role)
    results = {"schema_version": 1, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
               "protocol": protocol, "summary": summary, "rows": rows}
    write_json(args.output / "results.json", results)
    write_json(args.output / "summary.json", summary)
    fields = ["id", "qualification", "role", "selected", "reasons", "condition", "returned_prediction",
              "reference_pulse_bpm", "predicted_bpm", "bpm_relative_error_percent", "beat_f1_70ms", "downbeat_f1_70ms"]
    with (args.output / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            common = {"id": row["id"], "qualification": row["status"], "role": row.get("role"),
                      "selected": row["selected_for_inference"], "reasons": ";".join(row["reasons"])}
            if not row["selected_for_inference"]:
                writer.writerow(common)
                continue
            for name, data in row["conditions"].items():
                score = data["metrics"]
                writer.writerow({**common, "condition": name, "returned_prediction": score["returned_prediction"],
                    "reference_pulse_bpm": references[row["id"]]["pulse_bpm"],
                    "predicted_bpm": data["prediction"].get("quarter_bpm"),
                    "bpm_relative_error_percent": score.get("pulse_bpm_relative_error_percent"),
                    "beat_f1_70ms": score["beat_f1"]["70"]["f1"],
                    "downbeat_f1_70ms": score["downbeat_f1"]["70"]["f1"] if score["downbeat_f1"] else None})
    (args.output / "report.html").write_text(render_report(results), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "protocol-gtzan-v1.json")
    parser.add_argument("--config", type=Path, default=MODEL / "config-tap-v2.json")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "samples/.experiment-state/metronome-v1/final0.ckpt")
    parser.add_argument("--role", choices=["development", "validation"], default="development")
    parser.add_argument("--limit", type=int, default=100, help="Maximum exact feature groups; zero evaluates the complete selected role")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--trace", action="store_true", help="Preserve every scored clock for later decomposition")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    args.output = args.output.resolve()
    if args.output.exists():
        raise ValueError("Use a new run output; preserved runs are immutable")
    rows, references, protocol = prepare(args)
    if args.prepare_only:
        return
    if not any(row["selected_for_inference"] for row in rows):
        raise ValueError("No selected input qualifies for inference")
    environment = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[name] = "4"
    command = [sys.executable, "-m", "experiments.metronome_benchmark_v1.inference"]
    options = ["--source", str(args.output / "source-inputs.json"), "--config", str(args.output / "model-config.json"),
               "--checkpoint", str(args.checkpoint), "--output", str(args.output)]
    subprocess.run(command + ["prepare"] + options + (["--trace"] if args.trace else []), cwd=ROOT, env=environment, check=True)
    subprocess.run(command + ["select"] + options + ["--hints", str(args.output / "unit-hints.json")],
                   cwd=ROOT, env=environment, check=True)
    build_results(args, rows, references, protocol)


if __name__ == "__main__":
    main()
