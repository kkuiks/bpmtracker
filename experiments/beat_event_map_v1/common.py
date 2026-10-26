from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os

CODE_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('BPMTRACKER_WORKSPACE_ROOT',str(CODE_ROOT)))
PARENT = ROOT / 'data/research/runs/continuous_beat_map_v1/20261011T154900Z-v3'
POLICIES = ['proxy97', 'proxy100', 'proxy103']
CONFIG = {
    'signatures': [[2,4],[3,4],[4,2],[4,4],[5,4],[6,4],[6,8],[7,4]],
    'bpm_domain': [30,400], 'rational_denominator': 4,
    'source_peak_floor': .20, 'source_run_sigma_seconds': .035,
    'source_run_bad_mass': 1.5, 'source_run_budget': 48,
    'source_minimum_fit_observations': 3, 'source_clock_budget': 512,
    'initial_information_mass': 4., 'initial_fit_quality': .8,
    'pulse_factors': [.5,1.,2.,2/3,4/3,1/3,1.5,.75],
    'initial_role_radius_log': .12, 'initial_candidate_budget': 96,
    'initial_role_merge_log': .08, 'initial_family_path_reserve': 2,
    'initial_path_budget': 8, 'map_path_budget': 4,
    'pending_path_budget': 2, 'evidence_candidate_reserve': 16,
    'extension_candidates': 48, 'max_declarations': 24,
    'maximum_stagnant_search_depths': 3,
    'proposal_phase_tolerance_seconds': .08,
    'neural_sigma_seconds': .025, 'pcm_sigma_seconds': .035,
    'beat_weight': .62, 'bar_weight': .28, 'pcm_weight': .10,
    'observation_role_cost': .018, 'offbeat_role_cost': .025,
    'tempo_change_cost': 1.2, 'meter_change_cost': 1.0,
    'octave_change_extra_cost': 3., 'octave_ratio_tolerance': .03,
    'gate_old_ceiling': .55, 'gate_new_floor': .65,
    'gate_improvement': .12, 'gate_minimum_source_mass': 2.,
    'meter_prior': {'4/4':0.,'3/4':.006,'6/8':.008,'2/4':.024,
                    '4/2':.04,'5/4':.016,'6/4':.026,'7/4':.018},
    'family_initial_prior': .04,
    'evidence_clutter_probability': .05,
}
METHODS = {
    'E0_EVENT_SEARCH': {'gate':False,'role_mixture':False},
    'E1_MISMATCH_GATE': {'gate':True,'role_mixture':False},
    'E2_RHYTHM_ROLES': {'gate':True,'role_mixture':True},
    'E3_SAME_UNIT_GATE': {'gate':True,'role_mixture':True,'unit_hold':True},
}
PILOT_IDS = ['e007','r020','e002','r003','r002','r008','r009','r005']

def read(path):return json.loads(Path(path).read_text())
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def stamp():return datetime.now(timezone.utc).isoformat()
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def code_hashes():
    paths=list(Path(__file__).parent.glob('*.py'))
    paths += [CODE_ROOT/'experiments/continuous_beat_map_v1'/name for name in ['map.py','score_audio.py','common.py','evaluate.py','native.py']]
    return {str(p.relative_to(CODE_ROOT)):digest(p) for p in sorted(paths)}
def guard(run):
    frozen=read(Path(run)/'freeze.json')
    if frozen['code_hashes']!=code_hashes() or frozen['config']!=CONFIG or frozen['methods']!=METHODS:
        raise RuntimeError('Frozen beat-event experiment changed')
