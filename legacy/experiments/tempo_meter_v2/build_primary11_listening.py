"""Build a private eleven-song predicted-map listening review bundle.

Canonical source WAVs are linked, never rewritten. Each source-only prediction
is rendered to a native-clock mono click with accented predicted bar starts.
No owner reference map is opened and no listening judgment is inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import sys

import numpy as np
import soundfile as sf

from .run_constant_grid11 import digest, read_bound

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis_legacy"))
from music_map_contract import interpolate_clock, prepare_map, render_bars


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "data/corpus/primary-references-v4/catalog.json"
PREDICTIONS = ROOT / "data/runs/tempo-meter-v2/primary11-phrase-chain-20260927-v1/prediction-manifest.json"
SCORE = ROOT / "data/runs/tempo-meter-v2/primary11-phrase-chain-20260927-v1/scoring-fp-gate-v3/summary.json"


def quarter_events(value: dict) -> list[float]:
    prepared = prepare_map(value)
    knots = prepared["clock_knots"]
    lo = math.ceil(knots[0]["pulse"] - 1e-9)
    hi = math.floor(knots[-1]["pulse"] + 1e-9)
    return [time for pulse in range(lo, hi+1)
            if (time := interpolate_clock(knots, float(pulse))) < prepared["duration_seconds"]
            and any(start - 1e-9 <= time < end for start, end in prepared["support_seconds"])]


def bar_events(value: dict) -> list[float]:
    prepared = prepare_map(value)
    bars = render_bars(prepared)
    if bars["status"] != "rendered":
        raise ValueError(f"predicted map cannot render bars: {bars['status']}")
    return [time for time in bars["bar_events_seconds"]
            if 0 <= time < prepared["duration_seconds"]
            and any(start - 1e-9 <= time < end for start, end in prepared["support_seconds"])]


def source_events(value: dict) -> dict:
    prepared = prepare_map(value)
    knots = prepared["clock_knots"]
    unit = prepared["quarters_per_pulse"]
    quarters_per_pulse = unit["numerator"] / unit["denominator"]
    tempo = []
    for first, last in zip(knots, knots[1:]):
        bpm = 60 * (last["pulse"]-first["pulse"]) * quarters_per_pulse / (
            last["source_seconds"]-first["source_seconds"])
        start = max(0.0, first["source_seconds"])
        end = min(prepared["duration_seconds"], last["source_seconds"])
        if end <= start:
            continue
        if tempo and abs(tempo[-1]["bpm"]-bpm) < 1e-5 and abs(tempo[-1]["end_seconds"]-start) < 1e-7:
            tempo[-1]["end_seconds"] = end
        else:
            tempo.append({"start_seconds": start, "end_seconds": end, "bpm": bpm})
    meter = []
    for event in prepared["meter_events"]:
        time = interpolate_clock(knots, event["pulse"])
        meter.append({"source_seconds": time, "pulse": event["pulse"],
                      "numerator": event["numerator"], "denominator": event["denominator"]})
    return {"tempo_segments": tempo, "meter_events": meter}


def _tick(sample_rate: int, *, accent: bool) -> np.ndarray:
    count = max(2, round(.035 * sample_rate))
    seconds = np.arange(count, dtype=np.float64) / sample_rate
    frequency = 1760.0 if accent else 880.0
    amplitude = .63 if accent else .38
    pulse = amplitude * np.exp(-95 * seconds) * (
        .78 * np.cos(2*math.pi*frequency*seconds) +
        .22 * np.cos(2*math.pi*frequency*1.9*seconds))
    tail = max(1, round(.004 * sample_rate))
    pulse[-tail:] *= np.linspace(1, 0, tail)
    return pulse.astype(np.float32)


def render_click(path: Path, *, sample_rate: int, sample_frames: int,
                 quarters: list[float], bars: list[float]) -> dict:
    quarter_frames = [round(time*sample_rate) for time in quarters]
    bar_frames = {round(time*sample_rate) for time in bars}
    if (not quarter_frames or any(b <= a for a, b in zip(quarter_frames, quarter_frames[1:])) or
            quarter_frames[0] < 0 or quarter_frames[-1] >= sample_frames or
            not bar_frames.issubset(quarter_frames)):
        raise ValueError("click events must be ordered source frames with bars on quarters")
    output = np.zeros(sample_frames, dtype=np.float32)
    ordinary = _tick(sample_rate, accent=False)
    accented = _tick(sample_rate, accent=True)
    for frame in quarter_frames:
        sound = accented if frame in bar_frames else ordinary
        end = min(sample_frames, frame+len(sound))
        output[frame:end] += sound[:end-frame]
    peak = float(np.max(np.abs(output)))
    if peak > .99:
        raise ValueError(f"click waveform clips: {peak}")
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, output, sample_rate, subtype="PCM_16")
    info = sf.info(path)
    if (info.frames, info.samplerate, info.channels, info.subtype) != (
            sample_frames, sample_rate, 1, "PCM_16"):
        raise ValueError("written click has a different source sample clock")
    return {"sha256": digest(path), "bytes": path.stat().st_size,
            "quarter_click_count": len(quarter_frames), "accented_bar_count": len(bar_frames),
            "peak_before_pcm16_quantization": peak,
            "first_quarter_frame": quarter_frames[0], "last_quarter_frame": quarter_frames[-1]}


def _page(template: str, payload: dict, note_namespace: str) -> str:
    embedded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    if template.count("__REVIEW_DATA__") != 1:
        raise ValueError("review page template placeholder changed")
    return template.replace("__REVIEW_DATA__", embedded).replace(
        "joljak-primary11-review-v1:", note_namespace + ":")


def _index(rows: list[dict], note_namespace: str) -> str:
    cards = []
    for number, row in enumerate(rows, 1):
        name = html.escape(row["name"])
        role = html.escape(row["recording_role"])
        cards.append(f'<a class="card" href="{row["id"]}/review.html"><span class="number">{number:02d}</span><span><strong>{name}</strong><small>{role}</small><small>{row["duration_seconds"]/60:.1f}분 · BPM 전환 {row["tempo_change_count"]} · 박자 전환 {row["meter_change_count"]}</small></span><span class="arrow">듣기 →</span></a>')
    page = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>11곡 템포 지도 청취 검토</title><style>
body{margin:0;background:#f1f5f8;color:#172638;font:16px/1.55 system-ui,"Noto Sans KR",sans-serif}main{max-width:1040px;margin:auto;padding:30px 18px 70px}h1{margin:0 0 8px;font-size:2rem}.lead{color:#536679;margin:0 0 20px}.notice{background:#fff8e8;border-left:4px solid #c88922;padding:12px 16px;border-radius:5px;margin:20px 0}.list{display:grid;gap:10px}.card{display:flex;gap:16px;align-items:center;padding:15px 18px;background:#fff;border:1px solid #d5e0e9;border-radius:12px;text-decoration:none;color:inherit}.card:hover,.card:focus-visible{border-color:#216cad;background:#f7fbff}.number{font-weight:800;color:#216cad;min-width:2rem}.card strong{display:block;font-size:1.05rem}.card small{display:block;color:#5b6a79}.arrow{margin-left:auto;white-space:nowrap;color:#216cad;font-weight:700}button{font:inherit;border:1px solid #adc3d8;color:#154d80;background:white;border-radius:8px;padding:8px 13px;cursor:pointer}button:hover{background:#e9f4ff}.actions{margin:22px 0}.status{font-size:.88rem;color:#526779;margin-left:10px}@media(max-width:650px){.card{align-items:flex-start}.arrow{font-size:.87rem}}
</style></head><body><main><h1>11곡 템포 지도 청취 검토</h1><p class="lead">현재 실험 알고리즘이 만든 원곡 기준 클릭과 BPM·박자 지도를 한 곡씩 들어보세요.</p><p class="notice">이 페이지는 <strong>예측 결과</strong>를 듣는 용도입니다. 강한 클릭은 예측한 마디 시작, 작은 클릭은 4분음표 박입니다. 원곡과 클릭은 같은 시간축으로 재생됩니다. 여기서 확인해도 정답 지도가 자동으로 수정되지는 않습니다.</p><div class="actions"><button id="exportAll" type="button">저장한 11곡 검토 메모 JSON 받기</button><span id="reviewCount" class="status"></span></div><div class="list">""" + "".join(cards) + """</div></main><script>
const IDS=""" + json.dumps([row["id"] for row in rows]) + """;
function reviewKey(id){return 'joljak-primary11-review-v1:'+id}
function refresh(){let done=0;for(const id of IDS){try{const v=JSON.parse(localStorage.getItem(reviewKey(id))||'null');if(v?.status&&v.status!=='unreviewed')done++}catch(_){}}document.getElementById('reviewCount').textContent=`${done}/11곡 판단 저장됨 (이 브라우저에만 저장)`}
document.getElementById('exportAll').onclick=()=>{const entries=[];for(const id of IDS){try{const v=JSON.parse(localStorage.getItem(reviewKey(id))||'null');if(v)entries.push(v)}catch(_){}}const blob=new Blob([JSON.stringify({schema_version:1,kind:'owner_listening_notes_not_automatic_ground_truth',exported_at:new Date().toISOString(),entries},null,2)+'\\n'],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='joljak-11-song-listening-notes.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
refresh();window.addEventListener('storage',refresh);
</script></body></html>"""
    return page.replace("joljak-primary11-review-v1:", note_namespace + ":")


