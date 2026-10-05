"""Audit annotation-only public meter grammar before any audio-model use."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import subprocess
from .run_constant_grid11 import digest,save


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--dataset',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 if a.output.exists():raise FileExistsError('new audit output required')
 root=a.dataset.resolve()
 commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 files=sorted((root/'parsed_beats').glob('*.json'))
 if len(files)<20:raise ValueError('parsed measure annotations unavailable')
 meters=Counter();transitions=Counter();patterns=defaultdict(list)
 rows=[];names=set()
 for path in files:
  record=json.loads(path.read_text())
  ident=record['youtube_id']
  if ident in names:raise ValueError('duplicate recording identity')
  names.add(ident)
  measures=record['measures']
  if len(measures)<2:raise ValueError('short annotated track')
  times=[float(x['downbeat_sec']) for x in measures]
  if any(b<=a for a,b in zip(times,times[1:])):raise ValueError('nonmonotonic downbeats')
  sequence=[(int(x['time_sig_num']),int(x['time_sig_den'])) for x in measures]
  if any(n<=0 or d<=0 for n,d in sequence):raise ValueError('invalid meter')
  for meter in sequence:meters[meter]+=1
  for before,after in zip(sequence,sequence[1:]):
   if before!=after:transitions[before,after]+=1
  for i in range(1,len(sequence)-1):
   if sequence[i-1]==sequence[i+1]==(4,4) and sequence[i] in ((2,4),(6,4)):
    patterns[sequence[i]].append({'youtube_id':ident,'measure_index':i})
  rows.append({'youtube_id':ident,'measure_count':len(measures),
    'change_count':sum(a!=b for a,b in zip(sequence,sequence[1:])),
    'original_file_sha256':digest(root/'beats'/path.name.removesuffix('.beats.json')),
    'parsed_sha256':digest(path)})
 counts={f'{n}/{d}':len(patterns[(n,d)]) for n,d in ((2,4),(6,4))}
 groups={f'{n}/{d}':len({r['youtube_id'] for r in patterns[(n,d)]})
         for n,d in ((2,4),(6,4))}
 out=a.output.resolve();out.mkdir(parents=True)
 snapshot=out/'source-snapshot';snapshot.mkdir();shutil.copy2(__file__,snapshot/Path(__file__).name)
 report={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),
  'annotation_only':True,'source_audio_acquired':False,
  'dataset_repo':'anime-song/uncommon-meter-beat-dataset',
  'dataset_commit':commit,
  'license':'MIT for annotations; source audio excluded',
  'metadata_sha256':digest(root/'metadata.csv'),
  'source_overlap_check':'target titles/artist tokens absent from metadata.csv, checked separately',
  'track_count':len(rows),'measure_count':sum(x['measure_count'] for x in rows),
  'tracks_with_changes':sum(x['change_count']>0 for x in rows),
  'meters':{f'{n}/{d}':count for (n,d),count in meters.most_common()},
  'transition_counts':{f'{a[0]}/{a[1]}->{b[0]}/{b[1]}':count
                       for (a,b),count in transitions.most_common()},
  'context':'single 2/4 or 6/4 measure flanked on both sides by 4/4',
  'context_event_counts':counts,'context_distinct_track_counts':groups,
  'context_examples':{f'{n}/{d}':patterns[(n,d)] for n,d in ((2,4),(6,4))},
  'rows':rows,'runner_sha256':digest(__file__)}
 save(out/'audit.json',report)
 print('tracks',report['track_count'],'measures',report['measure_count'],
       'changes',report['tracks_with_changes'],'single-between-four',counts,'groups',groups)
if __name__=='__main__':main()
