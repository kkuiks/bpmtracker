"""Input-boundary regression guards; these tests do not score any model."""
from copy import deepcopy
import unittest
from run_joint_guide_pilot import validate_payload


def payload():
    return {'schema_version':1, 'id':'opaque_example',
        'input_audio':{'path':'example.wav','sha256':'0'*64},
        'guide':{'bpm':160.,'approximate':True,'scope':'first_stable_section',
                 'source':'actual_human_external_Tap_Tempo','raw_tap_timestamps':None}}


class PilotInputTests(unittest.TestCase):
    def test_scalar_input_has_no_assumed_meter_or_note_unit(self):
        value=payload(); before=deepcopy(value)
        self.assertEqual(validate_payload(value),160.)
        self.assertEqual(value,before)
        value['guide']=None
        self.assertIsNone(validate_payload(value))

    def test_reference_interpretation_cannot_be_smuggled_into_guide(self):
        for key,value in [('meter',[6,8]),('note_unit_quarters',.5),
                          ('stable_window_seconds',[0,8]),('bar_anchor_seconds',0)]:
            p=payload();p['guide'][key]=value
            with self.assertRaises(ValueError):validate_payload(p)

    def test_reference_file_and_invalid_numeric_inputs_rejected(self):
        p=payload();p['reference_path']='secret-label.json'
        with self.assertRaises(ValueError):validate_payload(p)
        for value in (True,0,-1,float('nan'),float('inf')):
            p=payload();p['guide']['bpm']=value
            with self.assertRaises(ValueError):validate_payload(p)

    def test_output_identity_cannot_escape_or_replace_evidence_directory(self):
        for case_id in ('../reference','a/b','/absolute','a..b'):
            p=payload();p['id']=case_id
            with self.assertRaises(ValueError):validate_payload(p)


if __name__=='__main__':unittest.main()
