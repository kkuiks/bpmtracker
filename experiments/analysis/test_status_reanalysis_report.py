"""Synthetic checks for report denominators and unavailable-capability semantics."""
import unittest

from build_status_reanalysis_report import aggregate, metric_row, TOLERANCES
from compare_clock_candidates import evaluate_times


class StatusReanalysisReportTests(unittest.TestCase):
    def reference(self):
        return {'evaluation_support_seconds':[0.,4.], 'beats_seconds':[0.,.5,1.,1.5,2.,2.4,2.8,3.2,3.6,4.],
            'downbeats_seconds':None,
            'tempo_events':[{'time_seconds':0.,'bpm_quarter':120.},
                            {'time_seconds':2.,'bpm_quarter':150.}],
            'meter_events':None}

    def item(self,track_id='a',admission='admitted_reference'):
        return {'id':track_id,'cohort':'sample','model':'beat_this','evaluation_admission':admission}

    def row(self,track_id,score,group_id='one',admission='admitted_reference',method='clock'):
        scores={'event_'+label:{'f1':score} for label in TOLERANCES}
        value={'clock':{'support_seconds':[0.,4.]},'prediction':[0.,.5],
               'status':'proposal','capabilities':{'tempo_map':True}}
        return metric_row(self.item(track_id,admission),method,value,scores,{'group_id':group_id},'core')

    def test_capable_failed_map_keeps_missed_changes_and_zero_beats(self):
        metrics=evaluate_times(self.reference(),[],None,tempo_map_supported=True)
        row=metric_row(self.item(),'clock',{'clock':None,'prediction':[],
            'status':'failed_no_tempo_map','capabilities':{'tempo_map':True}},metrics,{},'core')
        result=aggregate([row])[0]
        self.assertEqual(result['track_count'],1)
        self.assertEqual(result['empty_predictions'],1)
        self.assertEqual(result['failed_tempo_maps'],1)
        self.assertEqual(result['beat_20ms_macro_f1'],0.)
        self.assertEqual(result['tempo_100ms']['scored_track_count'],1)
        self.assertEqual(result['tempo_100ms']['false_negatives'],1)

    def test_unsupported_map_is_not_counted_as_failed_map(self):
        metrics=evaluate_times(self.reference(),self.reference()['beats_seconds'],None,tempo_map_supported=False)
        row=metric_row(self.item(),'official',{'clock':None,'prediction':self.reference()['beats_seconds'],
            'status':'beat_output','capabilities':{'tempo_map':False}},metrics,{},'core')
        result=aggregate([row])[0]
        self.assertEqual(result['failed_tempo_maps'],0)
        self.assertIsNone(result['tempo_100ms'])
        self.assertEqual(result['beat_20ms_macro_f1'],1.)
        self.assertEqual(row['tempo_100ms_status'],'unsupported_tempo_map')

    def test_unscored_and_owner_rejected_rows_cannot_enter_primary_mean(self):
        rows=[self.row('kept',.25),self.row('unscored',1.,admission='prediction_only'),
              self.row('rejected',1.,admission='owner_rejected_reference')]
        result=aggregate(rows)[0]
        self.assertEqual(result['track_count'],1)
        self.assertEqual(result['beat_20ms_macro_f1'],.25)
        self.assertEqual(aggregate(rows[1:]),[])

    def test_missing_reference_stays_blank_in_per_track_output(self):
        row=metric_row(self.item(admission='prediction_only'),'clock',
            {'clock':None,'prediction':[.1,.6],'status':'proposal','capabilities':{'tempo_map':True}},
            None,{},'core')
        self.assertIsNone(row['beat_20ms_f1'])
        self.assertIsNone(row['downbeat_20ms_f1'])
        self.assertIsNone(row['tempo_100ms_true_positives'])

    def test_group_mean_weights_performer_groups_equally(self):
        rows=[self.row('a',1.,'performer1'),self.row('b',1.,'performer1'),self.row('c',0.,'performer2')]
        result=aggregate(rows)[0]
        self.assertEqual(result['distinct_group_count'],2)
        self.assertAlmostEqual(result['beat_20ms_macro_f1'],2/3)
        self.assertEqual(result['beat_20ms_group_macro_f1'],.5)

    def test_unsupported_downbeat_is_not_a_zero_accuracy_measure(self):
        unsupported=self.row('a',.5,method='without_downbeat')
        unsupported['downbeat_supported']=False
        measured=self.row('b',.5,method='wrong_downbeat')
        measured['downbeat_supported']=True
        for label in TOLERANCES:measured['downbeat_'+label+'_f1']=0.
        results={r['method']:r for r in aggregate([unsupported,measured])}
        self.assertIsNone(results['without_downbeat']['downbeat_20ms_macro_f1'])
        self.assertEqual(results['without_downbeat']['downbeat_scored_track_count'],0)
        self.assertEqual(results['without_downbeat']['downbeat_unsupported_tracks'],1)
        self.assertEqual(results['wrong_downbeat']['downbeat_20ms_macro_f1'],0.)
        self.assertEqual(results['wrong_downbeat']['downbeat_scored_track_count'],1)
        self.assertEqual(results['wrong_downbeat']['downbeat_unsupported_tracks'],0)

    def test_models_and_execution_scopes_are_not_pooled(self):
        a=self.row('a',1.);b=self.row('a',0.);c=self.row('a',.5)
        b['model']='beat_transformer';c['scope']='refinement'
        result=aggregate([a,b,c])
        self.assertEqual(len(result),3)
        self.assertEqual({(r['model'],r['scope']) for r in result},
            {('beat_this','core'),('beat_transformer','core'),('beat_this','refinement')})


if __name__=='__main__':unittest.main()
