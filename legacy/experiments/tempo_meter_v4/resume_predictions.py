"""Execution-only resource guard for unchanged, hash-bound prediction resumes.

Two source jobs may run globally; >=500-second jobs share one heavy-job mutex.
This changes scheduling, never inference, observation fields, costs or selection.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

_LOCK_ROOT=None
_ORIGINAL_JOB=None


@contextmanager
def resource_slots(duration):
    _LOCK_ROOT.mkdir(parents=True,exist_ok=True)
    slots=[(_LOCK_ROOT/('slot-'+str(i))).open('a') for i in range(2)]
    held=[]
    heavy=(_LOCK_ROOT/'heavy').open('a') if duration>=500 else None
    try:
        # Waiting for another long job must not prevent short-job admission.
        if duration>=500:
            fcntl.flock(heavy,fcntl.LOCK_EX)
        while not held:
            for slot in slots:
                try:
                    fcntl.flock(slot,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    held.append(slot);break
                except BlockingIOError:pass
            if not held:time.sleep(.2)
        yield
    finally:
        for slot in held:fcntl.flock(slot,fcntl.LOCK_UN)
        for slot in slots:slot.close()
        if heavy is not None:
            fcntl.flock(heavy,fcntl.LOCK_UN);heavy.close()


def guarded_job(row,*args,**kwargs):
    with resource_slots(row['source']['sample_frames']/row['source']['sample_rate']):
        return _ORIGINAL_JOB(row,*args,**kwargs)


def main():
    global _LOCK_ROOT,_ORIGINAL_JOB
    parser=argparse.ArgumentParser();parser.add_argument('--route',choices=['raw','learned'],required=True)
    args,forwarded=parser.parse_known_args();sys.argv=[sys.argv[0],*forwarded]
    output=Path(forwarded[forwarded.index('--output')+1]);_LOCK_ROOT=output.parent/'execution-slot-locks'
    receipt=dict(route=args.route,wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        arguments=forwarded,global_slots=2,heavy_source_seconds=500,heavy_slots=1,
        maximum_concurrent_heavy_jobs=1,scheduling_policy='two jobs, at most one >=500-second source',
        inference_changed=False,started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    (output.parent/('resume-'+args.route+'-execution.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    if args.route=='raw':
        from . import run_coordinate_parallel
        original=subprocess.run
        def guarded(command,*positional,**keyword):
            if '-m' in command and 'experiments.tempo_meter_v4.run_coordinate_comparison' in command:
                inp=Path(command[command.index('--input')+1]);row=json.loads(inp.read_text())['rows'][0]
                with resource_slots(row['source']['sample_frames']/row['source']['sample_rate']):
                    return original(command,*positional,**keyword)
            return original(command,*positional,**keyword)
        subprocess.run=guarded;run_coordinate_parallel.main()
    else:
        from . import run_learned
        _ORIGINAL_JOB=run_learned.job;run_learned.job=guarded_job;run_learned.main()


if __name__=='__main__':main()
