import copy
import hashlib
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import extract as e
import cohort as c
from build_cohort_contract import cohort_contract
from make_cohort_synthetic import generate


class CohortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="bionic-cohort-synthetic-")
        cls.root = Path(cls.tmp.name)
        cls.plan_path = generate(cls.root)
        cls.base = e.read_json(cls.plan_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.plan = copy.deepcopy(self.base)
        self.plan["bootstrap_replicates"] = 100

    def analyze(self):
        e.write_json(self.plan_path, self.plan)
        return c.analyze(self.plan_path)

    def test_published_cohort_schema_matches_source(self):
        self.assertEqual(e.read_json(c.CONTRACT), cohort_contract())

    def test_simpson_reversal_detected_with_known_arithmetic(self):
        result = self.analyze()
        comp = result["comparisons"][0]
        self.assertEqual(comp["difference_a_minus_b"], 10)
        self.assertEqual(comp["adjusted"]["difference_a_minus_b"], -10)
        self.assertTrue(comp["reversal_after_adjustment"])
        self.assertEqual(comp["adjusted"]["overlap_units"], 24)
        self.assertEqual(result["causal_identification"], "not_established")

    def test_post_outcome_correction_not_used_as_predictor(self):
        result = self.analyze()
        self.assertTrue(all(u["observed_rates"]["error_correction"] == .5 for u in result["units"]))
        self.assertTrue(all(u["pre_outcome_rates"]["error_correction"] == 0 for u in result["units"]))
        error = next(f for f in result["candidate_factors"] if f["category"] == "error_correction")
        self.assertIsNone(error["difference_a_minus_b"])

    def test_profile_groups_have_outcomes_but_are_post_hoc_not_traits(self):
        profiles = self.analyze()["observed_profile_groups"]
        self.assertEqual(len(profiles), 2)
        self.assertEqual(sorted(p["primary_outcome_mean_equal_participant"] for p in profiles), [60, 70])
        self.assertTrue(all(p["interpretation"].startswith("post_hoc") for p in profiles))

    def test_pattern_condition_alignment_blocks_independent_factor_claim(self):
        result = self.analyze()
        check = next(f for f in result["candidate_factors"] if f["category"] == "verification_request")
        self.assertEqual(check["perfectly_aligned_covariates"], ["condition_code"])
        self.assertEqual(check["within_covariate_independent_contrast"], "not_observed")
        report = c.markdown(result)
        self.assertIn("패턴의 독립적 요인 효과를 분리할 수 없습니다", report)
        self.assertIn("모델 설정 미확인", report)

    def test_unknown_timestamps_do_not_create_duration(self):
        self.assertTrue(all(s["observed_span_seconds"] is None for u in self.analyze()["units"] for s in u["timing"]))

    def test_window_absent_keeps_descriptive_but_excludes_factors(self):
        self.plan["units"][0].update(pre_outcome_window=None, window_ref=None)
        result = self.analyze()
        self.assertTrue(result["units"][0]["primary_eligible"])
        self.assertFalse(result["units"][0]["factor_eligible"])
        self.assertEqual(result["candidate_factors"][0]["eligible_units"], 23)

    def test_missing_outcome_not_zero_and_valid_zero_preserved(self):
        self.plan["units"][0]["outcome"]["value"] = None
        self.plan["units"][1]["outcome"]["value"] = 0
        units = self.analyze()["units"]
        self.assertIsNone(units[0]["outcome_value"])
        self.assertEqual(units[1]["outcome_value"], 0)

    def test_unreviewed_score_and_coding_excluded(self):
        self.plan["units"][0]["coding_review"] = "draft"
        self.plan["units"][1]["outcome"]["reviewed"] = False
        result = self.analyze()
        self.assertFalse(result["units"][0]["primary_eligible"])
        self.assertIsNone(result["units"][1]["outcome_value"])
        self.assertEqual(result["groups"][0]["primary_units"], 11)

    def test_repeated_tasks_equal_participant_weight_not_row_weight(self):
        rows = [{"participant_id": "P-1", "y": 100}] * 10 + [{"participant_id": "P-2", "y": 0}]
        self.assertEqual(c.participant_mean(rows, lambda r: r["y"]), 50)

    def test_cluster_bootstrap_small_sample_suppressed_and_seed_reproducible(self):
        rows = [{"participant_id": f"P-{i}", "g": "A" if i < 5 else "B", "y": i} for i in range(10)]
        select, value = lambda r: r["g"], lambda r: r["y"]
        self.assertEqual(c.bootstrap(rows, select, value, 100, 9), c.bootstrap(rows, select, value, 100, 9))
        self.assertIsNotNone(c.bootstrap(rows, select, value, 100, 9)["interval"])
        self.assertIsNone(c.bootstrap(rows[:8], select, value, 100, 9)["interval"])

    def test_unknown_covariate_not_imputed_or_in_adjusted_cells(self):
        self.plan["units"][0]["covariates"]["difficulty_band"] = None
        adj = self.analyze()["comparisons"][0]["adjusted"]
        self.assertEqual(adj["missing_adjustment_units"], 1)
        self.assertEqual(adj["overlap_units"], 23)

    def test_nonoverlap_adjustment_unavailable(self):
        for unit in self.plan["units"]:
            unit["covariates"]["difficulty_band"] = unit["covariates"]["condition_code"]
        adj = self.analyze()["comparisons"][0]["adjusted"]
        self.assertIsNone(adj["difference_a_minus_b"])
        self.assertEqual(adj["overlap_units"], 0)

    def test_unapproved_plan_rejected_before_any_artifact_read(self):
        self.plan["units"][0]["approved"] = False
        with patch.object(c, "load_run", side_effect=AssertionError("must not read")):
            with self.assertRaises(e.ContractError):
                self.analyze()

    def test_wrong_data_mode_rejected(self):
        self.plan["data_mode"] = "research"
        with self.assertRaisesRegex(e.ContractError, "data_mode_mismatch"):
            self.analyze()

    def test_research_derived_protocol_accepted_using_invented_fixture_only(self):
        self.plan["units"] = self.plan["units"][:1]
        self.plan["data_mode"] = "research"
        unit = self.plan["units"][0]
        with tempfile.TemporaryDirectory(prefix="invented-research-wire-fixture-") as temporary:
            folder = Path(temporary) / "derived"
            shutil.copytree(self.root / unit["run_dirs"][0], folder)
            cov = e.read_json(folder / "coverage.json")
            cov.update(data_mode="research", dataset_namespace="DS-INVENTED-WIRE-FIXTURE")
            e.write_json(folder / "coverage.json", cov)
            (folder / "report.md").write_text("Invented fixture testing research-derived protocol; not actual research data.\n", encoding="utf-8")
            e.write_json(folder / "integrity.json", {"files": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in c.ARTIFACTS}})
            unit["run_dirs"] = [str(folder)]
            self.assertEqual(self.analyze()["data_mode"], "research")

    def test_complete_scope_contradiction_and_modified_artifact_rejected(self):
        self.plan["units"] = self.plan["units"][:1]
        unit = self.plan["units"][0]
        with tempfile.TemporaryDirectory(prefix="invented-bad-output-") as temporary:
            folder = Path(temporary) / "derived"
            shutil.copytree(self.root / unit["run_dirs"][0], folder)
            cov = e.read_json(folder / "coverage.json")
            cov["sessions"][0]["end_verified"] = False
            e.write_json(folder / "coverage.json", cov)
            unit["run_dirs"] = [str(folder)]
            with self.assertRaisesRegex(e.ContractError, "source_integrity"):
                self.analyze()
            e.write_json(folder / "integrity.json", {"files": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in c.ARTIFACTS}})
            with self.assertRaisesRegex(e.ContractError, "complete_session_inconsistent"):
                self.analyze()

    def test_outcome_scale_and_receipt_required(self):
        self.plan["units"][0]["outcome"]["value"] = 101
        with self.assertRaisesRegex(e.ContractError, "outcome_out_of_range"):
            self.analyze()
        self.plan["units"][0]["outcome"].update(value=80, assessment_ref=None)
        with self.assertRaisesRegex(e.ContractError, "receipt_required"):
            self.analyze()

    def test_window_all_sessions_and_receipt_required(self):
        self.plan["units"][0]["pre_outcome_window"][0]["session_id"] = "S-UNKNOWN"
        with self.assertRaisesRegex(e.ContractError, "window_must_cover"):
            self.analyze()
        self.plan["units"][0]["pre_outcome_window"] = self.base["units"][0]["pre_outcome_window"]
        self.plan["units"][0]["window_ref"] = None
        with self.assertRaisesRegex(e.ContractError, "window_receipt"):
            self.analyze()

    def test_identical_rerun_deduplicated_and_source_not_mutated(self):
        unit = self.plan["units"][0]
        original = self.root / unit["run_dirs"][0]
        intake = self.root / "intake-001"
        rerun = e.build(intake / "manifest.json", intake / "codings.json", self.root / "reruns")
        unit["run_dirs"].append(str(rerun.relative_to(self.root)))
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir()}
        result = self.analyze()
        self.assertEqual(result["units"][0]["all_events"], 4)
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir()})

    def test_conflicting_rerun_refused(self):
        intake = self.root / "intake-001"
        codings = e.read_json(intake / "codings.json")
        codings["entries"][0].update(categories=["goal_specification"], criterion_codes=["explicit_goal_or_constraint"])
        path = intake / "alternate-codings.json"
        e.write_json(path, codings)
        rerun = e.build(intake / "manifest.json", path, self.root / "reruns")
        self.plan["units"][0]["run_dirs"].append(str(rerun.relative_to(self.root)))
        with self.assertRaisesRegex(e.ContractError, "unresolved_coding_conflict"):
            self.analyze()

    def test_partial_scope_excluded_primary_retained_sensitivity(self):
        self.plan["units"] = self.plan["units"][:1]
        original = c.load_run
        def partial(*args):
            patterns, cov, hashes = original(*args)
            cov["complete_extraction"] = False
            return patterns, cov, hashes
        with patch.object(c, "load_run", side_effect=partial):
            result = self.analyze()
        self.assertFalse(result["units"][0]["primary_eligible"])
        self.assertEqual(result["units"][0]["outcome_value"], 80)

    def test_reads_only_named_artifacts_no_raw_intake(self):
        original, names = e.read_json, []
        def record(path):
            names.append(Path(path).name)
            return original(path)
        with patch.object(e, "read_json", side_effect=record):
            self.analyze()
        self.assertTrue(set(names) <= {"comparison-plan.json", "cohort-contract.json", "integrity.json", "patterns.json", "coverage.json"})

    def test_new_build_run_has_output_integrity(self):
        e.write_json(self.plan_path, self.plan)
        first = c.build(self.plan_path, self.root / "analysis")
        second = c.build(self.plan_path, self.root / "analysis")
        self.assertNotEqual(first, second)
        self.assertEqual(e.read_json(first / "analysis.json"), e.read_json(second / "analysis.json"))
        for name, digest in e.read_json(first / "integrity.json")["files"].items():
            self.assertEqual(hashlib.sha256((first / name).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
