"""Aggregate preserved prerequisites into a decision and readable evidence."""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path

import numpy as np

from .common import describe, digest, read_json, write_json


VARIABLES = {"step", "return", "large", "octave", "small", "short_bar", "silent_change"}


def support_summary(rows, span, group):
    selected = [r for r in rows if r.get("span_quarters") == span and
                (r.get("variant") == "real_variable" if group == "real" else r.get("variant") in VARIABLES)]
    result = {"clock_denominator": len(selected)}
    for field in ("true_support", "other_regions"):
        total = sum(r[field]["points"] for r in selected)
        result[field] = {"points": total, "time_weighted_coverage": {
            state: sum(r[field]["points"] * (r[field][state] or 0) for r in selected) / total if total else None
            for state in ("MATCH", "MISMATCH", "UNKNOWN")},
            "macro_clock_coverage": {state: float(np.mean([r[field][state] for r in selected if r[field][state] is not None]))
                                     for state in ("MATCH", "MISMATCH", "UNKNOWN")}}
    return result


def gather(run):
    candidate = read_json(run / "candidate-recovery/results.json")
    proposal = read_json(run / "local-proposal-v2/results.json")
    support = read_json(run / "support-v6/results.json")
    negative = read_json(run / "negative-controls-v6/results.json")
    boundaries = {str(span): read_json(run / f"boundary-support{span}/results.json") for span in (4, 8, 16)}
    unique = {}
    for row in candidate["rows"]:
        if row["variant"] == "real_variable":
            unique[(row["id"], row["nominal_target_bpm"])] = row
    unique_summary = {"denominator": len(unique), "stage_recovered": {
        stage: sum(row["stage_diagnostics"][stage]["nominal_present"] for row in unique.values())
        for stage in ("broad_bpm_list", "base_scored", "final_family_scored", "retained")}}
    burdens = defaultdict(list)
    for source in read_json(run / "source-inputs.json")["samples"]:
        with gzip.open(run / "local-proposal-v2" / f"{source['id']}.jsonl.gz", "rt") as stream:
            for line in stream:
                row = json.loads(line)
                burdens[str(row["span_seconds"])].append(len(row.get("original_broad_rates", [])))
    summary = {"decision": "DO NOT PROCEED TO STEP 1 YET",
               "blocking_prerequisites": [
                   "Whole-input final family loses constituent rates; local rate union does not establish phase or valid support.",
                   "Short real clock support and false fixed change proposals remain; no reliable product support-duration rule is established.",
                   "Boundary localization is conditional on oracle clocks and source support; misses, broad intervals and harmonic ambiguity remain."],
               "source_commit": read_json(run / "run.json")["source_commit"],
               "input_denominators": {"new_constructed_music": 30, "parent_compositions": 3, "primary_real": 3,
                                      "secondary_rate_only": 2, "existing_vocabulary_probe": 1, "automatic_inputs": 36,
                                      "fixed_gtzan_groups": 367, "reserved_consumed": 0},
               "whole_input_candidate_recovery": candidate["summary"], "primary_real_unique_rates": unique_summary,
               "local_proposal": proposal["summary"],
               "original_local_broad_proposal_burden": {k: describe(v) for k, v in burdens.items()},
               "support": {str(span): {group: support_summary(support["rows"], span, group) for group in ("real", "constructed")}
                           for span in (4, 8, 16)},
               "fixed_negative_controls": negative["summary"],
               "boundaries": {span: value["summary"] for span, value in boundaries.items()},
               "initial_unrestricted_boundary": read_json(run / "boundary/results.json")["summary"],
               "controls": {"preparation": read_json(run / "preparation-controls.json"),
                            "algorithm": read_json(run / "algorithm-controls.json"), "constructed_coordinates": 30},
               "limits": {"automatic_variable_maps_produced": False, "quarter_support_not_global_bar_phase_accuracy": True,
                          "real_millisecond_certification": False, "synthetic_perceptual_uniqueness_certified": False,
                          "simple_default_replacement": False, "neural_training": False, "original_reference_shift": False}}
    return summary, candidate, proposal, support, negative, boundaries


