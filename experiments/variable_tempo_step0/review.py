"""Scoped execution contracts; musical correctness is reported separately."""

import argparse
from pathlib import Path
import shutil

import numpy as np

from .common import PACKAGE, ROOT, digest, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    run = parser.parse_args().run.resolve()
    checks = []
    def check(name, value):
        checks.append({"name": name, "passed": bool(value)})
    sources = read_json(run / "source-inputs.json")["samples"]
    check("source_denominator_36", len(sources) == 36)
    check("source_fields_only", all(set(r) == {"id", "audio_path", "sample_rate", "sample_frames", "channels", "duration_seconds"} for r in sources))
    check("markers_and_click_audio_not_model_inputs", all("marker" not in r["audio_path"] and "with-click" not in r["audio_path"] for r in sources))
    original = read_json(run / "original/inference-receipt.json")
    check("36_original_predictions_complete", len(original["samples"]) == 36 and "all_families_prepared_at_utc" in original)
    check("original_source_reference_separation", not original["reference_files_read"] and not original["hint_files_read"])
    check("original_source_and_config_unchanged", all(digest(ROOT / "experiments/metronome_reconstruction_v1" / name) == digest(run / "original-source-snapshot" / name)
          for name in ("infer.py", "hinted.py", "grid.py", "config-tap-v2.json")))
    admission = read_json(run / "negative-control-admission.json")
    check("367_negative_groups_reserved_zero", admission["count"] == 367 and admission["reserved_consumed"] == 0)
    calibration = read_json(run / "support-v3/parameters.json")
    validation_ids = {r["id"] for r in admission["rows"] if r["role"] == "already_used_validation"}
    check("validation_not_in_support_calibration", not validation_ids.intersection(calibration["calibration_ids"]))
    proposal = read_json(run / "local-proposal-v2/source-receipt.json")
    check("local_source_worker_isolated", proposal["completed"] and not proposal["reference_files_read"])
    check("all_local_inputs_retained", len(proposal["rows"]) == 36)
    negative = read_json(run / "negative-controls-v6/results.json")
    check("negative_final_denominator", negative["gtzan_denominator"] == 367 and negative["reserved_consumed"] == 0)
    equal = True
    for row in read_json(run / "negative-controls/oracle-inputs.json")["rows"]:
        if not row["id"].startswith("gtzan_"):
            continue
        for clock in row["clocks"]:
            for span in (4, 8, 16):
                name = f"{clock['clock_id']}-span{span}.npz"
                with np.load(run / "negative-controls/predictions" / row["id"] / name) as old, np.load(run / "negative-controls-v6/predictions" / row["id"] / name) as new:
                    equal &= np.array_equal(old["support-v3_states"], new["support-v6_states"])
    check("feature_states_unchanged_without_waveform_masks", equal)
    check("preparation_controls_passed", read_json(run / "preparation-controls.json")["passed"])
    check("algorithm_isolation_controls_passed", read_json(run / "algorithm-controls.json")["passed"])
    coordinates = list((run / "corpus/inputs").glob("*/origin-verification.json"))
    check("30_constructed_coordinate_records", len(coordinates) == 30 and all(read_json(p)["marker_frame_error"] <= 1 and read_json(p)["music_ledger_frame_error"] <= 1 for p in coordinates))
    check("silent_clock_cases_unknown", all(r["constructed_expected_unknown"]["UNKNOWN"] == 1 for r in read_json(run / "support-v6/results.json")["rows"]
          if r.get("variant") == "silent_change" and r.get("span_quarters") == 8))
    check("no_automatic_variable_accuracy_claim", not read_json(run / "summary.json")["limits"]["automatic_variable_maps_produced"])
    snapshots = run / "final-step0-source-snapshot"
    snapshots.mkdir(exist_ok=False)
    manifest = {}
    for path in sorted(PACKAGE.glob("*")):
        if path.is_file() and path.suffix in (".py", ".json", ".md"):
            shutil.copyfile(path, snapshots / path.name)
            manifest[path.name] = digest(path)
    write_json(snapshots / "manifest.json", manifest)
    write_json(run / "execution-review.json", {"checks": checks, "passed": all(c["passed"] for c in checks),
               "execution_contract_only": True, "not_musical_accuracy_or_daw_runtime_validation": True})
    print({"checks": len(checks), "passed": all(c["passed"] for c in checks)})
    if not all(c["passed"] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
