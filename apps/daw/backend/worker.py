"""Local media jobs and an adapter to the frozen fixed-metronome model.

No reference files are read. Source recordings are never edited. Analysis scopes
are sample-aligned windows of a decoded original; raw hints are opened only after
the complete audio family is prepared. All stdout messages are JSON lines.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import struct
import sys

import numpy as np
import soundfile as sf
import soxr

DEFAULT_CLICK_GAIN = 0.7 * 10 ** (6 / 20)


def emit(stage, **fields):
    print(json.dumps({"stage": stage, **fields}, allow_nan=False), flush=True)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def decode(job):
    output = Path(job["output"])
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    for index, item in enumerate(job["files"]):
        path = Path(item["path"])
        folder = output / item["id"]
        folder.mkdir(exist_ok=True)
        with sf.SoundFile(path) as source:
            if source.channels not in (1, 2) or source.frames <= 0:
                raise ValueError("Import mono or stereo audio with at least one sample")
            bin_frames = 256
            peaks = []
            decoded_frames = 0
            playback_frames = 0
            resampler = soxr.ResampleStream(source.samplerate, 48000, source.channels, dtype='float32', quality='HQ') if source.samplerate != 48000 else None
            playback = (folder / 'playback.f32').open('wb') if resampler else None
            with (folder / "audio.f32").open("wb") as pcm:
                for block in source.blocks(blocksize=bin_frames * 1024, dtype="float32", always_2d=True):
                    if not np.isfinite(block).all():
                        raise ValueError("Source contains non-finite audio samples")
                    pcm.write(block.astype("<f4", copy=False).tobytes())
                    decoded_frames += len(block)
                    if resampler:
                        rendered = resampler.resample_chunk(block)
                        playback.write(rendered.astype('<f4', copy=False).tobytes())
                        playback_frames += len(rendered)
                    pad = (-len(block)) % bin_frames
                    padded = np.pad(block, ((0, pad), (0, 0))) if pad else block
                    bins = padded.reshape(-1, bin_frames, source.channels)
                    peaks.append(np.column_stack((bins.min(axis=(1, 2)), bins.max(axis=(1, 2)))))
                    emit("Decoding audio", progress=(index + source.tell() / len(source)) / len(job["files"]), name=path.name)
            if resampler:
                tail = resampler.resample_chunk(np.empty((0, source.channels), dtype=np.float32), last=True)
                playback.write(tail.astype('<f4', copy=False).tobytes())
                playback_frames += len(tail)
            if playback:
                playback.close()
            expected = item.get('expected')
            if expected and (source.samplerate != expected['sampleRate'] or source.channels != expected['channels'] or decoded_frames != expected['frames']):
                raise ValueError('Relocated audio geometry differs from the saved original. Choose the original recording.')
            wave = np.concatenate(peaks).astype("<f4")
            wave.tofile(folder / "peaks.f32")
            stat = path.stat()
            asset = {"id": item["id"], "name": item.get("name", path.name), "sourcePath": str(path),
                     "pcmPath": str(folder / "audio.f32"), "peaksPath": str(folder / "peaks.f32"),
                     "playbackPath": str(folder / 'playback.f32' if resampler else folder / 'audio.f32'),
                     "playbackRate": 48000, "playbackFrames": playback_frames if resampler else decoded_frames,
                     "sampleRate": source.samplerate, "channels": source.channels, "frames": decoded_frames,
                     "duration": decoded_frames / source.samplerate, "peakBinFrames": bin_frames,
                     "peakBins": len(wave), "originalSize": stat.st_size,
                     "originalModified": stat.st_mtime_ns / 1_000_000}
            write_json(folder / "asset.json", asset)
            assets.append(asset)
    return {"assets": assets}


def analyze(job):
    root = Path(job["analysisRoot"])
    sys.path.insert(0, str(root))
    import torch
    from beat_this.inference import Audio2Frames
    from experiments.metronome_reconstruction_v1.infer import make_evidence
    from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family, select_from_family, validate_hint_row

    config_path = root / "experiments/metronome_reconstruction_v1/config-tap-v2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    asset = job["asset"]
    first = max(0, round(job["sourceStart"] * asset["sampleRate"]))
    last = min(asset["frames"], round(job["sourceEnd"] * asset["sampleRate"]))
    if last <= first:
        raise ValueError("Select a non-empty audio range")
    output = Path(job["output"])
    output.mkdir(parents=True, exist_ok=False)
    inputs = {"assetId": asset["id"], "name": asset["name"], "sourcePath": asset["sourcePath"],
              "sampleRate": asset["sampleRate"], "channels": asset["channels"],
              "firstSourceFrame": first, "lastSourceFrameExclusive": last,
              "sourceStart": first / asset["sampleRate"], "sourceEnd": last / asset["sampleRate"],
              "scope": "selected_audio_only", "referenceFilesRead": False,
              "modelContract": "fixed-metronome-tap-only26-v2"}
    write_json(output / "source-input.json", inputs)
    write_json(output / "config.json", config)
    emit("Loading the fixed-metronome model")
    torch.set_num_threads(config["torch_threads"])
    tracker = Audio2Frames(job["checkpoint"], device=config["device"], float16=False)
    pcm = np.memmap(asset["pcmPath"], dtype="<f4", mode="r", shape=(asset["frames"], asset["channels"]))
    signal = np.array(pcm[first:last], dtype=np.float32)
    emit("Extracting beat and downbeat evidence")
    beat, down = tracker(signal, asset["sampleRate"])
    duration = len(signal) / asset["sampleRate"]
    evidence = make_evidence(beat.cpu().numpy(), down.cpu().numpy(), duration, config)
    np.savez_compressed(output / "evidence.npz", beat_logits=beat.cpu().numpy(), downbeat_logits=down.cpu().numpy(), fps=config["fps"], duration_seconds=duration)
    del signal, beat, down, tracker
    emit("Preparing every audio candidate before reading the tap")
    family = prepare_audio_family(evidence, config)
    write_json(output / "audio-family.json", family)
    # This is the first and only read of continuous tap input.
    hint = json.loads(Path(job["hintPath"]).read_text(encoding="utf-8"))
    validate_hint_row(hint)
    tap = hint.get("initial_quarter_bpm_tap")
    emit("Selecting the initial metrical layer")
    prediction = select_from_family(family, tap)
    write_json(output / "prediction.json", prediction)
    write_json(output / "raw-tap-receipt.json", hint)
    result = {"id": job["id"], "clipId": job["clipId"], "assetId": asset["id"],
              "sourceStart": inputs["sourceStart"], "sourceEnd": inputs["sourceEnd"],
              "initialTap": tap, "createdAt": datetime.now(timezone.utc).isoformat(),
              "result": prediction, "recordPath": str(output / "analysis.json")}
    write_json(output / "analysis.json", result)
    return result


def analysis_geometry(project):
    clips = {c["id"]: c for c in project["clips"]}
    regions = []
    for region in project["clocks"]:
        clip = clips.get(region["clipId"])
        origin = clip["start"] - clip["sourceStart"] if clip else region.get('projectOrigin')
        if origin is None:
            continue
        source_start = max(region["sourceStart"], clip["sourceStart"]) if clip else region["sourceStart"]
        source_end = min(region["sourceEnd"], clip["sourceStart"] + clip["duration"]) if clip else region["sourceEnd"]
        start = max(0, origin + source_start)
        end = origin + source_end
        if end > start:
            regions.append({**region["values"], "id": region["id"], "start": start, "end": end,
                            "phase": origin + region["sourceStart"] + region["values"]["offset"]})
    return regions


def musical_map(project):
    tempos = sorted(project['tempos'], key=lambda event: event['quarter'])
    if not tempos or tempos[0]['quarter'] != 0:
        tempos.insert(0, {'id': 'whole-project-tempo', 'quarter': 0, 'bpm': project.get('bpm', 120)})
    points = sorted(project['signatures'], key=lambda event: event['bar'])
    signature = project.get('signature', {'numerator': 4, 'denominator': 4})
    if not points or points[0]['bar'] != 1:
        points.insert(0, {'id': 'whole-project-signature', 'bar': 1, **signature})
    signatures, quarter, previous_bar, previous_length = [], 0.0, 1, signature['numerator'] * 4 / signature['denominator']
    for event in points:
        quarter += (event['bar'] - previous_bar) * previous_length
        previous_bar = event['bar']
        previous_length = event['numerator'] * 4 / event['denominator']
        signatures.append({**event, 'quarter': quarter, 'barLength': previous_length})
    def seconds_at(position):
        seconds = 0.0
        for index, tempo in enumerate(tempos):
            stop = min(position, tempos[index + 1]['quarter'] if index + 1 < len(tempos) else position)
            seconds += max(0, stop - tempo['quarter']) * 60 / tempo['bpm']
            if stop >= position:
                break
        return seconds
    def quarter_at(seconds):
        at = 0.0
        for index, tempo in enumerate(tempos):
            stop = tempos[index + 1]['quarter'] if index + 1 < len(tempos) else math.inf
            duration = (stop - tempo['quarter']) * 60 / tempo['bpm']
            if seconds <= at + duration + 1e-8:
                return tempo['quarter'] + (seconds - at) * tempo['bpm'] / 60
            at += duration
        return 0.0
    return tempos, signatures, seconds_at, quarter_at


def geometry(project, end=None):
    if project.get('version', 1) == 1:
        return analysis_geometry(project)
    tempos, signatures, seconds_at, quarter_at = musical_map(project)
    last = quarter_at(end if end is not None else project['projectDuration'])
    edges = sorted({q for q in [0, last, *[t['quarter'] for t in tempos], *[s['quarter'] for s in signatures]] if 0 <= q <= last})
    regions = []
    for quarter, stop in zip(edges, edges[1:]):
        tempo = next(t for t in reversed(tempos) if t['quarter'] <= quarter + 1e-8)
        signature = next(s for s in reversed(signatures) if s['quarter'] <= quarter + 1e-8)
        bars = math.floor((quarter - signature['quarter'] + 1e-8) / signature['barLength'])
        bar_start = signature['quarter'] + bars * signature['barLength']
        start = seconds_at(quarter)
        regions.append({'id': f"{tempo['id']}:{signature['id']}", 'bpm': tempo['bpm'],
                        'numerator': signature['numerator'], 'denominator': signature['denominator'],
                        'start': start, 'end': seconds_at(stop), 'phase': start - (quarter - bar_start) * 60 / tempo['bpm']})
    return regions


def mix_block(project, assets, times, track_id=None):
    mix = np.zeros((len(times), 2), dtype=np.float64)
    tracks = {t["id"]: t for t in project["tracks"]}
    any_solo = any(t["solo"] for t in tracks.values())
    covered = {}
    for clip in reversed(project["clips"]):
        track = tracks.get(clip["trackId"])
        if not track or (track_id and track_id != track["id"]) or track["mute"] or (any_solo and not track["solo"]):
            continue
        keep = (times >= clip["start"]) & (times < clip["start"] + clip["duration"])
        if track["id"] not in covered:
            covered[track["id"]] = np.zeros(len(times), dtype=bool)
        keep &= ~covered[track["id"]]
        covered[track["id"]] |= keep
        if not keep.any():
            continue
        asset, pcm = assets[clip["assetId"]]
        positions = (times[keep] - clip["start"] + clip["sourceStart"]) * asset.get('playbackRate', asset["sampleRate"])
        floor = np.floor(positions).astype(np.int64)
        alpha = positions - floor
        playback_frames = asset.get('playbackFrames', asset['frames'])
        floor = np.clip(floor, 0, playback_frames - 1)
        after = np.minimum(floor + 1, playback_frames - 1)
        samples = pcm[floor] * (1 - alpha[:, None]) + pcm[after] * alpha[:, None]
        pan, gain = track["pan"], track["gain"]
        if asset["channels"] == 1:
            angle = (pan + 1) * math.pi / 4
            mix[keep, 0] += samples[:, 0] * math.cos(angle) * gain
            mix[keep, 1] += samples[:, 0] * math.sin(angle) * gain
        else:
            mix[keep, 0] += samples[:, 0] * min(1, 1 - pan) * gain
            mix[keep, 1] += samples[:, 1] * min(1, 1 + pan) * gain
    return mix * project["masterGain"]


def click_block(regions, times):
    click = np.zeros(len(times), dtype=np.float64)
    covered = np.zeros(len(times), dtype=bool)
    for region in reversed(regions):
        valid = (times >= region["start"]) & (times < region["end"])
        valid &= ~covered
        covered |= valid
        step = 60 / region["bpm"] * 4 / region["denominator"]
        beat = np.floor((times - region["phase"]) / step + 1e-9).astype(np.int64)
        age = times - (region["phase"] + beat * step)
        active = valid & (age >= 0) & (age < .035)
        strong = (beat % region["numerator"]) == 0
        freq = np.where(strong, 1600.0, 1050.0)
        click[active] += np.sin(2 * math.pi * freq[active] * age[active]) * np.exp(-age[active] / .006) * np.where(strong[active], .32, .20)
    return np.column_stack((click, click))


def vlq(value):
    value = max(0, int(value))
    result = [value & 127]
    while value >> 7:
        value >>= 7
        result.insert(0, (value & 127) | 128)
    return bytes(result)


def write_midi(path, regions, start, end):
    # MIDI is a quantized interchange derivative. Exact second scopes and phase
    # remain in JSON; this file never regenerates an accepted reference.
    ppq = 960
    boundaries = {start, end}
    for r in regions:
        if r['end'] > start and r['start'] < end:
            boundaries.update((max(start, r['start']), min(end, r['end'])))
    edges = sorted(boundaries)
    segments, changes = [], []
    for at, stop in zip(edges, edges[1:]):
        active = next((r for r in reversed(regions) if r['start'] <= at < r['end']), None)
        segments.append((at, stop, active))
        bpm = active['bpm'] if active else 120.0
        if not changes or changes[-1][1] != bpm:
            changes.append((at, bpm))
    def tick(time):
        total = 0.0
        for i, (at, bpm) in enumerate(changes):
            stop = changes[i + 1][0] if i + 1 < len(changes) else end
            total += max(0, min(time, stop) - at) * bpm / 60
            if stop >= time:
                break
        return round(total * ppq)
    events = [(0, b'\xff\x03' + vlq(9) + b'Tempo Map')]
    for at, bpm in changes:
        micros = max(1, min(0xffffff, round(60_000_000 / bpm)))
        events.append((tick(at), b'\xff\x51\x03' + micros.to_bytes(3, 'big')))
    for at, stop, r in segments:
        if not r:
            events.append((tick(at), bytes([0xff, 0x58, 4, 4, 2, 24, 8])))
            continue
        bar = 60 / r["bpm"] * 4 / r["denominator"] * r["numerator"]
        first_bar = r["phase"] + math.ceil((at - r["phase"]) / bar - 1e-9) * bar
        meter_time = first_bar if first_bar < stop else at
        events.append((tick(meter_time), bytes([0xff, 0x58, 4, r["numerator"], int(math.log2(r["denominator"])), 96 // r['denominator'], 8])))
    for r in regions:
        if r['end'] <= start or r['start'] >= end:
            continue
        label = f"Clock scope {r['start']-start:.9f}..{r['end']-start:.9f}s; downbeat origin {r['phase']-start:.9f}s".encode()
        events.append((tick(max(start, r["start"])), b'\xff\x06' + vlq(len(label)) + label))
    events.sort(key=lambda e: e[0])
    data, previous = bytearray(), 0
    for at, message in events:
        data.extend(vlq(at - previous) + message)
        previous = at
    data.extend(vlq(max(0, tick(end) - previous)) + b'\xff\x2f\x00')
    Path(path).write_bytes(b'MThd' + struct.pack('>IHHH', 6, 0, 1, ppq) + b'MTrk' + struct.pack('>I', len(data)) + data)


def write_project_midi(path, project, start, end):
    # Project events share the same quarter clock as playback. Source-relative
    # predictions remain separate and do not become MIDI ground truth.
    ppq = 960
    tempos, signatures, seconds_at, quarter_at = musical_map(project)
    origin, stop = quarter_at(start), quarter_at(end)
    def tick(quarter):
        return max(0, round((quarter - origin) * ppq))
    events = [(0, b'\xff\x03' + vlq(9) + b'Tempo Map')]
    active_tempo = next(t for t in reversed(tempos) if t['quarter'] <= origin + 1e-8)
    active_signature = next(s for s in reversed(signatures) if s['quarter'] <= origin + 1e-8)
    for tempo in [active_tempo, *[t for t in tempos if origin + 1e-8 < t['quarter'] < stop]]:
        micros = max(1, min(0xffffff, round(60_000_000 / tempo['bpm'])))
        events.append((tick(tempo['quarter']), b'\xff\x51\x03' + micros.to_bytes(3, 'big')))
    for signature in [active_signature, *[s for s in signatures if origin + 1e-8 < s['quarter'] < stop]]:
        events.append((tick(signature['quarter']), bytes([0xff, 0x58, 4, signature['numerator'], int(math.log2(signature['denominator'])), 96 // signature['denominator'], 8])))
    for signature in signatures:
        if signature['quarter'] >= stop:
            continue
        if signature['quarter'] >= origin - 1e-8 or signature['id'] == active_signature['id']:
            label = f"Project bar {signature['bar']} at {seconds_at(signature['quarter']) - start:.9f}s; export origin at project quarter {origin:.9f}".encode()
            events.append((tick(signature['quarter']), b'\xff\x06' + vlq(len(label)) + label))
    events.sort(key=lambda event: event[0])
    data, previous = bytearray(), 0
    for at, message in events:
        data.extend(vlq(at - previous) + message)
        previous = at
    data.extend(vlq(max(0, tick(stop) - previous)) + b'\xff\x2f\x00')
    Path(path).write_bytes(b'MThd' + struct.pack('>IHHH', 6, 0, 1, ppq) + b'MTrk' + struct.pack('>I', len(data)) + data)


def export(job):
    project, options = job["project"], job["options"]
    start, end = options["start"], options["end"]
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("Export needs a non-empty time range")
    if not (options.get('mix') or (options.get('stems') and project['tracks']) or options.get('click') or options.get('maps')):
        raise ValueError("Choose at least one export output")
    folder = Path(job["output"])
    folder.mkdir(parents=True, exist_ok=False)
    rate = project["sampleRate"]
    frames = round((end - start) * rate)
    assets = {}
    for asset in project["assets"]:
        assets[asset["id"]] = (asset, np.memmap(asset.get('playbackPath', asset["pcmPath"]), dtype="<f4", mode="r", shape=(asset.get('playbackFrames', asset["frames"]), asset["channels"])))
    regions = geometry(project, max(end, project.get('projectDuration', end)))
    outputs = []
    if options["mix"]: outputs.append(('Mixdown', None, False))
    if options["stems"]:
        outputs.extend((f"{i+1:02d} {re.sub(r'[^\w .-]', '_', t['name'])}", t['id'], False) for i, t in enumerate(project["tracks"]))
    if options["click"]: outputs.append(('Click', None, True))
    files = []
    for index, (name, track, is_click) in enumerate(outputs):
        path = folder / (name + '.wav')
        with sf.SoundFile(str(path) + '.partial', mode='w', samplerate=rate, channels=2, format='WAV', subtype='PCM_24') as destination:
            for first in range(0, frames, 8192):
                count = min(8192, frames - first)
                times = start + np.arange(first, first + count, dtype=np.float64) / rate
                block = click_block(regions, times) * project["masterGain"] * project.get("clickGain", DEFAULT_CLICK_GAIN) if is_click else mix_block(project, assets, times, track)
                destination.write(block)
                if first % (8192 * 24) == 0:
                    emit(f"Rendering {name}", progress=(index + first / max(frames, 1)) / max(len(outputs), 1))
        Path(str(path) + '.partial').rename(path)
        files.append(str(path))
    if options["maps"]:
        map_path = folder / 'Tempo Map.json'
        document = {"schemaVersion": 2 if project.get('version') == 2 else 1,
                    "originProjectSeconds": start, "durationSeconds": end - start,
                    "clockRegions": [r for r in regions if r["end"] > start and r["start"] < end],
                    "analyses": project["analyses"], "audioWasTimeStretched": False}
        if project.get('version') == 2:
            tempos, signatures, seconds_at, quarter_at = musical_map(project)
            declared_signatures = {s['id'] for s in project['signatures']}
            document.update({'projectBpm': project.get('bpm', tempos[0]['bpm']),
                             'projectSignature': project.get('signature', {'numerator': signatures[0]['numerator'], 'denominator': signatures[0]['denominator']}),
                             'projectTempoEvents': [{**t, 'projectSeconds': seconds_at(t['quarter'])} for t in sorted(project['tempos'], key=lambda t: t['quarter'])],
                             'projectSignatureEvents': [{**s, 'projectSeconds': seconds_at(s['quarter'])} for s in signatures if s['id'] in declared_signatures],
                             'originProjectQuarter': quarter_at(start), 'savedAnalysisScopes': project['clocks'],
                             'analysisClockRegions': analysis_geometry(project),
                             'tempoEventPersistence': 'until-next-event' if project.get('timingPolicy') == 'persistent' else 'legacy'})
            write_project_midi(folder / 'Tempo Map.mid', project, start, end)
        else:
            write_midi(folder / 'Tempo Map.mid', regions, start, end)
        write_json(map_path, document)
        files += [str(map_path), str(folder / 'Tempo Map.mid')]
    return {"folder": str(folder), "files": files, "sampleRate": rate, "frames": frames}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding="utf-8"))
    try:
        result = {'decode': decode, 'analyze': analyze, 'export': export}[job['kind']](job)
        emit('complete', result=result)
    except Exception as exc:
        error = ('Not enough available memory for this audio job. Close other memory-heavy applications and retry.'
                 if isinstance(exc, MemoryError) else f'{type(exc).__name__}: {exc}')
        emit('failed', error=error)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
