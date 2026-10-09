"""Prepare owner revalidation views of the catalog's unchanged reference maps."""

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.project_storage import SAMPLES, resolve_path
from tools.ntm_collection.storage import assert_candidate_allowed


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_path(value, relative_to=None):
    path = Path(value)
    if not path.is_absolute():
        direct = SAMPLES / path
        if direct.exists():
            path = direct
        elif relative_to is not None:
            path = Path(relative_to) / path
        else:
            path = direct
    path = resolve_path(path).absolute()
    if not path.resolve().is_relative_to(SAMPLES.resolve()):
        raise ValueError("Review assets must stay inside data/samples")
    return path


def event_time(event):
    if isinstance(event, (float, int)):
        return float(event)
    for key in ("master_seconds", "audio_seconds", "time_seconds", "project_seconds", "source_seconds"):
        if key in event:
            return float(event[key])
    raise ValueError("Reference event has no readable time coordinate")


def intervals(value):
    if not value:
        return []
    if len(value) == 2 and all(isinstance(n, (int, float)) for n in value):
        return [[float(value[0]), float(value[1])]]
    return [[float(a), float(b)] for a, b in value]


def tempo_info(value):
    rate = float(value)
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Invalid reference BPM")
    nearest = Fraction(rate).limit_denominator(4)
    nominal = float(nearest)
    period_delta = abs(60e6 / rate - 60e6 / nominal)
    if not 30 <= rate <= 400:
        kind = "out_of_domain"
    elif abs(rate - nominal) <= 1e-9:
        kind = "simple_fraction" if nearest.denominator > 1 else "integer"
    elif period_delta <= 1.00001:
        kind = "storage_precision"
    else:
        kind = "outside_vocabulary"
    return dict(bpm=rate, nearest_fraction=str(nearest), nominal_bpm=nominal,
                representation=kind, period_difference_microseconds=period_delta)


def normalize(ref, duration, support, offset=0.0, candidate=False):
    def time(event):
        already_relative = isinstance(event, dict) and any(k in event for k in ("master_seconds", "audio_seconds"))
        return event_time(event) + (offset if candidate and not already_relative else 0.0)

    tempos = []
    for i, event in enumerate(ref.get("tempo_events", [])):
        rate = next((event[k] for k in ("bpm_quarter", "bpm", "quarter_bpm") if k in event), None)
        if rate is None:
            raise ValueError("Tempo event has no quarter BPM")
        tempos.append(dict(key=f"tempo_{i}", time=time(event), quarter=event.get("quarter"),
                           microseconds_per_quarter=event.get("microseconds_per_quarter"),
                           **tempo_info(rate)))
    if not tempos and "quarter_bpm" in ref:
        tempos.append(dict(key="tempo_0", time=float(ref.get("first_beat_source_seconds", 0)),
                           quarter=None, microseconds_per_quarter=None,
                           **tempo_info(ref["quarter_bpm"])))
    meters = [dict(key=f"meter_{i}", time=time(e), numerator=int(e["numerator"]),
                   denominator=int(e["denominator"]), quarter=e.get("quarter"),
                   note=e.get("scope_note", "")) for i, e in enumerate(ref.get("meter_events", []))]
    if not meters and ref.get("meter"):
        m = ref["meter"]
        meters = [dict(key="meter_0", time=float(ref.get("first_beat_source_seconds", 0)),
                       numerator=m["numerator"], denominator=m["denominator"], quarter=None, note="")]

    if candidate:
        quarters = next(([time(e) for e in ref[k]] for k in ("quarters", "quarter_events", "quarter_beats_seconds") if k in ref), [])
        bars = next(([time(e) for e in ref[k]] for k in ("bars", "bar_events", "downbeats_seconds") if k in ref), [])
        beats = list(quarters)
    else:
        quarters = next(([time(e) for e in ref[k]] for k in
                         ("quarter_beats_seconds", "quarter_events", "beats_seconds", "beat_times_seconds")
                         if k in ref), [])
        beats = next(([time(e) for e in ref[k]] for k in ("beats_seconds", "beat_times_seconds") if k in ref), list(quarters))
        bars = next(([time(e) for e in ref[k]] for k in
                     ("downbeats_seconds", "bar_events", "bar_starts_seconds") if k in ref), None)
        if bars is None:
            bars = [time(e) for e in ref.get("quarter_events", []) if e.get("bar_start", e.get("accent", False))]

    half_open = "half-open" in ref.get("evaluation_scope", {}).get("boundary_semantics", "")
    no_grid = intervals(ref.get("free_time_seconds"))
    no_grid += intervals(ref.get("evaluation_scope", {}).get("no_grid_tail_seconds"))

    def audible(t):
        if not math.isfinite(t) or t < -1e-9 or t >= duration:
            return False
        if any(a - 1e-9 <= t < b - 1e-9 for a, b in no_grid):
            return False
        return any(a - 1e-9 <= t and (t < b - 1e-9 if half_open else t <= b + 1e-9) for a, b in support)

    def chosen(values):
        return sorted(set(max(0.0, v) for v in values if audible(v)))

    approved_label = "기록된 승인 박" if not candidate else "제공 시계의 박"
    if ref.get("quarters_per_rendered_click") == 2:
        approved_label += " · 2분음표"
    click_modes = [{"id": "approved", "label": approved_label,
                    "times": chosen(beats)}]
    if quarters != beats:
        click_modes.append({"id": "quarter", "label": "4분음표", "times": chosen(quarters)})
    if ref.get("compound_beat_times_seconds"):
        click_modes.append({"id": "compound", "label": "6/8 묶음 박", "times": chosen(ref["compound_beat_times_seconds"])})
    click_modes.append({"id": "bars", "label": "마디 첫 박만", "times": chosen(bars)})
    return dict(tempos=tempos, meters=meters, click_modes=click_modes, bars=chosen(bars),
                support_seconds=support, no_grid_seconds=no_grid,
                audio_relative_coordinates=True, additional_saved_offset_applied=0,
                stored_event_counts=dict(quarters=len(quarters), beats=len(beats), bars=len(bars)),
                available_map=bool(tempos and meters and quarters))


