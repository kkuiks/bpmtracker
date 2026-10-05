"""Explicit capacity-score variant of the same frozen-observation experiment."""
import json
from pathlib import Path
import sys
from . import capacity_emissions
from .run_comparison import main
from experiments.tempo_meter_v3.probe_resources import digest

if __name__=='__main__':
    index=sys.argv.index('--parameters')
    record=json.loads(Path(sys.argv[index+1]).read_text())
    if record['capacity_implementation_sha256']!=digest(capacity_emissions.__file__):raise ValueError('capacity implementation differs from lock')
    if record['fast_structure_implementation_sha256']!=digest(Path(__file__).with_name('fast_structure.py')):raise ValueError('fast implementation differs from lock')
    if record['learned_support_implementation_sha256']!=digest(Path(__file__).with_name('learned_support.py')):raise ValueError('support implementation differs from lock')
    for name,expected in record.get('additional_implementation_sha256',{}).items():
        if digest(Path(__file__).with_name(name))!=expected:raise ValueError('additional implementation differs '+name)
    capacity_emissions.install()
    main()
