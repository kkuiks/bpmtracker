"""Summarize frozen results without rescoring or selecting a product model."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path('data/runs/analysis-rebuild')
TARGETS = ROOT/'20261002-v1/production-labels-v2/manifest.json'
ROUTES = (
    ('absolute-first', '20261002-v1', 'evaluation', 'predictions', 'validation-final'),
    ('absolute-control', '20261002-v2', 'absolute-control-evaluation', 'absolute-control-predictions', 'absolute-control-validation'),
    ('cadence-relative', '20261002-v2', 'evaluation', 'predictions', 'validation'),
    ('frozen-events', '20261002-v3', 'evaluation', 'predictions', 'validation'),
)


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def count_events(score, kind):
    counts = score.get(kind+'_change_counts')
    if counts is not None:
        return [counts[k] for k in ('true_positives', 'false_positives', 'false_negatives')]
    key = 'false_'+kind+'_changes_in_reference_scope'
    return [0, score[key], 0] if key in score else None


def route_summary(spec, splits):
    name, directory, evaluation, predictions, validation = spec
    folder = ROOT/directory
    scores = read(folder/evaluation/'scores.json')
    predictions_record = read(folder/predictions/'manifest.json')
    selection = read(folder/validation/'selection.json')
    assert predictions_record['complete'] and selection['complete']
    assert digest(folder/predictions/'manifest.json') == scores['prediction_manifest_sha256']
    expected = {r['id']: r for r in predictions_record['rows']}
    rows = []
    for row in scores['rows']:
        p = expected[row['id']]
        assert digest(p['selected']['path']) == row['prediction_sha256']
        physical = read(p['selected']['path'])
        score = row['score']
        rows.append(dict(id=row['id'], title=row['title'], role=row['role'],
                         split=splits.get(row['id'], 'auxiliary'),
                         status=p['prediction_status'], pass_all=score['all_gates_pass'],
                         scores=row['aggregation_contributions'], original_scores=score['scores'],
                         gates=score['gates'], tempo_counts=count_events(score, 'tempo'),
                         meter_counts=count_events(score, 'meter'),
                         cached_seconds=p['runtime_seconds'],
                         observed_bar_count=len(physical.get('physical_timeline', {}).get('bar_events', [])),
                         maximum_export_bar_displacement_seconds=physical.get('export', {}).get('max_export_bar_displacement_seconds'),
                         free_tail_false_positives=score.get('free_tail_false_positives'),
                         grid_end_error_seconds=score.get('grid_end_error_seconds')))
    finished = [r for r in rows if r['split'] != 'auxiliary']
    assert len(finished) == 20 and len(rows) == 21
    metrics = list(rows[0]['scores'])
    counts = {}
    for kind in ('tempo', 'meter'):
        available = [r[kind+'_counts'] for r in finished if r[kind+'_counts'] is not None]
        counts[kind] = dict(tp_fp_fn=[sum(c[i] for c in available) for i in range(3)],
                            scored_recordings=len(available), total_recordings=20,
                            unavailable=[r['id'] for r in finished if r[kind+'_counts'] is None])
    return dict(name=name, directory=directory, scores_sha256=digest(folder/evaluation/'scores.json'),
                prediction_manifest_sha256=digest(folder/predictions/'manifest.json'),
                selection_sha256=digest(folder/validation/'selection.json'),
                selected=selection['selected'], passing_excerpts=[r['passing_excerpts'] for r in selection['checkpoint_comparisons']],
                complete_passes={split:sum(r['pass_all'] for r in rows if r['split']==split) for split in ('train','validation','auxiliary')},
                finished_passes=sum(r['pass_all'] for r in finished), auxiliary_passes=sum(r['pass_all'] for r in rows if r['split']=='auxiliary'),
                decode_failures=sum(r['status']=='decode_failed' for r in rows),
                finished_macro_scores={k:sum(r['scores'][k] for r in finished)/20 for k in metrics},
                all21_macro_scores=scores['cohort_metric_averages_with_failure_penalty'],
                change_counts=counts,
                finished_cached_median_seconds=statistics.median(r['cached_seconds'] for r in finished),
                finished_cached_max_seconds=max(r['cached_seconds'] for r in finished), rows=rows)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'20261002-v1');a=p.parse_args()
    targets=read(TARGETS);splits={r['id']:r['split'] for r in targets['rows']}
    routes=[route_summary(spec,splits) for spec in ROUTES]
    result=dict(scope='Known development recordings20 plus auxiliary1; no unseen claim',
                complete=True, targets_sha256=digest(TARGETS),routes=routes,
                decision='Reject all tested accuracy settings; retain factored implementation and speed evidence',
                product_model_selected=False, scorer_changed=False,
                failure_policy='Complete-pass denominator20 retains failed decodes; macro contribution zero; original per-song scores remain unavailable',
                change_count_policy='Sum available scored recordings only; failed decodes reported explicitly, never interpreted as successful no-change maps')
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'comparison-summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    lines=['# Different analysis-engine rebuild: first bounded comparison', '',
           '**Decision: none of the tested models qualifies as the replacement product analyzer.** The factored service is implemented and callable; automatic accuracy remains inadequate. Preserve it as experimental source and retain all old artifacts.', '',
           '## Authorized scope and preservation', '',
           'The owner requested a different approach after the independent-review route failed, and selected the analysis engine before UI/editing/export. The full quarter-BPM, tempo-change, meter/meter-change, bar and no-grid task is retained. 104 old v3/v4 source files are snapshotted and 16 final-run/model artifacts are bound in place by `preservation.json`. No originals were moved/deleted; no commit/push, paid GPU, new acquisition, reference/default promotion or native Windows claim.', '',
           '## What changed', '',
           'The new `services/analysis/` predicts chronological quarter/bar/grid events, production quarter rate and denominator semantics with a two-layer bidirectional recurrent model. A vectorized timing-only piecewise regression replaces meter/group/repetition path competition. A separately supervised note unit interprets detected bar lengths; it cannot alter numerical clock knots or native bar timestamps. The frozen Beat This encoder is reused. No old reconstructor is imported by the service. Source snapshots, weight hashes, source/cache bindings and prediction-before-reference receipts preserve the comparison.', '',
           'The shared schema stores timestamp estimates and notation hypotheses separately. “Physical” here means the estimated timestamp layer, not an assertion that a uniquely correct bar grouping is observable in audio. Quarter units and bar labels still require musical interpretation. Legacy exports disclose bar displacement introduced by incompatible/missing notation. No new structural-equivalence scoring is adopted.', '',
           '## Targets, fitting and selection', '',
           'All 20 known recordings retain the existing 14 training/6 held-from-fit split and conservative producer grouping. The auxiliary GuitarSet clip is not fitted. Existing qualified quarter/bar/support labels and masking remain. New rate and denominator labels use approved production maps, including the accepted RWC constant 100 map rather than its raw interval-derived MIDI tempo. `production-labels-v2` corrects inherited old qualification flags; all 20 numerical targets match the retained first revision. No grouping labels are fabricated.', '',
           'References are owner-reviewed production maps with individual approved scopes, not independently certified original-click millisecond ground truth. Accepted maps are already audio-relative; no additional offset or reference-derived phase correction is applied. Unknown margins remain excluded, distinct from explicit no-grid tails. Sources and frozen reference bindings remain unchanged.', '',
           'The first 600-step two-example fit failed Deadman bars. The otherwise unchanged 2400-step fit passed quarter/bar/denominator training gates on both 48s examples. The cadence variant also passed its 2400-step tiny check. This proves limited trainability, not real-song accuracy. Each main observer uses three seeds × 1600 updates, with 400/1600 checkpoints. Selection reuses the exact eight frozen held excerpts across six already-known sources, equal-source six-score mean, failures zero, earlier checkpoint/lower seed for ties. All six checkpoints of each route have zero complete excerpt passes. Repeated selection on these known excerpts is development, not a clean unseen holdout.', '',
           '| Route | Selected seed/step | Held selection mean | Finished all-gate passes | Train/held/aux passes | Failed decodes |',
           '| --- | --- | ---: | ---: | --- | ---: |']
    for r in routes:
        s=r['selected'];step=Path(s['selected']).stem.split('-')[-1];n=r['complete_passes']
        lines.append(f"| {r['name']} | {s['seed']}/{step} | {s['map_selection_value']:.6f} | {r['finished_passes']}/20 | {n['train']}/14, {n['validation']}/6, {n['auxiliary']}/1 | {r['decode_failures']} |")
    lines += ['', '## Accuracy and false positives', '',
              'The unchanged frozen scorer requires all six individual scores ≥90%, 70ms quarter/bar events and 500ms changes; tempo changes also require both rates within 0.1 BPM. Extra events remain penalized, any false change fails a constant-reference gate, and known no-grid/end gates remain. Every failed map stays in the full 20 denominator. Original unavailable scores remain null; only macro contributions are zero. Existing limited owner-approved equivalences remain; no song-specific answer list or newly relaxed score.', '',
              '| Route | Quarter BPM % | Meter % | Quarter-event F1 % | Bar F1 % | Tempo TP/FP/FN | Meter TP/FP/FN |',
              '| --- | ---: | ---: | ---: | ---: | --- | --- |']
    for r in routes:
        values=list(r['finished_macro_scores'].values())[:4]
        t=r['change_counts']['tempo']['tp_fp_fn'];m=r['change_counts']['meter']['tp_fp_fn']
        lines.append('| '+r['name']+' | '+' | '.join(f'{100*v:.3f}' for v in values)+' | '+'/'.join(map(str,t))+' | '+'/'.join(map(str,m))+' |')
    lines += ['', 'Change-count sums cover available scored maps only; `comparison-summary.json` identifies missing counts explicitly. Finished-only macro scores above differ from the all 21 macro retained in each evaluation. Auxiliary outcomes are counted separately.', '',
              'The cadence observer improves the held selection mean relative to the absolute observer under the same expanded pulse families, but does not increase complete-song passes. The absolute control has 2/20 passes (San Quentin and Godsmack), the other settings 1/20 (San Quentin). These settings all remain below the preserved same-observation v2 result 8/20 + 1/1. The old frozen generic13 result 10/13 is a distinct, smaller development comparison and is not rewritten. The previous v3/frozen and bounded joint results 2/20 + 1/1 remain historical controls; their guide/input conditions differ from this unhinted service.', '',
              'The first-versus-expanded-clock comparison also changes the chosen checkpoint, so it does not isolate pulse-family causality. The frozen-event route is reselected on the held excerpts, so its whole-song contrast is a route comparison; it is not a pure fixed-weight causal estimate. No route is selected for deployment by whole-song scores.', '',
              '## Per-recording results', '',
              'Values are the original frozen six-score aggregation aliases, in percent. `failed` is unavailable rather than a numerically scored wrong map. All rows including difficult recordings remain. Each subsection reports the same source IDs and scopes; full gates, counts, tail false positives, runtime, native-bar count and maximum compatibility displacement are in the JSON.', '']
    for r in routes:
        lines += ['### '+r['name'], '', '| Recording | Exposure | BPM | Meter | Quarter | Bar | Tempo change | Meter change | Complete | Cached s |',
                  '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |']
        for row in r['rows']:
            values=' | '.join(f'{v*100:.2f}' for v in row['scores'].values()) if row['status']!='decode_failed' else ' | '.join(['failed']*6)
            lines.append(f"| {row['title']} (`{row['id']}`) | {row['split']} | {values} | {'pass' if row['pass_all'] else 'fail'} | {row['cached_seconds']:.3f} |")
        lines += ['']
    lines += ['## Runtime and portable execution', '',
              'Cached timings measure observer plus numerical reconstruction, excluding acoustic extraction, startup and I/O. They use the existing WSL CPU configuration, not a Windows product benchmark.', '',
              '| Route | Finished cached median s | Finished cached maximum s |', '| --- | ---: | ---: |']
    for r in routes:lines.append(f"| {r['name']} | {r['finished_cached_median_seconds']:.3f} | {r['finished_cached_max_seconds']:.3f} |")
    cold=ROOT/'20261002-v2/cold-godsmack-final'
    run=read(cold/'result/run.json');wall=read(cold/'execution.json')
    seconds=run['source']['sample_frames']/run['source']['sample_rate']
    lines += ['',f"One actual fresh-cache Godsmack source of {seconds:.3f}s completed in {wall['wall_seconds_including_python_start']:.3f}s including Python startup; engine internal time {run['total_seconds']:.3f}s, acoustic extraction/model initialization {run['acoustic']['elapsed_seconds']:.3f}s, observer {run['observation_seconds']:.3f}s, complete reconstruction/export {run['decode_seconds']:.3f}s. This uses the absolute-control checkpoint, local MX450 and WSL. It is one measured case, not a general upper bound, native Windows proof or accuracy guarantee.", '',
              'The first original 177.085s cold probe recorded 8.575s inside the service, excluding process startup. Its fresh acoustic features, logits and energy are byte-for-byte array-equal to the preserved feature cache (`cold-godsmack/acoustic-parity.json`). The rejected old learned route had 384.943s finished-recording cached median; this is a large timing reduction with worse accuracy, not an adoption result.', '',
              '## Failure-stage evidence and interpretation', '',
              'The first tiny fit demonstrates trainability only. In the selected cadence Equilibrium 64s excerpt, only three native bar events were observed and the exporter proposed a 24/2 continuation; this is a bar-observation/notation failure despite a correct numerical quarter clock. RWC in the first pilot chose ~200 quarter BPM and 8/4 while retaining most true bar times; the quarter unit is wrong even though an existing paired-bar meter diagnostic can be 100%. The returned maps contain many false tempo and meter changes. Walker grid/end/no-grid failures remain; successful construction of a JSON map is not musical correctness.', '',
              'These observations support specific component failures; they do not prove that the general research family or the new representation is impossible. Absolute-rate learning from limited producers, joint task interference, pulse-family normalization, bar-head adaptation and denominator compatibility are hypotheses with confounded causal evidence. Native/export bar disagreement is disclosed, not silently repaired using references. Learned scores are uncalibrated. General notation equivalence, uncertain/no-grid boundary calibration, source-verified musical origins, unseen music and native Windows remain open.', '',
              '## Completion and next decision', '',
              'Preservation, a separate callable source-only implementation, three observer/control comparisons, full 21 attempted predictions, unchanged evaluation and actual cold audio probes are complete. The final service retains its numerical timeline when notation export fails, emits an explicit failure receipt and uses no fabricated constant-map fallback. A real Sleeping With Sirens CLI execution returns code2, map null and a retained timeline; this is a correctly reported inference failure, not a recovered pass. This output-layer repair does not change the scored map. Core contract tests and real-map parity are recorded separately.', '',
              '**Product-quality analysis is not complete.** Retain this architecture as experimental implementation; reject these weights/settings as the product analyzer. Do not repeat completed comparisons or request more listening merely to reject them. Further research needs a bounded hypothesis addressing unit/phase/bar semantics and false changes, with a same-input control and immutable full-song denominator. An actual new-song evaluation follows only after a model and selection policy are frozen; no new cohort is acquired by this unit.', '',
              'Primary evidence: `preservation.json`, `production-labels-v2/manifest.json`, `protocol-effective.json`, `validation-final/selection.json`, sibling v2/v3 protocol/source/selection/prediction/evaluation receipts, `comparison-summary.json`, cold-run receipts and final verification. No inference code reads private notes or reference catalogs.']
    (a.output/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({r['name']:dict(finished=r['finished_passes'],auxiliary=r['auxiliary_passes'],failed=r['decode_failures']) for r in routes},indent=2))


if __name__=='__main__':main()