def issues_for(ident, ref, view, duration, source_documents):
    issues = []
    def add(key, text, time=0.0, kind="attention"):
        issues.append(dict(key="issue_" + key, text=text, time=time, kind=kind))
    for i, event in enumerate(view["tempos"]):
        if event["representation"] == "outside_vocabulary":
            add(f"rate_{i}", f"{event['bpm']:.12g} BPM은 분모 4 이하 후보와 정확히 일치하지 않습니다. 실제 정답 값의 유효성과 모델 표현 한계를 구분해 주세요.", event["time"], "information")
        if i and event["bpm"] == view["tempos"][i-1]["bpm"]:
            add(f"duplicate_tempo_{i}", f"같은 {event['bpm']:.12g} BPM이 다시 선언됩니다. 실제 변속 여부와 중복 메타데이터를 구분해 주세요.", event["time"])
        if event["time"] >= duration:
            add(f"outside_tempo_{i}", "이 템포 선언은 현재 음원의 끝보다 뒤에 있습니다.", event["time"])
        if i + 1 < len(view["tempos"]) and event["bpm"] != view["tempos"][i+1]["bpm"]:
            end = view["tempos"][i+1]["time"]
            length = end - event["time"]
            if 0 < length <= 4 * 60 / event["bpm"] + 1e-7:
                add(f"brief_tempo_{i}", f"다음 변화까지 {length:.6f}초입니다. 짧은 실제 구간인지 준비용 선언인지 검토해 주세요. 짧다는 이유만으로 무효로 판정하지 않았습니다.", event["time"])
    for i, event in enumerate(view["meters"]):
        if event["time"] >= duration:
            add(f"outside_meter_{i}", "이 박자표 선언은 현재 음원의 끝보다 뒤에 있습니다.", event["time"])
        if i and (event["numerator"],event["denominator"]) == (view["meters"][i-1]["numerator"],view["meters"][i-1]["denominator"]):
            add(f"same_meter_{i}", "같은 박자표의 재선언입니다. 마디 기준점 역할이 있는지 확인한 뒤 판정해 주세요. " + event.get("note", ""), event["time"], "information")
    source = ref.get("source_clock")
    if isinstance(source, dict):
        rows = source.get("tempo_events", [])
        if rows and rows[0].get("quarter", 0) > 0:
            add("leading_context", f"원본 MIDI의 첫 명시 템포는 프로젝트 {rows[0].get('project_seconds', 0):.6g}초부터입니다. 그 앞의 디코더 시간은 실제 음악 템포 선언과 구분되어 있습니다.", 0, "information")
        if rows and ref.get("accepted_bpm") is not None:
            old = rows[0].get("bpm", rows[0].get("bpm_quarter"))
            if old is not None and abs(old-ref["accepted_bpm"]) > .01:
                add("owner_semantics", f"원본 시계에는 {old:.12g} BPM이 보존되어 있고 현재 승인 값은 {ref['accepted_bpm']:.12g} BPM입니다. 현재 승인된 음악적 박 단위로 재검토해 주세요.", 0, "information")
    if ident == "rwc_p002":
        p = SAMPLES / "sources/public/five-source-small-pilot-20260929-v1/rwc_p002/midi-audit.json"
        if p.is_file():
            source_documents.append(("원본 MIDI 시계 검토 기록", p))
            add("raw_120", "원본 MIDI는 처음 2초에 120 BPM, 이후 100 BPM입니다. 현재 승인 맵에는 100 BPM만 채택되어 있습니다.", 0, "information")
    if ident == "doug-weier-real-friends-waiting-room":
        p = SAMPLES / "ntm/doug-weier-real-friends-waiting-room/collection/clock-source-audit.json"
        if p.is_file():
            audit = read(p)
            source_documents.append(("원본 프로젝트 선언 비교", p))
            if audit.get("reaper_initial_meter_agreement") is False:
                add("meter_source_conflict", "원본 MIDI·Studio One은 3/4, REAPER는 4/4를 선언합니다. 현재 승인 맵의 3/4를 음악과 대조해 주세요.")
    if ident == "jens-bogren-btbam-2019":
        add("unresolved_meter", "이 후보는 초반의 음악적 5/4 해석과 제공 프로젝트의 4/4 선언이 충돌하며 오프셋도 미확정입니다.")
    for note in ref.get("limits", []):
        if "awaits owner" in note.lower():
            continue
        add(f"limit_{len(issues)}", note, 0, "information")
    if view["no_grid_seconds"]:
        add("no_grid", "격자 밖으로 승인된 구간이 있습니다. 이 구간에서는 클릭을 연장하지 않고 끝부분의 처리도 확인해 주세요.", view["no_grid_seconds"][0][0], "information")
    return issues


