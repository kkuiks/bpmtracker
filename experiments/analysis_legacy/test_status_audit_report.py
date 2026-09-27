import unittest

from build_status_audit_report import TOLERANCES, aggregate, beat_this_summary, gtzan_summary, crossed_rows, normalize_bt_coverage


class StatusAuditReportTests(unittest.TestCase):
    def test_aggregate_keeps_cohorts_separate_and_counts_failures(self):
        rows=[]
        for cohort,value in [('a',.9),('b',.1)]:
            rows.append({'id':cohort,'cohort':cohort,'method':'model__clock','method_status':'failed' if cohort=='b' else 'ok',
                'prediction_count':0 if cohort=='b' else 4,'tempo_map_produced':cohort=='a',
                **{'f1_'+name:value for name in TOLERANCES},
                **{'tempo_changes_100ms_'+key:0 for key in ('tp','fp','fn')},
                **{'tempo_changes_500ms_'+key:0 for key in ('tp','fp','fn')}})
        result=aggregate(rows)
        self.assertEqual(set(result),{'a','b'})
        self.assertEqual(result['b']['methods']['model__clock']['empty_predictions'],1)
        self.assertEqual(result['a']['methods']['model__clock']['mean_f1']['20ms'],.9)

    def test_beat_this_summary_excludes_owner_rejected_ids(self):
        score={str(v):{'f1':.25} for v in (.01,.02,.03,.07)}
        high={str(v):{'f1':.75} for v in (.01,.02,.03,.07)}
        def row(track_id,values):
            variants={name:{'annotated_span':{'beats_seconds':values,'downbeats_seconds':None}}
                      for name in ('official_minimal','legacy_dbn','clock_pipeline')}
            return {'id':track_id,'dataset':'set','clock_status':'ok','scores':variants}
        report={'tracks':[row('keep',high),row('reject',score)]}
        result=beat_this_summary(report,{'reject'})
        self.assertEqual(result['set']['distinct_audio_count'],1)
        self.assertEqual(result['set']['methods']['legacy_dbn_clock']['macro_f1']['20ms'],.75)

    def test_gtzan_summary_is_explicitly_supplementary(self):
        score={str(v):{'f1':.5} for v in (.01,.02,.03,.07)}
        variants={name:{'annotated_span':{'beats_seconds':score}}
                  for name in ('official_minimal','legacy_dbn','clock_pipeline')}
        report={'tracks':[{'genre':'rock','clock_status':'fallback_x','scores':variants}]}
        result=gtzan_summary(report)
        self.assertIn('supplementary',result['scope'])
        self.assertEqual(result['methods']['official_minimal']['macro_f1']['30ms'],.5)
        self.assertEqual(result['methods']['legacy_dbn_clock']['clock_fallback_count'],1)

    def test_failed_candidate_maps_retain_full_cohort_change_denominator(self):
        catalog = {'tracks': []}; report = {'tracks': []}; references = {}
        metric = {'f1': 0., 'precision': 0., 'recall': 0., 'false_negatives': 3, 'false_positives': 0}
        for i, count in enumerate((5, 6, 4)):
            track_id = str(i)
            catalog['tracks'].append({'id': track_id, 'reference': {'sha256': 'test'}, 'reference_tier': 'test'})
            references[track_id] = {'beats_seconds': [1., 2., 3.], 'downbeats_seconds': [1.],
                'evaluation_support_seconds': [0., 20.],
                'tempo_events': [{'time_seconds': float(j), 'bpm_quarter': 120. + j} for j in range(count + 1)]}
            clock = {'support_seconds': [0., 20.], 'segments': [
                {'start_seconds': 0., 'pulse_rate_per_minute': 120.}]} if i == 0 else None
            report['tracks'].append({'id': track_id, 'cohort': 'creator', 'methods': {
                'beat_this__clock_candidates_selected': {
                    'prediction': {'beats_seconds': [], 'downbeats_seconds': []}, 'clock': clock,
                    'status': 'insufficient_evidence', 'metrics': {
                        **{'event_' + t: metric for t in TOLERANCES},
                        **{'downbeat_' + t: metric for t in TOLERANCES}}}}})
        rows = crossed_rows(report, catalog, references)
        result = aggregate(rows)['creator']['methods']['beat_this__clock_candidates_selected']
        self.assertEqual(result['tempo_changes_500ms']['fn'], 15)
        self.assertEqual(result['tempo_changes_500ms']['eligible_tracks'], 3)
        self.assertEqual(result['tempo_changes_500ms']['failed_map_tracks_included'], 2)
        self.assertEqual(result['tempo_map_failure_count'], 2)
        self.assertIsNone(result['mean_downbeat_f1']['20ms'])
        self.assertEqual(result['downbeat_output_status'], 'unsupported')

    def test_blocked_input_count_is_distinct_from_documented_crashes(self):
        manifest = {'rows': [{'id': 'a', 'status': 'reused'},
                             {'id': 'b', 'status': 'frontend_runtime_failure'},
                             {'id': 'c', 'status': 'frontend_runtime_failure'}]}
        result = normalize_bt_coverage(manifest, {'reproductions': [{'input': 'a'}, {'input': 'b'}]})
        self.assertEqual(result['counts'], {'reused': 1, 'blocked_by_shared_frontend_failure': 2})
        self.assertEqual(result['documented_frontend_distinct_input_count'], 2)
        self.assertFalse(result['rows'][2]['frontend_failure_reproduced_on_this_input'])
        self.assertEqual(manifest['rows'][1]['status'], 'frontend_runtime_failure')


if __name__=='__main__':unittest.main()
