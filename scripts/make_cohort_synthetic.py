"""Generate invented comparison inputs, including Simpson reversal and late correction."""
import argparse
from pathlib import Path
import extract as e
from make_synthetic import event, session
from build_cohort_contract import FIELDS


def generate(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    e.require(not (root / "comparison-plan.json").exists(), "synthetic_example_already_exists")
    units = []
    specs = [("A", "EASY", 80, 9), ("A", "HARD", 40, 3),
             ("B", "EASY", 90, 3), ("B", "HARD", 50, 9)]
    for group, difficulty, score, n in specs:
        for _ in range(n):
            index = len(units) + 1
            pid, task = f"P-SYN{index:03d}", "T-SYN-01"
            sid = "S-SYN-01"
            intake = root / f"intake-{index:03d}"
            intake.mkdir()
            category = "verification_request" if group == "A" else "goal_specification"
            text = "근거를 확인해 줘." if group == "A" else "CSV 형식으로 정리해 줘."
            events = [event(1, "user", text, "syn-1"),
                event(2, "assistant", "가상의 과제를 처리하겠습니다.", "syn-2"),
                event(3, "tool", "가상 도구 완료.", "syn-3"),
                event(4, "user", "빠진 항목을 수정해 줘.", "syn-4")]
            manifest = {"schema_version": "1.0.0", "data_mode": "synthetic",
                "dataset_namespace": f"SYN-COHORT-{index:03d}", "participant_id": pid, "task_id": task,
                "adapter": "synthetic-export-v1", "model_observation": {"model_id": "synthetic/model",
                    "model_id_confirmed": True, "settings_confirmed": False,
                    "temperature": None, "top_p": None, "context_length": None},
                "sessions": [session(sid, 4)]}
            codings = {"taxonomy_version": e.TAXONOMY_VERSION, "entries": []}
            for row, label in [(1, category), (4, "error_correction")]:
                codings["entries"].append({"source_ref": e.ref(sid, row), "decision": "coded",
                    "categories": [label], "criterion_codes": [e.CRITERIA[label][0]], "ambiguity": None,
                    "evidence": [{"ref": e.ref(sid, row), "start": 0, "end": len(events[row-1]["text"])}], "related_refs": []})
            e.write_json(intake / "manifest.json", manifest)
            e.write_json(intake / "S-SYN-01.json", events)
            e.write_json(intake / "codings.json", codings)
            run = e.build(intake / "manifest.json", intake / "codings.json", root / "derived")
            units.append({"unit_id": f"U-SYN{index:03d}", "participant_id": pid, "task_id": task,
                "approved": True, "run_dirs": [str(run.relative_to(root))], "coding_review": "reviewed",
                "covariates": {**{f: None for f in FIELDS}, "condition_code": group,
                    "task_family": "SYN-TASK", "difficulty_band": difficulty, "model_condition": "SYN-MODEL"},
                "outcome": {"value": score, "reviewed": True, "assessment_ref": f"SYN-RATING-{index:03d}"},
                "pre_outcome_window": [{"session_id": sid, "max_source_index": 3}],
                "window_ref": "SYN-PRE-EVAL"})
    plan = {"analysis_version": "0.2.0", "data_mode": "synthetic", "selection_approved": True,
        "study_id": "SYN-COHORT", "grouping_basis": "pre_analysis",
        "outcome_definition": {"metric_code": "SYN-QUALITY", "rubric_version": "SYN-R1",
            "unit_code": "POINTS", "minimum": 0, "maximum": 100, "higher_is_better": True},
        "group_by": ["condition_code"], "adjust_by": ["difficulty_band"],
        "comparisons": [{"field": "condition_code", "level_a": "A", "level_b": "B"}],
        "bootstrap_replicates": 400, "seed": 20260930, "units": units}
    e.write_json(root / "comparison-plan.json", plan)
    e.write_json(root / "provisional-expectations.json", {"origin": "invented arithmetic fixture, not human validated research",
        "participants": 24, "raw_difference_a_minus_b": 10, "common_strata_difference_a_minus_b": -10,
        "late_error_correction_excluded_from_pre_outcome": True})
    return root / "comparison-plan.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args()
    print(generate(args.out_root))
