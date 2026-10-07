"""A reader-facing summary of automatic qualification and measured results."""

import html


def text(value):
    return html.escape(str(value))


def number(value, digits=3):
    return "—" if value is None else f"{value:.{digits}f}"


def render(results):
    summary = results["summary"]
    labels = {"audio_only": "자동 분석", "correct_unit_diagnostic": "정답 박 단위 제공 진단"}
    methods = []
    for name, value in summary["conditions"].items():
        methods.append(f"<tr><td>{labels[name]}</td><td>{value['qualified_denominator']}</td>"
            f"<td>{value['returned_clocks']}</td><td>{value['failed_or_abstained']}</td>"
            f"<td>{value['nominal_vocabulary_matches']}</td><td>{value['bpm_within_relative_percent']['0.1']}</td>"
            f"<td>{value['encoded_meter_matches']}/{value['encoded_meter_denominator']}</td>"
            f"<td>{value['rate_relations']['half_rate']}</td><td>{value['rate_relations']['double_rate']}</td>"
            f"<td>{value['unflagged_rate_errors']}</td></tr>")
    samples = []
    for row in results["rows"]:
        if not row["eligible"]:
            reason = "; ".join(row["reasons"])
            if row.get("error"):
                reason += ": " + row["error"]
            samples.append(f"<tr><td>{text(row['id'])}</td><td>{text(row['status'])}</td><td colspan='7'>{text(reason)}</td></tr>")
            continue
        for name, data in row["conditions"].items():
            prediction, metrics = data["prediction"], data["metrics"]
            signature = prediction.get("time_signature")
            meter = f"{signature['numerator']}/{signature['denominator']}" if signature else "—"
            diagnostic = metrics.get("declared_origin_diagnostic", {})
            quarter = diagnostic.get("quarter_clock") or {}
            bar = diagnostic.get("bar_clock") or {}
            samples.append(f"<tr><td>{text(row['id'])}</td><td>{labels[name]}</td>"
                f"<td>{number(row['reference_bpm_encoded'], 6)} → {number(prediction.get('quarter_bpm'), 6)}</td>"
                f"<td>{meter}</td><td>{number(metrics.get('bpm_relative_error_percent'), 4)}</td>"
                f"<td>{number(metrics.get('bpm_implied_drift_ms_over_input'))}</td>"
                f"<td>{number(quarter.get('maximum_absolute_ms'))}</td><td>{number(bar.get('maximum_absolute_ms'))}</td>"
                f"<td>{text(', '.join(metrics.get('confidence_flags', [])) or prediction.get('status'))}</td></tr>")
    return f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BabySlakh 자동 평가 시제품</title><style>body{{font:15px/1.7 system-ui,sans-serif;background:#f5f7fa;color:#182337;margin:0}}main{{max-width:1450px;margin:auto;padding:32px}}table{{border-collapse:collapse;width:100%;background:white;font-variant-numeric:tabular-nums}}th,td{{padding:9px;border:1px solid #d9e1ec;text-align:left}}th{{background:#eaf0f8}}.scroll{{overflow-x:auto;margin:20px 0}}.note{{background:#fff2cf;padding:18px;border-radius:10px}}a{{color:#1557a1}}</style><main>
<h1>BabySlakh 자동 평가 시제품</h1><p>전체 {summary['catalog_count']}개 · 부분 평가 가능 {summary['qualified_count']}개 · 범위 밖 {summary['excluded_count']}개 · 자료 오류 {summary['source_error_count']}개 · 평가 집합의 원곡 그룹 {summary['unique_parent_groups']}개</p>
<p>곡별 수동 판단 {summary['manual_judgments']}회. 자료의 시계와 평가 가능 항목은 추론 전에 판정했습니다. 모든 곡은 개발용 시제품 자료이며 합성 음악입니다.</p>
<p class="note"><strong>독립적인 음원 시간 원점이 확인된 표본: {summary['absolute_phase_qualified_count']}개.</strong> 정밀 위상 정확도는 채점하지 않습니다. 아래 위상 수치는 MIDI tick 0을 음원 0초로 가정한 조건부 진단입니다. 이 진단은 원점 검증이나 제작자 클릭의 정밀 정확도와 구분됩니다.</p>
<h2>참조가 지원하는 항목</h2><p>BPM은 명시된 원본 MIDI 템포와 비교합니다. 박자표는 시작 위치에 명시된 값만 채점하며 기본 4/4를 정답으로 보충하지 않습니다. BPM으로 계산한 누적 드리프트는 속도 오차의 영향이며 실제 정렬을 측정한 값이 아닙니다.</p>
<p>명목 BPM 일치는 현재 분모 4 이하 후보 집합의 가장 가까운 값과 비교한 보조 항목입니다. 실제 BPM 오차와 조건부 시계 이벤트는 원래 MIDI 수치를 유지합니다. 단위 제공 조건은 참조 BPM으로 박 단위를 선택한 진단이며 사람이 입력한 탭이나 완전 자동 성능이 아닙니다.</p>
<h2>같은 평가 집합에서의 비교</h2><div class="scroll"><table><tr><th>조건</th><th>분모</th><th>시계 반환</th><th>실패·미반환</th><th>명목 BPM 일치</th><th>BPM 오차 ≤0.1%</th><th>명시 박자표 일치</th><th>반속도</th><th>배속도</th><th>경고 없는 속도 오류</th></tr>{''.join(methods)}</table></div>
<h2>표본별 결과</h2><div class="scroll"><table><tr><th>표본</th><th>조건·상태</th><th>저장된 참조 → 예측 BPM</th><th>예측 박자표</th><th>BPM 오차(%)</th><th>속도 기반 드리프트(ms)</th><th>가정 원점 박 최대오차(ms)</th><th>가정 원점 마디 최대오차(ms)</th><th>판정·진단</th></tr>{''.join(samples)}</table></div>
<p>적합성 판정 후의 추론 실패와 시계 미반환은 평가 분모에 남습니다. 위상 값이 큰 결과를 맞추기 위해 참조를 이동하지 않습니다. 입력 전체와 참조 지원 구간은 별도로 기록합니다.</p>
<p><a href="results.json">전체 결과 JSON</a> · <a href="results.csv">집계 CSV</a> · <a href="qualification.json">사전 적합성 판정</a> · <a href="protocol.json">평가 규칙</a> · <a href="inference-receipt.json">추론 실행 정보</a></p>
</main></html>"""
