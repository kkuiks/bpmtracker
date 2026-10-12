"""Source/evaluation contracts and a fixed song-level split."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PRIOR=ROOT/'data/research/runs/variable_clock_composition_v1/20261010T185525Z-v1'
DEVELOPMENT=['r000','r001','r002','r004','r006','r007','r011','r013','r015','r017','r019']
VALIDATION=['r003','r005','r008','r009','r010','r012','r014','r016','r018','r020']
FOLDS=[['r000','r004','r013','r015'],['r001','r006','r011','r017'],['r002','r007','r019']]
FACTORS=[.25,1/3,.5,2/3,.75,1.,4/3,1.5,2.,3.,4.]
CONFIG={'sample_rate':16000,'hop_samples':160,'nfft':1024,
        'frequency_bands':[[30,150],[150,500],[500,2000],[2000,8000]],
        'window_seconds':16.,'hop_seconds':4.,'bars_quarters':[2,3,4,5,6,7,8],
        'profile_bins':32,'profile_harmonics':8,
        'autocorrelation_lags_quarters':[.25,.5,1.,1.5,2.,3.,4.,5.,6.,7.,8.],
        'source_quality_min':.35,'minimum_neural_events':5,
        'anchor_deadline_seconds':30.,'anchor_quality_min':.65,
        'anchor_stability_fraction':.03,'tap_error_fraction':.03,
        'unit_family_relative_tolerance':.05,'train_window_purity_min':.85,
        'regularizers':[.01,.1,1.],'optimizer_iterations':150,
        'bootstrap_seed':11102026,'bootstrap_repetitions':5000}
LEARNED={
 'N1_NEURAL_ANCHOR':{'neural':True,'audio':False,'anchor':True},
 'A1_AUDIO':{'neural':False,'audio':True,'anchor':False},
 'A2_AUDIO_ANCHOR':{'neural':False,'audio':True,'anchor':True},
 'A3_AUDIO_NEURAL':{'neural':True,'audio':True,'anchor':False},
 'A4_AUDIO_NEURAL_ANCHOR':{'neural':True,'audio':True,'anchor':True},
}
HEURISTIC=['N0_NATIVE','N2_INITIAL_RELATION','P0_PATTERN_NEAREST']
CRITERIA={'primary':'A4_AUDIO_NEURAL_ANCHOR','baseline':'N1_NEURAL_ANCHOR',
          'confirmatory_audio_methods':['A4_AUDIO_NEURAL_ANCHOR','A2_AUDIO_ANCHOR'],
          'validation_variable_accuracy_min':.80,'validation_variable_gain_min':.05,
          'relative_unit_error_reduction_min':.25,'positive_songs_required':3,
          'positive_song_gain_min':.01,'nonregressed_songs_required':4,
          'song_max_regression':.01,'bootstrap_gain_lower_min':0.,
          'control_accuracy_max_decline':.03,'true_double_post_accuracy_min':.80,
          'true_double_post_min_gain_vs_baseline':0.,
          'sensor_level_pair_max_decline':.03,
          'unit_discriminator_gate_not_full_map_acceptance':True}

def read(path):return json.loads(Path(path).read_text())
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);part=path.with_suffix(path.suffix+'.partial')
    part.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n');part.replace(path)
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def stamp():return datetime.now(timezone.utc).isoformat()
def code_hashes():
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
def guard(run):
    f=read(Path(run)/'freeze.json')
    if f['code_hashes']!=code_hashes() or f['config']!=CONFIG or f['criteria']!=CRITERIA or f['learned']!=LEARNED:
        raise RuntimeError('Frozen source or settings changed')
def unit_index(value,base):return int(np_argmin_log(value/base))
def np_argmin_log(ratio):
    import numpy as np
    return np.argmin(abs(np.log(ratio/np.asarray(FACTORS))))