def prepare(out):
    import soundfile as sf
    catalog_path = SAMPLES / "catalog.json"
    catalog = read(catalog_path)
    source_catalog_sha = fingerprint(catalog_path)
    assets = {}
    tracks = []

    def asset(path, route):
        if not path.is_file():
            return None
        stat = path.stat()
        assets[route] = dict(path=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        return route

    def append(track, group, ref, ref_path, audio_path, offset=0.0):
        ident = track["id"]
        assert_candidate_allowed(dict(slug=ident, title=track["title"], session_id=track.get("session_id")), "review")
        if not audio_path.is_file():
            raise ValueError("Review audio missing: " + ident)
        info = sf.info(audio_path)
        duration = info.frames / info.samplerate
        candidate = group == "candidate"
        support = intervals(track.get("reference_support_seconds"))
        if not support:
            support = intervals(ref.get("support_seconds")) or [[0.0, duration]]
        if candidate:
            end = ref.get("project_end_seconds")
            support = [[max(0.0, offset), min(duration, end+offset)]] if end and end+offset > max(0,offset) else [[0,duration]]
        view = normalize(ref, duration, support, offset, candidate)
        documents = []
        for item in track.get("original_clocks", []):
            try:
                documents.append((Path(item["path"]).name, sample_path(item["path"])))
            except ValueError:
                pass
        for item in track.get("owner_review_records", []):
            try:
                documents.append(("이전 승인 기록 · " + Path(item["path"]).name, sample_path(item["path"])))
            except ValueError:
                pass
        for key in ("acceptance_record", "acceptance_path", "source_clock_file"):
            if isinstance(ref.get(key), str):
                try:
                    documents.append(("이전 승인/시계 · " + Path(ref[key]).name,
                                      sample_path(ref[key], ref_path.parent)))
                except ValueError:
                    pass
        problems = issues_for(ident, ref, view, duration, documents)
        map_sha = fingerprint(ref_path)
        claimed_map_sha = track.get("reference", {}).get("sha256")
        if claimed_map_sha and map_sha != claimed_map_sha:
            problems.append(dict(key="issue_reference_identity", text="현재 맵 파일의 지문이 카탈로그에 기록된 지문과 다릅니다. 검토할 버전을 확인해 주세요.", time=0.0, kind="attention"))
        documents = list(dict.fromkeys(documents))
        downloads = []
        for i, (label, path) in enumerate(documents):
            route = asset(path, f"files/{ident}/{i}{path.suffix.lower()}")
            if route:
                downloads.append(dict(label=label, url=route))
        map_route = asset(ref_path, f"reference/{ident}.json")
        audio_route = asset(audio_path, f"audio/{ident}{audio_path.suffix.lower()}")
        original_offset = next((ref[k] for k in ("accepted_offset_seconds", "offset_seconds", "source_origin_shift_seconds") if k in ref), None)
        if candidate:
            original_offset = offset if view["available_map"] else None
        packet = dict(id=ident, title=track["title"], group=group, role=track.get("role", "acquired_candidate"),
            audio_url=audio_route, reference_url=map_route, source_downloads=downloads,
            audio_path=str(audio_path.relative_to(SAMPLES)), reference_path=str(ref_path.relative_to(SAMPLES)),
            duration_seconds=duration, sample_rate=info.samplerate, sample_frames=info.frames,
            channels=info.channels, audio_bytes=audio_path.stat().st_size,
            reference_sha256=map_sha, catalog_reference_sha256=claimed_map_sha,
            audio_catalog_sha256=track.get("audio", {}).get("sha256"), audio_bytes_hash_verified=False,
            previous_approval=not candidate, catalog_sha256=source_catalog_sha,
            stored_offset_seconds=original_offset, candidate_initial_offset_seconds=offset if candidate else None,
            candidate_offset_options=ref.get("candidates", []),
            qualification=track.get("qualification", {}), issues=problems,
            click_unit_note=ref.get("render_policy", ""), notes=ref.get("clock_note", ref.get("description", "")),
            **view)
        save(out / "tracks" / (ident+".json"), packet)
        tracks.append({k:packet[k] for k in ("id","title","group","role","duration_seconds","reference_sha256","audio_catalog_sha256","available_map")}
                      | dict(packet_url="tracks/"+ident+".json", issue_count=len(problems),
                             attention_count=sum(p["kind"]=="attention" for p in problems),
                             bpm_values=list(dict.fromkeys(e["bpm"] for e in packet["tempos"])),
                             meter_values=list(dict.fromkeys(f"{e['numerator']}/{e['denominator']}" for e in packet["meters"]))))

    for track in catalog["tracks"]:
        group = "auxiliary" if track["role"].startswith("auxiliary") else "formal"
        ref_path = sample_path(track["reference"]["path"])
        append(track, group, read(ref_path), ref_path, sample_path(track["audio"]["path"]))

    index = read(SAMPLES / "ntm-library-index.json")
    for record in index["recordings"]:
        if record.get("status") == "owner_accepted" or record.get("source_material_deleted"):
            continue
        assert_candidate_allowed(dict(slug=record["slug"], title=record["title"], session_id=record.get("session_id")), "review")
        home = SAMPLES / "ntm" / record["slug"] / "collection"
        ref_path = home / "review-data.json"
        if not ref_path.is_file():
            ref_path = home / "preparation-status.json"
        if not ref_path.is_file() or not (home/"master.wav").is_file():
            continue
        ref = read(ref_path)
        track = dict(id=record["slug"], title=record["title"], session_id=record.get("session_id"))
        append(track, "candidate", ref, ref_path, home/"master.wav", float(ref.get("initial_offset_seconds", 0)))

    counts = {group:sum(t["group"]==group for t in tracks) for group in ("formal","auxiliary","candidate")}
    save(out / "index-data.json", dict(schema_version=1, prepared_at_utc=datetime.now(timezone.utc).isoformat(),
        batch_id=out.name, catalog_sha256=source_catalog_sha, counts=counts, tracks=tracks,
        prior_approval_is_not_current_revalidation=True, snapshots_do_not_modify_catalog_or_references=True))
    save(out / "assets.json", dict(assets=assets))
    if not (out / "review-records.json").exists():
        save(out / "review-records.json", dict(schema_version=1, batch_id=out.name, records={}))
    print(json.dumps(dict(prepared_batch=str(out), counts=counts,
        formal_duration_minutes=round(sum(t["duration_seconds"] for t in tracks if t["group"]=="formal")/60,1),
        original_media_copied=False, original_maps_changed=False, owner_revalidation_completed=0), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.out.resolve())
