"""Add qualified production-rate and note-unit supervision, offline only."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

from services.analysis.timeline import DENOMINATORS


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser();p.add_argument('--manifest', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    args = p.parse_args();manifest = json.loads(args.manifest.read_text());args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    for row in manifest['rows']:
        if digest(row['reference_map']) != row['reference_map_sha256'] or digest(row['targets']) != row['targets_sha256']:
            raise ValueError('qualified target binding changed')
        ref = json.loads(Path(row['reference_map']).read_text())['map']
        with np.load(row['targets']) as z:y, mask = z['y'].copy(), z['mask'].copy()
        count = len(y);seconds = np.arange(count)/50
        knots = ref['clock_knots'];q = np.asarray([k['pulse'] for k in knots]);t = np.asarray([k['source_seconds'] for k in knots])
        factor = ref['quarters_per_pulse']['numerator']/ref['quarters_per_pulse']['denominator']
        index = np.clip(np.searchsorted(t, seconds, side='right')-1, 0, len(t)-2)
        rates = 60*factor*np.diff(q)[index]/np.diff(t)[index]
        pulse = q[index]+(seconds-t[index])*np.diff(q)[index]/np.diff(t)[index]
        meters = ref['meter_events'];changes = np.asarray([m['pulse'] for m in meters]);mi = np.clip(np.searchsorted(changes, pulse, side='right')-1, 0, len(meters)-1)
        denominators = np.asarray([DENOMINATORS.index(m['denominator']) for m in meters])[mi]
        grid_mask = mask*y[:, 2]
        target = args.output/(row['id']+'.npz')
        np.savez_compressed(target, y=y, mask=mask, log_bpm=np.log(rates).astype(np.float32),
                            denominator=denominators.astype(np.int64), musical_mask=grid_mask)
        updated = dict(row, targets=str(target.resolve()), targets_sha256=digest(target),
                       old_targets_sha256=row['targets_sha256'], label_contract='quarter/bar/grid plus approved piecewise production rate and separate note-unit label; no raw MIDI interval tempo or inferred grouping')
        updated['qualification']=dict(row['qualification'],bpm_regression_supervised=True,
                                      denominator_supervised=True,numerator_supervised=False,
                                      meter_classes_supervised=False,
                                      meter_interpretation='separate denominator supervision and physical quarter-length compatibility')
        rows.append(updated)
    out = dict(manifest, rows=rows, previous_manifest_sha256=digest(args.manifest),
               architecture='physical timing independent of note-unit interpretation',
               target_contract='50fps quarter/bar/grid events plus approved log quarter-BPM and denominator class; musical mask excludes no-grid and unknown regions',
               qualification_note='Approved adapted production clocks; RWC uses the accepted constant100 map, never its interval-derived MIDI tempo entries')
    (args.output/'manifest.json').write_text(json.dumps(out, indent=2)+'\n')
    print(json.dumps(dict(rows=len(rows), train=sum(r['split']=='train' for r in rows), validation=sum(r['split']=='validation' for r in rows))))


if __name__ == '__main__':main()
