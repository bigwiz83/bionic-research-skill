import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import extract as e
import structure_session as s
import grade_and_trace as g
import compare_processes as p
from make_process_synthetic import generate


class IndividualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="bionic-individual-synthetic-")
        cls.root=Path(cls.tmp.name)
        cls.runs,cls.key=generate(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def detail_document(self):
        value=s.analyze([self.runs[0]])
        doc=value["instruction_details"]
        for row in doc["entries"]:
            action=next(a for a in value["observed_actions"] if a["event_id"]==row["event_id"])
            row["observed_text_length"]=max(span["end"] for span in action["evidence"])
            row["fields"]={field:[] for field in s.DETAIL_FIELDS}
            row["fields"]["goal"]=[{"value":"합성 관찰 지시의 추상 구조","evidence":action["evidence"]}]
        path=self.root/"synthetic-details.json"
        e.write_json(path,doc)
        return path,doc

    def test_single_person_no_grading_grouping_or_strategy(self):
        with patch.object(g,"grade",side_effect=AssertionError("grading forbidden")),patch.object(g,"answer_key",side_effect=AssertionError("answer key forbidden")):
            value=s.analyze([self.runs[0]])
        self.assertFalse(value["grouping_performed"])
        self.assertFalse(value["grading_performed"])
        self.assertFalse(value["intervention_strategy_development_performed"])
        self.assertNotIn("profile_groups",value)

    def test_multi_participant_input_refused(self):
        with self.assertRaisesRegex(e.ContractError,"one_participant"):
            s.analyze(self.runs[:2])

    def test_individual_helper_exits_before_profile_and_process_grouping(self):
        helper=p.analyze([self.runs[0]],max_pairs=0,individual_only=True)
        self.assertFalse(helper["comparison_computation_performed"])
        self.assertNotIn("profile_groups",helper)
        self.assertNotIn("sequence_groups",helper)
        self.assertNotIn("process_comparisons",helper)
        self.assertTrue(helper["processes"][0]["modules"])

    def test_unsupplied_detail_unknown_not_claimed_extracted(self):
        value=s.analyze([self.runs[0]])
        self.assertEqual(value["detail_status"],"not_extracted_fields_unknown")
        self.assertTrue(all(v is None for row in value["instruction_details"]["entries"] for v in row["fields"].values()))

    def test_detail_scope_and_evidence_accepted(self):
        path,doc=self.detail_document()
        value=s.analyze([self.runs[0]],path)
        self.assertEqual(value["instruction_details"],doc)
        self.assertNotEqual(value["detail_status"],"verified")

    def test_own_evidence_bounds_and_missing_event_rejected(self):
        path,doc=self.detail_document()
        bad=copy.deepcopy(doc)
        bad["entries"][0]["fields"]["goal"][0]["evidence"][0]["end"]=99999
        e.write_json(path,bad)
        with self.assertRaisesRegex(e.ContractError,"own_span_bounds"):
            s.analyze([self.runs[0]],path)
        doc["entries"].pop()
        e.write_json(path,doc)
        with self.assertRaisesRegex(e.ContractError,"exact_user_scope"):
            s.analyze([self.runs[0]],path)

    def test_final_numeric_result_preserved_without_correctness(self):
        value=s.analyze([self.runs[0]])
        self.assertEqual(value["observed_task_results"][0]["result"]["values"]["TARGET_COUNT"],10)
        self.assertNotIn("answer_class",value["observed_task_results"][0])
        self.assertTrue(value["coverage"])
        self.assertTrue(value["processes"][0]["modules"])

    def test_missing_result_stays_missing_not_failure_score(self):
        value=s.analyze([self.runs[6]])
        self.assertEqual(value["observed_task_results"],[])
        self.assertEqual(len(value["missing_task_result_units"]),1)

    def test_reads_only_selected_derivatives_and_detail_no_answer_key_or_raw(self):
        path,_=self.detail_document()
        original,names=e.read_json,[]
        def track(file):
            names.append(Path(file).name)
            return original(file)
        with patch.object(e,"read_json",side_effect=track):
            s.analyze([self.runs[0]],path)
        self.assertTrue(set(names)<={"coverage.json","patterns.json","integrity.json","cohort-contract.json","task-result.json","synthetic-details.json"})


if __name__=="__main__":
    unittest.main()