def pct(value):
    return "—" if value is None else f"{100 * value:.2f}%"


def format_stats(value, unit="s"):
    if not value.get("count"):
        return "No returned estimates"
    return f"median {value['median']:.6g}{unit}, p90 {value['p90']:.6g}{unit}, max {value['maximum']:.6g}{unit}"


def write_report(run, summary, candidate, proposal, support, negative, boundaries):
    lines = ["# Variable Tempo Expansion Step 0 — completed prerequisite study", "",
             "**Decision: DO NOT PROCEED TO STEP 1 YET.**", "",
             "The piecewise fixed-clock direction remains plausible on several long non-harmonic regions, but the current final candidate family is unsuitable as the only proposal source. Local proposals, short support, fixed false-change behavior and boundary ambiguity need another focused prerequisite iteration. No recursive decoder or application integration was built.", "",
             "## Scope and evidence", "",
             f"Source base: `{summary['source_commit']}`. Original estimator/configuration match the frozen development280 baseline. Official final0 observations were computed for 36 source-only waveforms; reference evaluation followed saved predictions.",
             "Thirty new musical inputs are variants of three parent compositions, not thirty independent songs. Twenty-one vary tempo and nine are fixed controls. Their transport/sample coordinates were independently checked within one 32 kHz frame (0.03125 ms). Music and authored-click listening assets are in `corpus/index.html`.",
             "Real diagnostics are Hospital Hill, Right Back At It Again and Heir Apparent: existing owner-reviewed maps support practical alignment comparisons, not independent producer-click millisecond certification. Circle With Me retains 4/2 and half-note click provenance and is rate-only. BabySlakh Track00008 is encoded-rate-only because waveform origin is unresolved. Forty-seven surveyed rows and the separately recorded owner exclusion remain in the inventory.", "",
             "The 280 development and 87 already-used validation GTZAN groups are fixed negative controls. They carry coarse annotation and notation limits. No reserved groups, new paid acquisition, neural training, accepted-reference changes or source commits/pushes occurred.", "",
             "## Candidate Recovery", "", "Rate recovery is separate from clock phase and valid support. Targets are nearest allowed denominator-four nominal rates; exact reference values, representational error and implied drift remain in JSON.", "",
             "| Cohort | Segment denominator | Broad list | Base scored | Final family | Retained | Top-1 segment-rate matches |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name in ("primary_real", "constructed_variable", "secondary_rate_only"):
        value = candidate["summary"][name]
        recovered = value["stage_nominal_recovery"]
        lines.append(f"| {name} | {value['segment_denominator']} | {recovered['broad_bpm_list']} | {recovered['base_scored']} | {recovered['final_family_scored']} | {recovered['retained']} | {value['selected_nominal_matches']} |")
    lines += ["", f"Primary real unique recording/rate targets: {summary['primary_real_unique_rates']['denominator']}. Stage counts: `{summary['primary_real_unique_rates']['stage_recovered']}`.",
              "Hospital Hill's nominal 110 BPM was base-score rank 2, with a 0.0108167 score gap, then disappeared when the final family narrowed around 102 BPM. The Opeth 145 BPM candidate similarly survived broad scoring but was lost around 135 BPM. Other real rates were absent already in broad proposal. These are separate failure categories.", "",
              "Local source-only proposal study used 2/4/8/16/32 s windows and unchanged Original spectral generation versus the frozen Simple event-line comparison. Every proposal was saved in a separate worker before reference targets were opened. Window edges are never tempo-change timestamps.", "",
              "| Window | Real denominator | Broad union | Simple top-1 union | Top-5 union | Top-20 union | Broad-rate count median / max |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for span, value in proposal["summary"]["primary_real"]["spans"].items():
        burden = summary["original_local_broad_proposal_burden"][span]
        lines.append(f"| {span}s | 15 | {value['original_broad_recovered']} | {value['simple_top1_recovered']} | {value['simple_top5_recovered']} | {value['simple_top20_recovered']} | {burden['median']:.0f} / {burden['maximum']:.0f} |")
    lines += ["", "These are **anywhere-in-recording rate unions**, not proof that a candidate explains its actual segment. The 1.655 s real 145 BPM segment cannot contain even the shortest 2 s analysis window. A nominal rate can appear in a mixed or unrelated window; source-derived phase/support must still be demonstrated. Broad recall with hundreds or thousands of proposals is not selective recovery.", "",
              "## Oracle quarter-clock support", "",
              "Only a supplied BPM/canonical phase enters support prediction; true support and boundaries are separate evaluation files. MATCH means sufficient evidence supports the clock; MISMATCH requires sustained local rhythmic evidence with poor clock agreement; otherwise UNKNOWN. Window spans 4/8/16 quarters are compared rather than selecting a convenient product minimum duration.",
              "Support v1 calibrated on three newly constructed 120 BPM controls; v2 added sixteen previously constructed fixed 4/4 variants at several rates; v3 added development280 observations while keeping validation87 out of calibration. These were frozen before selecting bands from real-variable support scores. V4/V5 source-observability implementation records remain preserved. Final v6 uses the v3 bands, strict digital-silence information and a deterministic frame-rounding slope uncertainty bound.",
              "Strict silence is source-only PCM zero over a full supplied-clock period. Ordinary inter-beat silence remains usable. Raw logits are unchanged. This addresses a measured failure: the silent-change control contained seven high beat-activation peaks in exactly zero audio. It is not general drumless-section detection; GTZAN waveforms are unavailable, so that acoustic check is absent for its feature controls.", "",
              "| Span | Cohort | True support MATCH | MISMATCH | UNKNOWN | Other-region MATCH |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for span, groups in summary["support"].items():
        for group, value in groups.items():
            a, b = value["true_support"]["time_weighted_coverage"], value["other_regions"]["time_weighted_coverage"]
            lines.append(f"| {span} quarters | {group} | {pct(a['MATCH'])} | {pct(a['MISMATCH'])} | {pct(a['UNKNOWN'])} | {pct(b['MATCH'])} |")
    lines += ["", "Time weighting differs from macro clock weighting; both are preserved. Silent intervals stay in the full support denominator, with expected-UNKNOWN diagnostics separate. A same-rate clock with a nearby phase can remain acoustically compatible; MATCH is not unique identification of intended quarter/bar semantics. Harmonic clock nesting is another explicit ambiguity.", "",
              "## Fixed negative controls and quantization", "", "| Role / condition, 8-quarter span | Inputs | MATCH | MISMATCH | UNKNOWN | Match-then-other-rate proposals | Runs >=4 / >=8 quarters |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for role in ("development", "already_used_validation"):
        for condition in ("annotation_fit_oracle", "saved_original"):
            key = f"{role}:support-v6:{condition}:8"
            value = negative["summary"][key]
            c = value["macro_coverage"]
            count = value["diagnostic_proposal_run_quarter_counts"]
            lines.append(f"| {role} / {condition} | {value['input_denominator']} | {pct(c['MATCH'])} | {pct(c['MISMATCH'])} | {pct(c['UNKNOWN'])} | {value['inputs_with_match_then_alternate_proposal']} | {count['4']} / {count['8']} |")
    lines += ["", "A wholly wrong fixed hypothesis calls for replacement, not automatically an internal tempo change. The report therefore separates mismatch runs, alternate nominal-rate evidence, and a MATCH region followed by alternate-rate evidence. Run-length thresholds here are diagnostic columns, not an adopted product minimum.",
              "The unchanged 120.1 BPM reference remains outside the denominator-four vocabulary. Its correct-unit 120 BPM source proposal is tested separately from the exact oracle clock. Phase mismatch/drift alone is not a new nominal rate. The initial quantized-event fixture exposed correlated frame-rounding errors that the independent-noise regression proxy missed; the corrected interval includes a half-frame weighted slope bound. The initial failure and passed revised controls are retained.", "",
              "## Oracle boundary localization", "",
              "The baseline compares two known clocks over the entire source. It returned 11/12 real boundaries with median absolute error 1.377 s and a 166.070 s maximum: unrelated earlier regions can dominate the objective, especially for the short middle real segment.",
              "The comparison uses source-inferred MATCH runs to bound a neighboring-clock comparison. Integrated support ranks ordered anchor pairs without a fixed duration cutoff. Actual localization still uses original-time source events, not analysis-window edges. Exact objective plateaus and one-sensor-frame sensitivity intervals remain visible.", "",
              "| Support span | Cohort | Boundary denominator | Returned | Miss/unknown | Returned absolute error | Sensitivity interval contains reference |", "| --- | --- | ---: | ---: | ---: | --- | ---: |"]
    for span, data in boundaries.items():
        for group in ("primary_real", "constructed"):
            value = data["summary"][group]
            lines.append(f"| {span} quarters | {group} | {value['boundary_denominator']} | {value['returned_audio_boundaries']} | {value['missed_or_unknown']} | {format_stats(value['absolute_seconds_error_returned'])} | {value['frame_sensitivity_contains_reference']} |")
    lines += ["", "Returned-point statistics exclude misses only from the conditional error distribution; misses remain in the boundary denominator. Real errors compare an existing owner map, not a certified absolute producer event. Exact source transport supports numerical constructed error, not real-music generalization.",
              "The optional phase-continuity estimate assumes a quarter-grid change and uses the supplied correct phases. Those phases can already constrain an authored junction strongly. Its near-zero errors must not be reported as audio-only boundary precision. In silent changes, a midpoint can be close while the supported interval is several seconds wide. In a 160→80 case, nested quarter lattices can leave no event-only switch advantage; UNKNOWN is preserved.", "",
              "## Decision and next bounded problem", "",
              "DO NOT PROCEED TO STEP 1 YET. Preserve Original as the canonical fixed foundation and Simple as a proposal/comparison tool. The study supports investigating a variable-facing multi-hypothesis proposer and support-driven boundary brackets, but does not establish reliable automatic recursion.",
              "The next prerequisite work should establish clock phase/support for proposed rates, characterize short-region and harmonic ambiguity, and freeze a defensible sustained-evidence policy against fixed controls. Do not remove short failures, turn UNKNOWN into a change, expand the BPM vocabulary, or revive legacy decoders. No follow-on experiment is started by this report.", "",
              "## Durable records and execution limits", "",
              "`inventory/` and corrected-origin-label `inventory-v2/`; frozen protocol/admission; `corpus/` coordinate ledgers and listening; `original/` full traces; `candidate-recovery/`; `local-proposal-v2/`; support versions; acoustic evidence; baseline and support-bracketed boundaries; fixed negative-control versions; source/config snapshots; JSON summaries and figures.",
              "The initial local-proposal attempt was interrupted because it opened a reference-containing prior report in the same process; its partial outputs and disposition are preserved and unscored. A separate-worker v2 replaced it. The source-worker fixture succeeds with an invalid reference sentinel, directly checking separation.",
              f"Preparation controls: {summary['controls']['preparation']['tests_run']}; algorithm/source-isolation controls: {summary['controls']['algorithm']['tests_run']}; constructed coordinate records: 30. These establish implementation contracts, not musical accuracy. No latest DAW runtime/playback/export audit or integration was performed."]
    (run / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ko = ["# 변속 확장 Step 0 결과", "", "**현재 판단: Step 1의 자동 분할기로 바로 넘어가기에는 이릅니다.**", "",
          "기존 고정 시계를 여러 개 찾아 연결하는 방향은 긴 구간에서 가능성을 보였습니다. 다만 후보가 있다는 사실, 실제로 맞는 구간을 찾는 것, 변경 시점을 찾는 것은 서로 다른 문제였습니다.", "",
          "## 실제 자료에서 확인한 것", "",
          "Hospital Hill, Right Back At It Again, Heir Apparent의 기존 승인 지도를 주 진단에 사용했습니다. Circle With Me는 원래 4/2 해석을 유지해 속도 후보만 보았고, BabySlakh는 음원 시간 원점이 확정되지 않아 변경 시점의 정밀 정확도를 채점하지 않았습니다.", "",
          "세 실제 곡의 15개 템포 구간 중 가장 가까운 표현 가능한 BPM이 넓은 탐색에는 10개 구간에서 있었지만, 최종 후보군에는 5개 구간에서만 남았습니다. 곡별 서로 다른 속도 10종을 세면 최종 후보군에는 3종이 남았습니다.",
          "로컬 관측에서는 놓친 속도를 후보로 다시 만들 수 있었습니다. 하지만 후보가 아주 많으면 정답이 목록에 들어 있기만 한 것일 수 있습니다. 또 짧은 실제 구간의 속도가 다른 부분의 혼합 창에서 우연히 나타날 수도 있습니다. 그래서 후보 복구를 곧바로 분할 성공으로 계산하지 않았습니다.", "",
          "## 맞음ㆍ어긋남ㆍ모름", "",
          "정답 시계를 알려준 조건으로, 이 시계가 맞는 구간을 찾았습니다. 긴 구간은 상당 부분 구분됐지만 짧은 1.66초 구간과 단서가 약한 구간은 여전히 어렵습니다. 같은 BPM이어도 박 시작 위치가 달라질 수 있어 별도 시계로 유지했습니다.",
          "무음에서는 센서가 주변 맥락을 이용해 박을 예상할 수 있었습니다. 실제 소리가 완전히 0인 통제 구간에 강한 활성 봉우리가 7개 있었으므로, 출력 신뢰도와 현장의 음악 단서를 구분해야 했습니다. 완전한 무음의 정보를 별도로 반영했고, 보통 박 사이의 짧은 공백은 유지했습니다.", "",
          "## 변경 시점과 고정 곡 대조", "",
          "곡 전체에서 두 시계의 교체점을 찾는 첫 방법은 실제 경계를 최대 약 166초 잘못 잡았습니다. 다른 구간이 계산에 끌려 들어왔기 때문입니다. 각 시계가 지지받는 구간을 먼저 찾고, 그 사이의 원래 시간축에서 변경점을 비교하는 보완을 실행했습니다.",
          "아래 표는 정답 BPM과 박 위치를 알려준 진단입니다. 반환한 시점의 오차와 놓친 경계를 구분해서 읽어야 합니다. 무음에서는 좁은 시점 하나보다 가능한 시간 범위가 중요하며, 알려준 정답 시계의 위상으로 얻는 정밀도는 자동 분석의 정밀도로 볼 수 없습니다.", "",
          "| 판정 창 | 실제 경계 | 반환 / 전체 | 놓침ㆍ모름 | 반환 시점의 오차 |", "| --- | --- | ---: | ---: | --- |"]
    for span, data in boundaries.items():
        value = data["summary"]["primary_real"]
        ko.append(f"| {span}박 | 기존 승인 지도와의 실용적 비교 | {value['returned_audio_boundaries']}/{value['boundary_denominator']} | {value['missed_or_unknown']} | {format_stats(value['absolute_seconds_error_returned'])} |")
    ko += ["", "고정 자료 280개 개발 그룹과 이미 사용한 검증 87개 그룹을 대조했습니다. 작은 변화 후보가 얼마나 생기는지와 얼마나 이어지는지를 함께 기록했습니다. 아직 제품의 최소 구간 길이나 합격 기준을 정하지 않았습니다.",
           "120.1 BPM의 참조는 그대로 두었습니다. 120 BPM으로 표현하면 박 위치가 서서히 밀릴 수 있지만, 그 밀림을 새로운 템포 구간으로 보상하면 안 됩니다. 짧은 창의 20ms 시간 눈금이 거짓 속도 변화를 만들 수 있는 검사도 추가했고, 시간 해상도로 생길 수 있는 오차를 반영했습니다.", "",
           "## 다음 판단", "",
           "먼저 여러 템포 후보의 위상과 실제 지지 구간을 신뢰할 수 있게 만드는 좁은 연구가 필요합니다. 짧은 구간ㆍ절반/두 배 관계ㆍ고정 곡의 오탐을 더 분명히 이해한 다음 자동 조합 단계로 넘어가는 것이 맞겠습니다.",
           "Original, 기존 26개 자료와 참조, 이전 실험, BPM 표현 범위, DAW는 유지했습니다. 예약된 98개 그룹은 사용하지 않았으며 소스 커밋ㆍ푸시는 실행하지 않았습니다.", "",
           "상세 조건ㆍ모든 분모ㆍ오차 분포ㆍ한계는 [영문 전체 보고서](report.md)와 [기계 판독 요약](summary.json)에 있습니다."]
    (run / "report.ko.md").write_text("\n".join(ko) + "\n", encoding="utf-8")


def figures(run, summary, support):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    directory = run / "figures"
    directory.mkdir()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    labels = ["Broad", "Final family", "Local top-20 union\n(anywhere; no phase proof)"]
    axes[0].bar(labels, [10, 5, 15], color=["#5088b0", "#c26453", "#519a75"])
    axes[0].set_ylim(0, 16)
    axes[0].set_ylabel("Recovered real segment-rate targets / 15")
    axes[0].set_title("Rate survival and proposal recovery")
    axes[1].bar(["Development", "Used validation"], [280, 87], color="#70899b")
    axes[1].set_ylabel("Fixed feature-group controls")
    axes[1].set_title("Reserved groups consumed: 0")
    fig.tight_layout()
    fig.savefig(directory / "candidate-and-cohorts.png", dpi=180)
    plt.close(fig)
    colors = {"MATCH": "#428965", "MISMATCH": "#be6658", "UNKNOWN": "#9ca6b0"}
    for ident in ("state_shirt_hospital_hill", "andrew-wade-a-day-to-remember", "jens-bogren-opeth", "step0_5100_silent_change"):
        ref = read_json(run / "evaluation-references" / f"{ident}.json")
        fig, ax = plt.subplots(figsize=(13, max(3.5, .7 * len(ref["clocks"]) + 1)))
        for i, clock in enumerate(ref["clocks"]):
            with np.load(run / "support-v6/predictions" / ident / f"{clock['clock_id']}-span8.npz") as data:
                t, states = data["times"], data["states"]
                for state, name in ((1, "MATCH"), (2, "MISMATCH"), (0, "UNKNOWN")):
                    ax.scatter(t[states == state], np.full(int(np.sum(states == state)), i), s=5, color=colors[name], marker="s", label=name if i == 0 else None)
        for i, segment in enumerate(ref["labeled_segments"]):
            ax.plot([segment["start_seconds"], segment["end_seconds"]], [i + .15, i + .15], color="black", linewidth=2)
        ax.set_yticks(range(len(ref["clocks"])), [f"{c['clock_id']}: {c['quarter_bpm']:.4g} BPM" for c in ref["clocks"]])
        ax.set_xlabel("Original audio seconds; black line = reference support")
        ax.set_title(f"Oracle quarter-clock support, 8-quarter windows: {ident}")
        ax.legend(loc="upper right")
        fig.tight_layout()
        fig.savefig(directory / f"support-{ident}.png", dpi=180)
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    values = gather(run)
    summary = values[0]
    write_json(run / "summary.json", summary)
    write_report(run, *values)
    figures(run, summary, values[3])
    print(summary["decision"])


if __name__ == "__main__":
    main()
