"""Cold single-audio entry for the explicitly locked coordinate route."""
import json
from pathlib import Path
import sys
from . import coordinate_analyzer,reconstruct_audio
from experiments.tempo_meter_v3.probe_resources import digest


def main():
    parameters=Path(sys.argv[sys.argv.index('--parameters')+1])
    lock=json.loads(parameters.read_text())
    if not lock['selected'].get('coordinate_refinement'):raise ValueError('coordinate route not selected')
    for name,sha in lock['additional_implementation_sha256'].items():
        if digest(Path(__file__).with_name(name))!=sha:raise ValueError('locked helper changed '+name)
    reconstruct_audio.analyze=coordinate_analyzer.install()
    reconstruct_audio.main()
    output=Path(sys.argv[sys.argv.index('--output')+1]);path=output/'run.json'
    record=json.loads(path.read_text())
    record['entrypoint_implementation_sha256']={name:digest(Path(__file__).with_name(name)) for name in ['reconstruct_coordinate_audio.py','reconstruct_audio.py','coordinate_analyzer.py']}
    record['learned_observations_used']=False
    path.write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':main()
