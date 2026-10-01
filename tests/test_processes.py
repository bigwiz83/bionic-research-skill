import copy
import hashlib
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import extract as e
import compare_processes as p
import grade_and_trace as g
from make_process_synthetic import generate


class ProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="bionic-process-synthetic-")
        cls.root=Path(cls.tmp.name)
        cls.runs,cls.key=generate(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_pattern_only_needs_no_plan_score_table_or_answer_key(self):
        result=p.analyze(self.runs)
        self.assertEqual(result["analysis_mode"],"pattern_process_only")
        self.assertFalse(result["score_analysis_performed"])
        self.assertEqual(len(result["units"]),8)
        self.assertFalse(any("outcome" in u for u in result["units"]))

    def test_same_profile_different_order_separately_identified(self):
        result=p.analyze([self.runs[0],self.runs[4]])
        self.assertEqual(len(result["profile_groups"]),1)
        self.assertEqual(len(result["sequence_groups"]),2)
        self.assertGreater(result["process_comparisons"][0]["edit_distance"],0)

    def test_ai_tool_following_events_not_counted_as_user_verification(self):
        result=p.analyze([self.runs[3]])
        process=result["processes"][0]
        self.assertEqual(process["modules"][0]["state"],"delegation_control")
        self.assertEqual(process["modules"][0]["following_actor_counts"],{"assistant":1,"tool":1})
        self.assertEqual(process["modules"][0]["observed_tool_failures"],1)
        self.assertNotIn("verification_request",result["units"][0]["profile"])

    def test_multi_label_module_has_no_invented_within_utterance_order(self):
        action={"content_complete":True,"decision":"coded","categories":["verification_request","goal_specification"]}
        self.assertEqual(p.state(action),"goal_specification+verification_request")
        self.assertEqual(p.align([p.state(action)],[p.state(action)])["edit_distance"],0)

    def test_ambiguous_not_false_absence(self):
        self.assertEqual(p.state({"content_complete":True,"decision":"deferred","categories":[]}),"UNRESOLVED")

    def test_no_cross_session_stitching(self):
        import cohort
        original=cohort.load_run
        def two_sessions(folder,mode):
            patterns,cov,hashes=original(folder,mode)
            patterns,cov=copy.deepcopy(patterns),copy.deepcopy(cov)
            split=6
            extra=copy.deepcopy(cov["sessions"][0])
            extra["session_id"]="S-SECOND"
            cov["sessions"].append(extra)
            for a in patterns["actions"]:
                if a["source_index"]>split:
                    a["session_id"]="S-SECOND"
                    a["source_ref"]=e.ref("S-SECOND",a["source_index"])
                    for span in a["evidence"]:
                        span["ref"]=a["source_ref"]
            return patterns,cov,hashes
        with patch.object(cohort,"load_run",side_effect=two_sessions):
            result=p.analyze([self.runs[0]])
        self.assertEqual(len(result["processes"]),2)
        self.assertEqual(sum(len(x["transitions"]) for x in result["processes"]),3)

    def test_unknown_time_and_source_order_not_fabricated(self):
        for process in p.analyze(self.runs)["processes"]:
            self.assertEqual(process["order_basis"],"normalized_package_order")
            self.assertTrue(all(m["elapsed_seconds"] is None for m in process["modules"]))

    def test_repeated_modules_and_pair_limit_are_reported(self):
        result=p.analyze(self.runs,max_pairs=1)
        self.assertEqual(result["processes"][3]["adjacent_repeat_count"],2)
        self.assertEqual(result["pair_coverage"],{"eligible_pairs":28,"included_pairs":1,"omitted_by_limit":27,"max_pairs":1})

    def test_auto_grading_correct_near_incorrect_and_missing(self):
        value=g.analyze(self.runs,self.key)
        self.assertEqual([r["answer_class"] for r in value["grades"]],["correct","correct","near","incorrect","correct","incorrect","unavailable","correct"])
        self.assertEqual(value["grades"][2]["closeness_score"],90)
        self.assertEqual(value["grades"][3]["closeness_score"],60)
        self.assertIsNone(value["grades"][6]["closeness_score"])

    def test_strategy_traces_exclude_post_answer_feedback_modules(self):
        value=g.analyze(self.runs,self.key)
        first=value["pre_feedback_traces"][0]
        self.assertEqual(len(first["sequence"]),4)
        self.assertNotIn("error_correction",first["sequence"])
        self.assertTrue(value["intervention_strategies"])
        self.assertTrue(all(s["status"]=="draft_intervention_strategy_effect_not_validated" for s in value["intervention_strategies"]))

    def test_successful_process_also_in_wrong_group_not_claimed_causal(self):
        value=g.analyze(self.runs,self.key)
        sequence=value["pre_feedback_traces"][0]["sequence"]
        strategy=next(s for s in value["intervention_strategies"] if s["observed_sequence"]==sequence)
        self.assertEqual(strategy["observed_by_answer_class"]["incorrect"],1)
        self.assertEqual(strategy["observed_by_answer_class"]["correct"],2)
        self.assertEqual(strategy["complete_process_by_answer_class"]["correct"],1)
        self.assertNotEqual(strategy["status"],"validated")

    def test_partial_success_not_eligible_for_strategy_evidence(self):
        value=g.analyze(self.runs,self.key)
        self.assertEqual(value["grades"][-1]["answer_class"],"correct")
        self.assertFalse(value["pre_feedback_traces"][-1]["intervention_candidate_eligible"])

    def test_correction_step_is_conditional_not_required_mistake(self):
        strategies=g.analyze(self.runs,self.key)["intervention_strategies"]
        steps=[step for s in strategies for step in s["instruction_scaffold"] if "error_correction" in step["simultaneous_module_bundle"]]
        self.assertTrue(steps)
        self.assertTrue(all(s["step_type"]=="conditional_on_observed_error" for s in steps))

    def test_missing_pre_feedback_window_disables_strategy_but_keeps_trace(self):
        original=g.submission
        with patch.object(g,"submission",side_effect=lambda path:{**original(path),"pre_feedback_window":None}):
            result=g.analyze(self.runs,self.key)
        self.assertEqual(result["intervention_strategies"],[])
        self.assertEqual(len(result["grades"]),8)

    def test_zero_answer_and_missing_value_handled_separately(self):
        metric={"metric_id":"COUNT","expected":0,"near_tolerance":0,"weight":1,"error_scale":1}
        self.assertEqual(g.grade({"values":{"COUNT":0}},[metric])["answer_class"],"correct")
        self.assertEqual(g.grade({"values":{"COUNT":None}},[metric])["answer_class"],"unavailable")

    def test_unknown_metrics_negative_or_fractional_counts_rejected(self):
        metric={"metric_id":"COUNT","expected":5,"near_tolerance":1,"weight":1,"error_scale":5}
        with self.assertRaises(e.ContractError):
            g.grade({"values":{"OTHER":5}},[metric])
        value=e.read_json(Path(self.runs[0])/"task-result.json")
        for wrong in [-1,2.5,True]:
            with tempfile.TemporaryDirectory() as temporary:
                path=Path(temporary)/"task-result.json"
                value["values"]["TARGET_COUNT"]=wrong
                e.write_json(path,value)
                with self.assertRaises(e.ContractError):
                    g.submission(path)

    def test_invalid_feedback_cutoff_rejected(self):
        original=g.submission
        def outside(path):
            value=original(path)
            value["pre_feedback_window"]["cutoffs"][0]["max_source_index"]=9999
            return value
        with patch.object(g,"submission",side_effect=outside):
            with self.assertRaisesRegex(e.ContractError,"cutoff_outside"):
                g.analyze(self.runs,self.key)

    def test_only_selected_derived_and_registered_key_files_read(self):
        original,names=e.read_json,[]
        def track(path):
            names.append(Path(path).name)
            return original(path)
        with patch.object(e,"read_json",side_effect=track):
            g.analyze(self.runs,self.key)
        self.assertTrue(set(names)<={"coverage.json","patterns.json","integrity.json","cohort-contract.json","task-result.json","answer-key.json"})

    def test_outputs_are_immutable_runs_with_integrity(self):
        first=p.build(self.runs,self.root/"results")
        second=p.build(self.runs,self.root/"results")
        self.assertNotEqual(first,second)
        self.assertEqual(e.read_json(first/"processes.json"),e.read_json(second/"processes.json"))
        for name,digest in e.read_json(first/"integrity.json")["files"].items():
            self.assertEqual(hashlib.sha256((first/name).read_bytes()).hexdigest(),digest)
        graded=g.build(self.runs,self.key,self.root/"graded")
        for name,digest in e.read_json(graded/"integrity.json")["files"].items():
            self.assertEqual(hashlib.sha256((graded/name).read_bytes()).hexdigest(),digest)

    def test_cohort_cli_accepts_selected_runs_without_json_plan(self):
        result=subprocess.run([sys.executable,str(ROOT/"scripts/cohort.py"),"--runs",*self.runs[:2],
            "--out-root",str(self.root/"cli-results")],capture_output=True,text=True,check=True)
        folder=Path(result.stdout.strip())
        self.assertTrue((folder/"processes.json").is_file())
        self.assertFalse(e.read_json(folder/"comparison-inputs.json")["external_tables_required"])


if __name__=="__main__":
    unittest.main()
