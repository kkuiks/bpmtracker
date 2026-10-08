"""Prepare a listening manifest from frozen experiment results, without inference."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from tools.project_storage import resolve_path

from .evaluate import reference_events


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def build(run, samples_root, output, condition="tap_only", count=5):
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    manifest = json.loads((run / "evaluation-manifest.json").read_text(encoding="utf-8"))
    metadata = {row["id"]: row for row in manifest["samples"]}
    rows = results["samples"]
    # Do not drop a failure or silently change the selection denominator.
    if any(not row["conditions"][condition].get("metrics") for row in rows):
        raise ValueError("This ranking requires recorded timing metrics for every sample")
    if not 1 <= count <= len(rows):
        raise ValueError("count must be between one and the full result denominator")

    def maximum_error(row):
        metrics = row["conditions"][condition]["metrics"]
        return max(metrics["paired_quarter_clock"]["max_absolute_error_ms"],
                   metrics["paired_bar_clock"]["max_absolute_error_ms"])

    ranked = sorted(rows, key=maximum_error, reverse=True)[:count]
    tracks, assets = [], {}
    for rank, row in enumerate(ranked, 1):
        ident, meta = row["id"], metadata[row["id"]]
        map_path = run / condition / "tempo-maps" / (ident + ".json")
        proposal = json.loads(map_path.read_text(encoding="utf-8"))
        ref = json.loads(resolve_path(samples_root / meta["reference"]["path"]).read_text(encoding="utf-8"))
        beat_ref, down_ref = reference_events(ref, meta["reference_support_seconds"])
        metrics = row["conditions"][condition]["metrics"]
        audio_url, map_url = f"audio/{ident}.wav", f"maps/{ident}.json"
        assets[audio_url] = str(resolve_path(samples_root / meta["audio"]["path"]).absolute())
        assets[map_url] = str(map_path.absolute())
        tracks.append({
            "id": ident, "rank": rank, "title": row["title"],
            "audio_url": audio_url, "map_url": map_url,
            "audio_bytes": meta["audio"]["bytes"],
            "duration_seconds": meta["duration_seconds"],
            "quarter_bpm": proposal["quarter_bpm"], "time_signature": proposal["time_signature"],
            "offset_seconds": proposal["offset_seconds"], "status": proposal["status"],
            "confidence_flags": proposal.get("confidence_flags", []),
            "ranking_error_ms": maximum_error(row),
            "quarter_max_error_ms": metrics["paired_quarter_clock"]["max_absolute_error_ms"],
            "bar_max_error_ms": metrics["paired_bar_clock"]["max_absolute_error_ms"],
            "quarter_initial_error_ms": metrics["paired_quarter_clock"]["initial_phase_error_ms"],
            "bar_initial_error_ms": metrics["paired_bar_clock"]["initial_phase_error_ms"],
            "reference_support_seconds": meta["reference_support_seconds"],
            "predicted": {"quarter": proposal["quarter_clicks_seconds"], "downbeat": proposal["downbeats_seconds"]},
            "reference": {"quarter": beat_ref.tolist(), "downbeat": down_ref.tolist()},
        })
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "index-data.json", {
        "schema_version": 1, "run": run.name, "condition": condition,
        "source_result_completed_at_utc": results["completed_at_utc"],
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "full_result_denominator": len(rows), "count": count,
        "selection_metric": "max(paired_quarter_clock.max_absolute_error_ms, paired_bar_clock.max_absolute_error_ms), descending",
        "reference_derived_hint_is_diagnostic_only": results.get("reference_derived_hint_is_diagnostic_only", False),
        "prediction_events_copied_from_saved_maps": True,
        "reference_events_are_existing_audio_relative_events": True,
        "additional_reference_offset_seconds": 0,
        "independent_original_click_millisecond_accuracy_certified": False,
        "tracks": tracks,
    })
    # Filesystem locations are for the server only; this file is not a served asset.
    write_json(output / "assets.json", {"schema_version": 1, "assets": assets})
    print(json.dumps({"output": str(output), "condition": condition,
                      "ranking": [{"id": t["id"], "title": t["title"], "max_error_ms": t["ranking_error_ms"]} for t in tracks]}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, default=Path("data/samples"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--condition", default="tap_only")
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()
    run = args.run.absolute()
    build(run, args.samples_root.absolute(), args.output or run / "listening-bottom5", args.condition, args.count)


if __name__ == "__main__":
    main()
