"""Separate coordinate-refinement route; frozen v4 entry points stay unchanged."""
import json
from pathlib import Path
import sys
from . import capacity_emissions,coordinate_analyzer,run_comparison
from experiments.tempo_meter_v3.probe_resources import digest


def main():
    record=json.loads(Path(sys.argv[sys.argv.index('--parameters')+1]).read_text())
    if not record['selected'].get('coordinate_refinement'):raise ValueError('coordinate route not selected')
    for key,name in [('capacity_implementation_sha256','capacity_emissions.py'),('fast_structure_implementation_sha256','fast_structure.py'),('learned_support_implementation_sha256','learned_support.py')]:
        if record[key]!=digest(Path(__file__).with_name(name)):raise ValueError('locked helper changed '+name)
    for name,expected in record['additional_implementation_sha256'].items():
        if digest(Path(__file__).with_name(name))!=expected:raise ValueError('additional implementation changed '+name)
    capacity_emissions.install()
    run_comparison.analyze=coordinate_analyzer.install()
    run_comparison.main()


if __name__=='__main__':main()
