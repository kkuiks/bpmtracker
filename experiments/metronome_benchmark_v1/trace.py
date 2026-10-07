"""Record every tested clock without changing the frozen estimator's functions.

Tracing wraps the existing call sites for one source input and restores them
afterwards. Reference clocks and numeric unit hints are absent from this module.
"""

from __future__ import annotations

from collections import Counter
import ast
from functools import lru_cache
import gzip
import json
from pathlib import Path
import sys

from .inference import write_json


def candidate_key(row):
    fraction = row["bpm_fraction"]
    return (fraction["numerator"], fraction["denominator"],
            row["time_signature"]["numerator"], float(row["offset_seconds"]).hex())


@lru_cache(maxsize=8)
def score_call_sites(filename):
    """Classify source calls even when Python 3.12 inlines comprehensions."""
    mapping, ancestors = {}, []
    class Visitor(ast.NodeVisitor):
        def visit(self, node):
            ancestors.append(node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'score_candidate':
                owner = next(item.name for item in reversed(ancestors) if isinstance(item, ast.FunctionDef))
                refinement = any(isinstance(item, ast.ListComp) for item in ancestors)
                stage = ('octave_refinement' if owner == 'octave_leader' else 'refinement') if refinement else (
                    'octave_coarse' if owner == 'octave_leader' else 'coarse')
                for line in range(node.lineno, node.end_lineno + 1):
                    mapping[line] = (owner, stage)
            super().visit(node)
            ancestors.pop()
    Visitor().visit(ast.parse(Path(filename).read_text()))
    return mapping


class CandidateTrace:
    def __init__(self, directory: Path, ident: str):
        self.directory, self.ident = directory, ident
        self.directory.mkdir(parents=True, exist_ok=True)
        self.scores_path = directory / f"{ident}.scores.jsonl.gz"
        self.events_path = directory / f"{ident}.events.jsonl.gz"
        if self.scores_path.exists() or self.events_path.exists():
            raise ValueError("A trace must use a new output")
        self.count = 0
        self.block = None
        self.layers = 0
        self.blocks = []
        self.counts = Counter()
        self.by_object = {}
        self.by_key = {}
        self.refinement_seeds = set()
        self.summary = {"schema_version": 1, "id": ident,
                        "reference_fields_used": False, "numeric_hints_used": False,
                        "clock_records": self.scores_path.name,
                        "search_events": self.events_path.name}

    def event(self, kind, **data):
        self.events.write(json.dumps({"event": kind, "block": self.block, **data}, allow_nan=False) + "\n")

    def __enter__(self):
        from experiments.metronome_reconstruction_v1 import infer, hinted
        self.infer, self.hinted = infer, hinted
        self.saved = [(infer, "score_candidate", infer.score_candidate),
                      (hinted, "score_candidate", hinted.score_candidate),
                      (infer, "optimize", infer.optimize),
                      (hinted, "optimize", hinted.optimize),
                      (infer, "phase_seeds", infer.phase_seeds),
                      (hinted, "phase_seeds", hinted.phase_seeds),
                      (infer, "broad_candidates", infer.broad_candidates),
                      (hinted, "_fit_layer", hinted._fit_layer)]
        self.score_fn, self.optimize_fn = infer.score_candidate, infer.optimize
        self.phase_fn, self.broad_fn = infer.phase_seeds, infer.broad_candidates
        self.layer_fn = hinted._fit_layer
        self.scores = gzip.open(self.scores_path, "wt", encoding="utf-8", compresslevel=3)
        self.events = gzip.open(self.events_path, "wt", encoding="utf-8", compresslevel=3)
        infer.score_candidate = hinted.score_candidate = self.score
        infer.optimize = hinted.optimize = self.optimize
        infer.phase_seeds = hinted.phase_seeds = self.phase
        infer.broad_candidates = self.broad
        hinted._fit_layer = self.layer
        self.event("trace_started")
        return self

    def score(self, *args, **kwargs):
        frame = sys._getframe(1)
        name = frame.f_code.co_name
        parent = frame.f_back if name == "<listcomp>" else frame
        owner, stage = score_call_sites(frame.f_code.co_filename).get(frame.f_lineno, (parent.f_code.co_name, 'unclassified'))
        seed = parent.f_locals.get("leader" if owner == "octave_leader" else "row") if 'refinement' in stage else None
        seed_id = self.by_object.get((self.block, id(seed))) if isinstance(seed, dict) else None
        site = {"function": owner, "line": frame.f_lineno, "file": Path(frame.f_code.co_filename).name}
        del frame, parent
        row = self.score_fn(*args, **kwargs)
        self.count += 1
        self.counts[(self.block, stage)] += 1
        if seed_id is not None and (self.block, seed_id) not in self.refinement_seeds:
            self.refinement_seeds.add((self.block, seed_id))
            self.event("refinement_seed", score_id=seed_id)
        self.scores.write(json.dumps({"score_id": self.count, "block": self.block,
            "stage": stage, "parent_score_id": seed_id, "site": site, "candidate": row}, allow_nan=False) + "\n")
        self.by_object[(self.block, id(row))] = self.count
        self.by_key[(self.block, candidate_key(row))] = self.count
        return row

    def phase(self, *args, **kwargs):
        value = self.phase_fn(*args, **kwargs)
        period = args[1] if len(args) > 1 else kwargs["period"]
        self.event("phase_seeds", period_seconds=float(period), seeds_seconds=value)
        return value

    def broad(self, *args, **kwargs):
        bpms, search = self.broad_fn(*args, **kwargs)
        self.event("broad_bpm_candidates", bpm_fractions=[
            {"numerator": x.numerator, "denominator": x.denominator} for x in bpms], search=search)
        return bpms, search

    def block_exit(self, result):
        best = result.get("best", result)
        retained = result.get("top_candidates", [])
        self.event("block_finished", best_score_id=self.by_key.get((self.block, candidate_key(best))),
                   best=best, retained_score_ids=[self.by_key.get((self.block, candidate_key(row))) for row in retained])
        self.blocks.append({"id": self.block,
            "scores": sum(value for (block, _), value in self.counts.items() if block == self.block),
            "best": {key: best[key] for key in ["quarter_bpm", "bpm_fraction", "period_seconds", "time_signature", "offset_seconds", "score"]},
            "retained_count": len(retained)})

    def optimize(self, *args, **kwargs):
        previous, self.block = self.block, "base_search"
        self.event("block_started")
        try:
            result = self.optimize_fn(*args, **kwargs)
            self.block_exit(result)
            return result
        finally:
            self.block = previous

    def layer(self, *args, **kwargs):
        previous, self.block = self.block, f"layer_{self.layers}"
        self.layers += 1
        bpms = args[1] if len(args) > 1 else kwargs["bpms"]
        self.event("block_started", bpm_fractions=[{"numerator": x.numerator, "denominator": x.denominator} for x in bpms])
        try:
            result = self.layer_fn(*args, **kwargs)
            self.block_exit(result)
            return result
        finally:
            self.block = previous

    def finish(self, family, prediction):
        self.summary.update({"family_status": family["status"],
            "audio_base_bpm": family.get("audio_base_bpm"),
            "layer_powers": {f"layer_{index}": level["power"] for index, level in enumerate(family.get("levels", []))},
            "prediction_status": prediction["status"], "selected_layer_power": prediction.get("selected_audio_layer_power")})
        self.event("audio_only_selection", prediction=prediction)

    def __exit__(self, typ, error, tb):
        for module, name, function in self.saved:
            setattr(module, name, function)
        try:
            self.event("trace_finished", score_count=self.count,
                       error=f"{typ.__name__}: {error}" if typ else None)
        finally:
            self.scores.close()
            self.events.close()
        self.summary.update({"score_count": self.count, "blocks": self.blocks,
            "stage_counts": {f"{block}:{stage}": value for (block, stage), value in self.counts.items()},
            "complete": typ is None, "error": f"{typ.__name__}: {error}" if typ else None,
            "score_bytes": self.scores_path.stat().st_size, "event_bytes": self.events_path.stat().st_size})
        write_json(self.directory / f"{self.ident}.json", self.summary)
        self.by_object.clear()
        self.by_key.clear()
        return False