def build(output: Path, *, prediction_manifest: Path = PREDICTIONS,
          score_summary: Path = SCORE) -> dict:
    if output.exists():
        raise FileExistsError("review output must be a new directory")
    catalog = json.loads(CATALOG.read_text())
    predictions = json.loads(prediction_manifest.read_text())
    score = json.loads(score_summary.read_text())
    note_namespace = (
        "joljak-primary11-review-v1"
        if prediction_manifest.resolve() == PREDICTIONS.resolve()
        else "joljak-primary11-review-" + digest(prediction_manifest)[:12])
    if (catalog["track_count"] != 11 or len(predictions.get("rows", [])) != 11 or
            predictions.get("complete") is not True or
            predictions.get("references_available_to_runner") is not False or
            score.get("total_songs") != 11):
        raise ValueError("current complete eleven-song source-only proposal required")
    by_id = {row["id"]: row for row in predictions["rows"]}
    if {row["id"] for row in catalog["tracks"]} != set(by_id):
        raise ValueError("prediction and primary-corpus identities differ")
    template_path = Path(__file__).with_name("primary11_listening.html")
    template = template_path.read_text()
    validated = []
    for track in catalog["tracks"]:
        row = by_id[track["id"]]
        audio = Path(track["canonical_audio"]["path"])
        prediction = read_bound(row["prediction"])
        info = sf.info(audio)
        geometry = row["source"]
        if (digest(audio) != track["canonical_audio"]["sha256"] or
                geometry != {"sha256": track["canonical_audio"]["sha256"],
                             "sample_rate": info.samplerate, "sample_frames": info.frames} or
                info.frames/info.samplerate != track["canonical_audio"]["duration_seconds"]):
            raise ValueError(f"source audio or sample clock changed: {track['id']}")
        value = json.loads(prediction.read_text())
        if value["map"]["source"] != geometry:
            raise ValueError(f"predicted map uses another source: {track['id']}")
        prepared = prepare_map(value["map"])
        if not prepared["capability"]["meter_declared"]:
            raise ValueError(f"prediction has no meter map: {track['id']}")
        quarters = quarter_events(value["map"])
        bars = bar_events(value["map"])
        segments = source_events(value["map"])
        validated.append((track, row, audio, prediction, info, quarters, bars, segments))
    output.mkdir(parents=True)
    rows = []
    for track, row, audio, prediction, info, quarters, bars, segments in validated:
        folder = output/track["id"]
        folder.mkdir()
        (folder/"source.wav").symlink_to(audio.resolve())
        shutil.copy2(prediction, folder/"predicted-map.json")
        click = render_click(folder/"predicted-click.wav", sample_rate=info.samplerate,
                             sample_frames=info.frames, quarters=quarters, bars=bars)
        payload = {"schema_version": 1, "kind": "source_only_prediction_listening_review",
                   "human_review_status": "not_reviewed",
                   "id": track["id"], "name": track["name"],
                   "recording_role": track["recording_role"],
                   "source": {"url": "source.wav", "sha256": row["source"]["sha256"],
                              "sample_rate": info.samplerate, "sample_frames": info.frames,
                              "duration_seconds": info.frames/info.samplerate},
                   "click": {"url": "predicted-click.wav", **click},
                   "prediction": {"url": "predicted-map.json",
                                  "sha256": row["prediction"]["sha256"],
                                  "bar_count": len(bars), "quarter_count": len(quarters),
                                  **segments},
                   "quarter_times_seconds": quarters,
                   "bar_times_seconds": bars,
                   "audio_origin_shift_seconds": 0,
                   "click_semantics": "every predicted quarter; stronger higher click on predicted bar start",
                   "not_reference_or_owner_acceptance": True}
        (folder/"review-data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
        (folder/"review.html").write_text(_page(template, payload, note_namespace))
        rows.append({"id": track["id"], "name": track["name"],
                     "recording_role": track["recording_role"],
                     "duration_seconds": payload["source"]["duration_seconds"],
                     "source_sha256": row["source"]["sha256"],
                     "prediction_sha256": row["prediction"]["sha256"],
                     "click_sha256": click["sha256"],
                     "click_bytes": click["bytes"],
                     "quarter_click_count": click["quarter_click_count"],
                     "accented_bar_count": click["accented_bar_count"],
                     "tempo_change_count": max(0, len(segments["tempo_segments"])-1),
                     "meter_change_count": max(0, len(segments["meter_events"])-1),
                     "review_page": str((folder/"review.html").resolve())})
        print(track["id"], click["quarter_click_count"], click["accented_bar_count"], flush=True)
    (output/"index.html").write_text(_index(rows, note_namespace))
    manifest = {"schema_version": 1, "complete": True,
                "purpose": "owner listening of current source-only predictions; no reference click or human acceptance",
                "catalog_sha256": digest(CATALOG),
                "prediction_manifest_sha256": digest(prediction_manifest),
                "score_summary_sha256": digest(score_summary),
                "review_note_namespace": note_namespace,
                "builder_sha256": digest(Path(__file__)),
                "template_sha256": digest(template_path),
                "source_files_modified": False,
                "source_time_offset_seconds": 0,
                "tracks": rows}
    (output/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, default=PREDICTIONS)
    parser.add_argument("--score-summary", type=Path, default=SCORE)
    args = parser.parse_args()
    result = build(args.output.resolve(),
                   prediction_manifest=args.candidate_manifest.resolve(),
                   score_summary=args.score_summary.resolve())
    print(json.dumps({"complete": result["complete"], "tracks": len(result["tracks"]),
                      "output": str(args.output.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
