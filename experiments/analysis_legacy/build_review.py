"""Build the circle regression comparison and an offline A/B audition page.

Plot limits and audition jump points intentionally target this development song.
"""

import argparse
import html
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from fit_clock import grid_events
from run_beat_this import span_pulse_rate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--decoders", type=Path, required=True)
    parser.add_argument("--clock", type=Path, required=True)
    parser.add_argument("--onsets", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    baseline = json.loads((args.baseline / "result.json").read_text())
    decoders = json.loads((args.decoders / "comparison.json").read_text())
    clock = json.loads((args.clock / "clock.json").read_text())
    onsets = json.loads((args.onsets / "analysis.json").read_text())
    reference = json.loads(args.reference.read_text())["reference"]["events"]
    duration = baseline["audio"]["duration_seconds"]
    fig, axes = plt.subplots(3, 1, figsize=(13,10), layout="constrained")
    for name, label, color in [("official_minimal", "Official minimal", "#b45662"), ("legacy_default", "Historical DBN", "#276ab0"), ("legacy_high_prior", "Forced high-rate control (not selected)", "#a5a5a5")]:
        if name in decoders["variants"]:
            t, rate = span_pulse_rate(decoders["variants"][name]["beats_seconds"])
            axes[0].plot(t, rate, label=label, color=color, alpha=.85, linewidth=1.)
    axes[0].set(ylabel="Predicted pulses / minute", title="Decoder comparison on identical final0 logits")
    starts = [s["start_seconds"] for s in clock["segments"]]
    rates = [2*s["pulse_rate_per_minute"] for s in clock["segments"]]
    axes[1].step(starts + [clock["segments"][-1]["end_seconds"]], rates + [rates[-1]], where="post", color="#237a57", label="Unselected x2 clock candidate")
    rt = [float(s["time_seconds"]) for s in reference]
    rb = [float(s["bpm"]) for s in reference]
    axes[1].step(rt+[duration], rb+[rb[-1]], where="post", color="#d18831", linestyle="--", label="Historical reference (audio origin unverified)")
    centers, peaks = [], []
    for window in onsets["periodicity_windows"]:
        if window["candidates"]:
            centers.append(window["center_seconds"])
            peaks.append(window["candidates"][0]["rate_per_minute"])
    axes[1].scatter(centers, peaks, s=18, color="#514b9c", label="Strongest audio periodicity (24-second windows)")
    axes[1].set(ylabel="Rate / minute", ylim=(200,214), title="Independent acoustic evidence; musical quarter-note level remains unaccepted")
    observed = np.asarray(decoders["variants"]["legacy_default"]["beats_seconds"])
    fitted = grid_events(clock)
    axes[2].plot(observed, 1000*(observed-fitted), linewidth=.7, color="#276ab0")
    axes[2].axhline(0, color="gray", linewidth=.5)
    axes[2].set(ylabel="Fit residual (milliseconds)", title="Residual against predicted events, NOT timing error against ground truth")
    for ax in axes:
        ax.set(xlim=(0,duration), xlabel="Unshifted source time (seconds)")
        ax.grid(alpha=.2)
    axes[0].legend(fontsize=8)
    axes[1].legend(fontsize=8)
    args.output_dir.mkdir(parents=True)
    fig.savefig(args.output_dir / "comparison.png", dpi=160)
    plt.close(fig)
    tracks = [("원본", args.audio), ("공식 모델의 기존 결과", args.baseline / "preview.wav"),
              ("기존 디코더: 약 102.5 / 105", args.decoders / "legacy_default" / "preview.wav"),
              ("새 연속 지도: 205 / 210 계열 후보", args.clock / "pulse-x2" / "preview.wav")]
    cards = []
    for label, path in tracks:
        if not path.is_file():
            raise ValueError(f"missing audition file: {path}")
        relative = html.escape(os.path.relpath(path, args.output_dir), quote=True)
        cards.append(f'<div class="track"><b>{html.escape(label)}</b><audio controls preload="metadata" src="{relative}"></audio></div>')
    page = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Joljak 분석 비교</title><style>body{max-width:1100px;margin:40px auto;padding:0 20px;font:16px/1.6 system-ui;background:#f5f6f8;color:#202a36}h1{font-size:26px}img{width:100%;background:white}.track{padding:14px;margin:10px 0;background:white;border-radius:8px}audio{display:block;width:100%;margin-top:8px}button{margin:4px;padding:8px 14px;border:1px solid #b8c6d4;border-radius:6px;background:white;cursor:pointer}.notice{padding:16px;background:#fff2d9}</style>
<h1>동일 음원 · 디코더와 템포 지도 비교</h1>
<p>원본 시간과 길이는 같습니다. 다른 플레이어를 재생하면 직전 재생 위치에서 이어서 비교합니다. 볼륨은 미리듣기별 정규화로 조금 다를 수 있습니다.</p>
<p class="notice">205/210 표기는 검토할 후보이며 자동 확정된 정답이 아닙니다. 새 지도에는 마디 첫 박 강조가 없습니다. 기존 Cubase 지도와 음원의 정렬도 확인되지 않았습니다.</p>
<div id="jumps"></div>TRACKS<img src="comparison.png" alt="디코더별 주기와 템포 지도, 예측 박자에 대한 적합 잔차 비교">
<p>검토할 사항: 후반부 클릭 속도가 안정적인지, 205/210 후보의 클릭이 연주에 맞는지, 약 147·185·205초 주변에서 변화가 자연스러운지.</p>
<script>let active=null;const players=[...document.querySelectorAll('audio')];for(const p of players){p.addEventListener('play',()=>{if(active&&active!==p){p.currentTime=active.currentTime;active.pause()}active=p})}for(const [label,t] of [['처음',0],['초반 10초',10],['변화 부근 143초',143],['변화 부근 181초',181],['후반 202초',202]]){const b=document.createElement('button');b.textContent=label;b.onclick=()=>{for(const p of players)p.currentTime=t};document.querySelector('#jumps').append(b)}</script></html>'''
    (args.output_dir / "index.html").write_text(page.replace("TRACKS", "\n".join(cards)), encoding="utf-8")
    print(args.output_dir / "index.html")


if __name__ == "__main__":
    main()
