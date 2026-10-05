"""Continue only after full predictions: fixed scoring, conditional tiny fit and3seeds."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--fixed-observations-only',action='store_true',help='Finish frozen paired comparison and report, without starting conditional training')
    p.add_argument('--main-steps',type=int,default=800)
    p.add_argument('--wait-existing-learned',action='store_true',
        help='Wait for the separately running learned comparison instead of launching duplicate predictions')
    a=p.parse_args();run=a.run
    input_path='data/runs/tempo-meter-v3/reviewed21-frozen-20260930-v1/predictions/manifest.json'
    inventory='data/runs/tempo-meter-v3/reviewed21-frozen-20260930-v1/reference-inventory.json'
    parameters=run/'parameters-locked.json';supervision=run/'production-supervision-locked/manifest.json'
    def status(stage,**extra):
        record=dict(stage=stage,updated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**extra)
        (run/'pipeline-status.json').write_text(json.dumps(record,indent=2)+'\n');print(record,flush=True)
    def execute(module,arguments,log):
        command=[sys.executable,'-m',module,*map(str,arguments)]
        with (run/'commands.txt').open('a') as f:f.write(' '.join(command)+'\n')
        with (run/log).open('a') as stream:result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(module+' failed; see '+str(run/log))
    try:
        status('waiting_complete_source_predictions')
        while True:
            paths=[run/'predictions-parallel'/arm/'manifest.json' for arm in ['no_repeat','automatic_repeat']]
            if all(p.exists() and json.loads(p.read_text())['complete'] for p in paths):break
            logfile=run/'comparison-parallel.log'
            if logfile.exists() and 'Traceback' in logfile.read_text():raise RuntimeError('parallel prediction failed; inspect source logs')
            time.sleep(15)
        for arm in ['no_repeat','automatic_repeat']:
            status('scoring_'+arm)
            if not (run/('evaluation-'+arm)/'scores.json').exists():
                execute('experiments.tempo_meter_v3.evaluate_reviewed',['--manifest',run/'predictions-parallel'/arm/'manifest.json','--inventory',inventory,'--output',run/('evaluation-'+arm)],'evaluation-'+arm+'.log')
        execute('experiments.tempo_meter_v4.report_document_route',['--run',run],'report-stage2.log')
        comparison=json.loads((run/'comparison-summary.json').read_text())
        if a.fixed_observations_only:
            status('fixed_observation_comparison_complete',training_started=False,
                conditional_learning_complete=False,private_notes_pending=True,promotion=False);return
        if all(comparison['summaries'][arm]['finished_passed']==20 for arm in ['no_repeat','automatic_repeat']):
            status('complete_fixed_observation_comparison',training_needed=False);return
        status('tiny_actual_fit')
        if not (run/'tiny-training/training.json').exists():
            execute('experiments.tempo_meter_v4.train_production',['--manifest',supervision,'--output',run/'tiny-training','--steps','600','--tiny'],'tiny-training.log')
        if not (run/'tiny-fit-check/trainability.json').exists():
            execute('experiments.tempo_meter_v4.tiny_fit_check',['--manifest',supervision,'--training',run/'tiny-training','--parameters',parameters,'--output',run/'tiny-fit-check'],'tiny-fit-check.log')
        sanity=json.loads((run/'tiny-fit-check/trainability.json').read_text())
        if not sanity['passed']:raise RuntimeError('Tiny actual fit fails; main training withheld until label/loss/implementation diagnosis')
        status('three_seed_actual_fit')
        if not (run/'production-training/training.json').exists():
            execute('experiments.tempo_meter_v4.train_production',['--manifest',supervision,'--output',run/'production-training','--steps',str(a.main_steps)],'production-training.log')
        status('held_group_actual_excerpt_map_validation')
        if not (run/'production-validation/selection.json').exists():
            execute('experiments.tempo_meter_v4.validate_production',['--manifest',supervision,'--training',run/'production-training','--parameters',parameters,'--output',run/'production-validation'],'production-validation.log')
        status('selected_model_whole_source_predictions')
        if a.wait_existing_learned:
            status('waiting_existing_learned_predictions')
            while True:
                manifest=run/'predictions-learned/manifest.json'
                if manifest.exists() and json.loads(manifest.read_text())['complete']:break
                logfile=run/'predictions-learned.log'
                if logfile.exists() and 'Traceback' in logfile.read_text():
                    raise RuntimeError('existing learned comparison failed; inspect its log')
                time.sleep(15)
        if not (run/'predictions-learned/manifest.json').exists() or not json.loads((run/'predictions-learned/manifest.json').read_text())['complete']:
            arguments=['--input',input_path,'--selection',run/'production-validation/selection.json','--parameters',parameters,'--output',run/'predictions-learned','--workers','2']
            if (run/'predictions-learned').exists():arguments.append('--resume')
            execute('experiments.tempo_meter_v4.run_learned',arguments,'predictions-learned.log')
        status('scoring_learned_whole_sources')
        if not (run/'evaluation-learned/scores.json').exists():
            execute('experiments.tempo_meter_v4.evaluate_learned',['--input',input_path,'--manifest',run/'predictions-learned/manifest.json','--inventory',inventory,'--reference-directory','data/runs/tempo-meter-v3/reviewed21-frozen-20260930-v1/evaluation','--output',run/'evaluation-learned'],'evaluation-learned.log')
        execute('experiments.tempo_meter_v4.report_document_route',['--run',run],'report-final.log')
        status('experiments_complete_reports_ready',private_notes_pending=True,promotion=False)
    except Exception as error:
        status('failed_requires_inspection',error=str(error));raise


if __name__=='__main__':main()
