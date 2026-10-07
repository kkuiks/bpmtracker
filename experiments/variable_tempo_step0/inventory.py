"""Inventory existing reference capabilities before new variable predictions."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from .common import SAMPLES, read_json, reference_segments, write_json

PRIMARY = {"state_shirt_hospital_hill", "andrew-wade-a-day-to-remember", "jens-bogren-opeth"}


def build():
    catalog = read_json(SAMPLES / "catalog.json")
    fixed = {r["id"]: r for r in read_json(SAMPLES / "selections/fixed-metronome-v1/all-valid-selection.json")["rows"]}
    rows = []
    for sample in catalog["tracks"]:
        ident = sample["id"]
        meta = fixed[ident]
        ref = read_json(SAMPLES / sample["reference"]["path"])
        bpms = meta["reference_quarter_bpm_values_exact_as_stored"]
        meters = meta["reference_meter_values"]
        variable = len(bpms) > 1
        changes_meter = len(meters) > 1
        classification = ("E_fixed_negative_control" if not variable and not changes_meter
                          else "B_tempo_and_meter_changes" if variable and changes_meter
                          else "A_fixed_meter_discrete_tempo" if variable else "B_meter_changes_only")
        if "explicitly_approved_free_time_or_no_grid_tail" in meta["reasons"] and not variable:
            classification = "C_fixed_clock_plus_free_tail"
        support = sample["reference_support_seconds"]
        segments = reference_segments(ref, support) if variable else []
        capabilities = ["candidate_rate_recovery"] if variable else ["fixed_negative_control"]
        disposition = "not_selected_initial_scope"
        if ident in PRIMARY:
            capabilities += ["oracle_quarter_clock_support", "practical_owner_map_boundary_agreement"]
            disposition = "primary_real_diagnostic"
        elif ident == "legacy_circle":
            disposition = "secondary_rate_only_4_2"
        notes = ["Accepted reference coordinates already contain the owner offset; additional offset is zero.",
                 "Owner alignment is practical evidence, not independent millisecond certification."]
        if ident == "legacy_circle":
            notes.append("Reference is 4/2, quarter BPM about 205/210; rendered clicks are half notes. No 4/4 reinterpretation.")
        if ident == "state_shirt_hospital_hill":
            notes.append("Producer text says 4/4 and approximately 102 / 109.9 BPM. Pre-first-explicit-meter bar phase is projected backward.")
        if ident == "jens-bogren-opeth":
            notes.append("Final owner acceptance governs practical use; older target_evaluation_eligible=false does not certify precise origin.")
        if ident == "andrew-wade-a-day-to-remember":
            notes.append("Tempo comes from supplied MIDI; explicit 4/4 comes from Studio One. The 145 BPM segment lasts about 1.655 seconds.")
        rows.append({"id": ident, "title": sample["title"], "data_origin": sample["role"],
                     "classification": classification, "reference_tier": "owner_reviewed_synthetic_reference"
                     if "synthetic" in sample["role"] else "tier2_owner_reviewed_real_map",
                     "audio_path": sample["audio"]["path"], "reference_path": sample["reference"]["path"],
                     "duration_seconds": sample["duration_seconds"], "support_seconds": support,
                     "quarter_bpm_values": bpms, "meters": meters, "segments": segments,
                     "audio_origin": "existing_owner_reviewed_alignment", "absolute_precision_certified": False,
                     "reference_kind": meta.get("reference_kind"), "capabilities": capabilities,
                     "step0_disposition": disposition, "scope_reasons": meta["reasons"], "notes": notes,
                     "original_clock_paths": [item["path"] for item in sample.get("original_clocks", [])]})
    baby_path = SAMPLES / "experiments/metronome_benchmark_v1/20261007-babyslakh-baseline-v1/qualification.json"
    baby = read_json(baby_path)["rows"]
    for source in baby:
        if source["eligible"]:
            continue
        clock = source["source_clock"]
        variable = len(clock["tempos"]) > 1
        reasons = list(source["reasons"])
        first_note = clock["first_note_seconds"]
        before_music = variable and first_note is not None and clock["tempos"][1]["source_seconds"] < first_note
        if before_music:
            reasons.append("initial_tempo_change_precedes_first_source_note")
        admitted = source["id"] == "Track00008"
        rows.append({"id": "babyslakh_" + source["id"], "title": source["id"],
                     "data_origin": "synthetic_midi_render", "reference_tier": "tier3_authored_clock_unresolved_audio_origin",
                     "classification": "D_source_clock_conflict" if "rendered_source_clock_disagreement" in reasons
                     else "B_tempo_and_meter_changes" if variable and len(clock["signatures"]) > 1
                     else "C_unobserved_initial_change" if before_music
                     else "A_fixed_meter_discrete_tempo" if variable else "B_meter_changes_only",
                     "duration_seconds": source["duration_seconds"], "tempo_events": clock["tempos"],
                     "meter_events": clock["signatures"], "audio_path": source["audio_path"],
                     "reference_record": str(baby_path.relative_to(SAMPLES)),
                     "audio_origin": "unresolved", "absolute_precision_certified": False,
                     "capabilities": ["encoded_candidate_rate_sequence"] if admitted else [],
                     "step0_disposition": "secondary_encoded_rate_only" if admitted else "not_selected_initial_scope",
                     "scope_reasons": reasons, "source_clock": clock,
                     "notes": ["This is synthetic development material, not a real recording.",
                               "Existing qualification evidence is retained; no audio-origin assumption is promoted."]})
    assets = read_json(SAMPLES / "assets.json")
    external = read_json(SAMPLES / "external-assets.json")
    return {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "inventory_precedes_new_variable_inference": True, "catalog_membership_unchanged": True,
            "survey": {"catalog_rows": len(catalog["tracks"]), "indexed_asset_records": len(assets["assets"]),
                       "external_indexed_paths": len(external["files"]),
                       "external_clocks_are_provenance_for_cataloged_sources": True,
                       "excluded_candidates": read_json(SAMPLES / "excluded-candidates.json")["candidates"],
                       "unenrolled_creator_sections": "Retained but not admitted; enrollment/qualification rules are preserved.",
                       "fixed_feature_controls": {"development_groups": 280, "already_used_validation_groups": 87,
                                                  "reserved_groups_consumed": 0},
                       "constructed_fixed_controls": "Existing 58-input defined-clock corpus is separate; new step controls will have new IDs."},
            "classification_counts": dict(Counter(row["classification"] for row in rows)), "rows": rows}


def markdown(data):
    lines = ["# Variable-reference inventory", "", "Existing source records, prior owner decisions and capability limits precede prediction.",
             "No reference is shifted, converted to 4/4 or promoted to independent millisecond truth.", "",
             "| ID | Origin/tier | Classification | Step 0 use | Rates / limitation |", "| --- | --- | --- | --- | --- |"]
    for row in data["rows"]:
        if row["step0_disposition"] == "not_selected_initial_scope" and row["classification"] == "E_fixed_negative_control":
            continue
        rates = ", ".join(f"{bpm:.6g}" for bpm in row.get("quarter_bpm_values", []))
        reasons = "; ".join(row.get("scope_reasons", []))
        lines.append(f"| {row['id']} | {row['reference_tier']} | {row['classification']} | {row['step0_disposition']} | {rates or reasons} |")
    lines += ["", "Primary real diagnostics: Hospital Hill, Right Back At It Again, Heir Apparent.",
              "Circle With Me is a rate-only secondary case because its accepted meter is 4/2.",
              "BabySlakh Track00008 is an encoded-rate secondary case with unresolved audio origin.",
              "All other surveyed rows and rejection reasons remain in the JSON denominator."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    data = build()
    write_json(args.output / "reference-inventory.json", data)
    (args.output / "reference-inventory.md").write_text(markdown(data), encoding="utf-8")
    print(json.dumps({"inventory_rows": len(data["rows"]), "classification_counts": data["classification_counts"]}))


if __name__ == "__main__":
    main()
