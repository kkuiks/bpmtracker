"""Inspect audio and explicit step-tempo references before model evaluation.

Uses Python's standard library plus ffmpeg/ffprobe. It audits reference
consistency; it does not establish that a reference is aligned to the audio.
"""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def positive(value, label):
    value = Decimal(str(value))
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return value


def read_tempo_reference(path, ticks_per_quarter):
    """Integrate step tempos with an explicit resolution and a zero origin.

    This is an audit of tempo events, not a general Cubase importer. In
    particular, ramp semantics and the audio/project origin are not inferred.
    """
    tpq = positive(ticks_per_quarter, "ticks per quarter")
    root = ET.parse(path).getroot()
    events = []
    elapsed = Decimal(0)
    previous_tick = None
    previous_bpm = None
    for node in root.findall(".//obj[@class='MTempoEvent']"):
        values = {child.get("name"): child.get("value") for child in node.findall("float")}
        tick = Decimal(values["PPQ"])
        bpm = positive(values["BPM"], "BPM")
        if not tick.is_finite() or tick < 0:
            raise ValueError("tempo positions must be finite and nonnegative")
        if previous_tick is None:
            if tick != 0:
                raise ValueError("a nonzero first tempo position needs an explicit origin policy")
        else:
            if tick <= previous_tick:
                raise ValueError("tempo positions must be strictly increasing")
            elapsed += (tick - previous_tick) * Decimal(60) / (tpq * previous_bpm)
        events.append({"tick": tick, "quarter_position": tick / tpq, "time_seconds": elapsed, "bpm": bpm})
        previous_tick, previous_bpm = tick, bpm
    if not events:
        raise ValueError("no tempo events found")
    signatures = []
    for node in root.findall(".//obj[@class='MTimeSignatureEvent']"):
        signatures.append({child.get("name"): child.get("value") for child in node})
    return {
        "ticks_per_quarter": str(tpq),
        "resolution_source": "explicit_command_line_argument",
        "integration_assumption": "step tempos; first tempo event at project time zero",
        "audio_origin_alignment": "unverified",
        "events": events,
        "signature_events_raw": signatures,
    }


def compare_reference_text(path, reference):
    rows = []
    declared_tpq = None
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("TPQ used"):
            declared_tpq = Decimal(line.split(":", 1)[1].strip())
        fields = line.split()
        if fields and fields[0].isdigit():
            if len(fields) != 4:
                raise ValueError("expected reference columns: index, tick, time, BPM")
            if int(fields[0]) != len(rows):
                raise ValueError("reference indices must be sequential from zero")
            rows.append(dict(zip(["tick", "time_seconds", "bpm"], map(Decimal, fields[1:]))))
    if declared_tpq != Decimal(reference["ticks_per_quarter"]):
        raise ValueError("reference header and explicit tick resolution disagree")
    if len(rows) != len(reference["events"]):
        raise ValueError("reference event counts disagree")
    differences = []
    consistent = True
    for row, event in zip(rows, reference["events"]):
        for key, displayed in row.items():
            if not displayed.is_finite():
                raise ValueError("reference values must be finite")
            tolerance = Decimal(5).scaleb(displayed.as_tuple().exponent - 1)
            consistent &= abs(event[key] - displayed) <= tolerance
        differences.append(abs(event["time_seconds"] - row["time_seconds"]))
    return {
        "within_display_rounding": consistent,
        "maximum_time_difference_seconds": str(max(differences)),
        "meaning": "internal consistency only; the text may derive from the same XML",
    }


def probe_audio(path):
    command = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,time_base,start_time,duration,duration_ts:format=duration,start_time",
        "-of", "json", str(path),
    ]
    result = json.loads(subprocess.check_output(command, text=True))
    if len(result.get("streams", [])) != 1:
        raise ValueError("expected an audio stream")
    return result


def decimal_json(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--smt", type=Path)
    parser.add_argument("--ticks-per-quarter", type=Decimal)
    parser.add_argument("--reference-text", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.smt and args.ticks_per_quarter is None:
        parser.error("--smt requires explicit --ticks-per-quarter; resolution is never guessed")
    if args.reference_text and not args.smt:
        parser.error("--reference-text requires --smt")
    if args.output_dir.exists():
        parser.error("--output-dir must be new; existing results are never overwritten")

    report = {
        "schema_version": 1,
        "purpose": "input and reference audit, not model inference or accuracy measurement",
        "source": {"filename": args.audio.name, "sha256": sha256(args.audio), "probe": probe_audio(args.audio)},
        "ffmpeg_version": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
    }
    if args.smt:
        report["reference"] = read_tempo_reference(args.smt, args.ticks_per_quarter)
        report["reference"]["source_sha256"] = sha256(args.smt)
        if args.reference_text:
            report["reference_text"] = compare_reference_text(args.reference_text, report["reference"])
            report["reference_text"]["sha256"] = sha256(args.reference_text)

    args.output_dir.mkdir(parents=True)
    decoded = args.output_dir / "audio.wav"
    command = ["ffmpeg", "-v", "error", "-nostdin", "-n", "-i", str(args.audio), "-map", "0:a:0", "-map_metadata", "-1", "-c:a", "pcm_f32le", str(decoded)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    probe = probe_audio(decoded)
    stream = probe["streams"][0]
    report["decoded"] = {
        "file": "audio.wav", "sha256": sha256(decoded), "probe": probe,
        "sample_frames": int(stream["duration_ts"]) if stream["time_base"] == "1/" + stream["sample_rate"] else None,
        "origin_policy": "first sample returned by this decoder is sample zero; no additional start_time subtraction",
        "reference_alignment": "unverified; codec timestamps are not a measured reference offset",
    }
    output = args.output_dir / "report.json"
    output.write_text(json.dumps(report, default=decimal_json, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(output)
    print(f"Decoded {stream['sample_rate']} Hz, {stream['channels']} channels, {report['decoded']['sample_frames']} frames")
    if "reference_text" in report:
        print("Reference matches displayed precision:", report["reference_text"]["within_display_rounding"])
    print("Audio/reference alignment remains unverified; no model was executed.")


if __name__ == "__main__":
    main()
