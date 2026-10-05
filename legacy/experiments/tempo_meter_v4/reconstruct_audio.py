"""One finished mix -> document-route map, without a catalog or references."""
import argparse
import json
from pathlib import Path
import resource
import sys
import time
import numpy as np
import soundfile as sf
from experiments.tempo_meter_v3.features import Extractor
from experiments.tempo_meter_v3.probe_resources import digest
from .observations import prepare
from .analyzer import analyze


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--initial-bpm',type=float)
    parser.add_argument('--acoustic-checkpoint',type=Path,required=True)
    parser.add_argument('--parameters',type=Path,required=True)
    parser.add_argument('--cache-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--device',default='cuda')
    parser.add_argument('--repetition',choices=['none','automatic'],default='none')
    parser.add_argument('--beam',type=int,default=32)
    args=parser.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    args.output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();info=sf.info(args.audio)
    source=dict(sha256=digest(args.audio),sample_rate=info.samplerate,sample_frames=info.frames)
    feature_path=args.cache_root/(source['sha256']+'.npz');cache_hit=feature_path.exists()
    parameters=json.loads(args.parameters.read_text())
    if not parameters['validation_pass']:raise ValueError('unvalidated parameters')
    if parameters['selected'].get('downbeat_capacity',False):
        from .capacity_emissions import install
        install()
    extractor=Extractor(args.acoustic_checkpoint,args.device)
    receipt=extractor.extract(args.audio,feature_path)
    feature_seconds=time.perf_counter()-started
    with np.load(feature_path) as values:
        obs=prepare(values['logits'],values['energy'],features=values['features'].copy())
    del extractor
    tick=time.perf_counter()
    prediction,alternatives=analyze(obs,source,args.initial_bpm,parameters=parameters['selected'],repetition=args.repetition,beam=args.beam)
    selected=args.output/'selected.json'
    selected.write_text(json.dumps(prediction,indent=2,allow_nan=False)+'\n')
    (args.output/'alternatives.json').write_text(json.dumps(alternatives,indent=2,allow_nan=False)+'\n')
    record=dict(source=source,audio=str(args.audio.resolve()),initial_bpm=args.initial_bpm,
        feature_binding=receipt['binding'],acoustic_cache_hit=cache_hit,
        feature_seconds=feature_seconds,decoder_seconds=time.perf_counter()-tick,total_seconds=time.perf_counter()-started,
        runtime_scope='warm acoustic cache' if cache_hit else 'cold observations and decoder',
        max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        selected=dict(path=str(selected.resolve()),sha256=digest(selected)),
        parameters_sha256=digest(args.parameters),references_available_to_runner=False,
        song_id_rules=False,experimental_not_promoted=True,native_windows_validated=False)
    (args.output/'run.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
