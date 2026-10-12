"""Compare the export worker with actual renderer geometry for the approved map change."""
from pathlib import Path
import ast
import json
import math
import struct

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'data/research/design-reviews/20261011-continuous-beat-map-v1/implementation-checks'
source = ast.parse((ROOT / 'apps/daw/backend/worker.py').read_text())
functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
             and node.name in {'musical_map', 'geometry', 'analysis_geometry', 'write_project_midi', 'write_midi', 'vlq', 'write_json', 'export'}]
scope = {'math': math, 'struct': struct, 'Path': Path, 'json': json}
exec(compile(ast.Module(body=functions, type_ignores=[]), 'worker-map-functions', 'exec'), scope)
checks = []
for fixture in json.loads((OUT / 'fixtures.json').read_text()):
    renderer = fixture['renderer_clocks']
    backend = scope['geometry'](fixture['project'])
    assert len(renderer) == len(backend), fixture['name']
    for left, right in zip(renderer, backend):
        for key in ['bpm', 'numerator', 'denominator', 'start', 'end', 'phase']:
            assert abs(left[key] - right[key]) < 1e-8, (fixture['name'], key, left, right)
    checks.append({'fixture': fixture['name'], 'pass': True})
    # Run the actual map-export branch, with no audio assets or WAV outputs.
    folder=OUT / ('export-' + fixture['name'])
    suffix=0
    while folder.exists():
        suffix+=1;folder=OUT / ('export-' + fixture['name'] + f'-{suffix}')
    scope['export']({'project':fixture['project'],'options':{'start':0,'end':12,'maps':True,'mix':False,'stems':False,'click':False},'output':str(folder)})
    document=json.loads((folder / 'Tempo Map.json').read_text())
    assert document['schemaVersion']==fixture['project']['version']
    assert document['projectBpm']==fixture['project']['bpm']
    assert (folder / 'Tempo Map.mid').read_bytes().startswith(b'MThd')
    expected={e['id']:e['quarter'] for e in fixture['project']['signatures'] if 'quarter' in e}
    actual={e['id']:e['quarter'] for e in document['projectSignatureEvents']}
    for identity,quarter in expected.items():assert actual[identity]==quarter
    checks.append({'fixture':fixture['name'],'actual_json_and_midi_export_branch':True,'pass':True})
(OUT / 'backend-checks.json').write_text(json.dumps({'checks': checks, 'all_pass': True}, indent=2) + '\n')
print('CONTINUOUS_MAP_BACKEND', len(checks), 'PASS')
