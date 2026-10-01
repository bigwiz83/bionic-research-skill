"""Separate derived-data comparison contract; raw intake contract stays unchanged."""
import copy
from build_contract import contract, obj, string, enum, arr, nullable, reference
from extract import ROOT, write_json

FIELDS = ["condition_code", "task_family", "difficulty_band", "experience_band",
          "model_condition", "prior_training", "task_order_band"]


def cohort_contract():
    result = copy.deepcopy(contract())
    result["$id"] = "urn:bionic-research-skill:cohort:0.2.0"
    result["title"] = "Approved derived outputs and cohort comparison plan"
    defs = result["$defs"]
    for name in ["patterns", "coverage"]:
        defs[name]["properties"]["skill_version"] = enum(["0.1.0", "0.2.0"])
    defs["coverage"]["properties"]["data_mode"] = enum(["synthetic", "research"])
    defs["coverage"]["properties"]["dataset_namespace"] = string(r"(?:SYN|DS)-[A-Z0-9-]{1,64}")
    code = string(r"[A-Z0-9][A-Z0-9_-]{0,47}")
    number = {"type": "number"}
    defs["outcome"] = obj({"value": nullable(number), "reviewed": {"type": "boolean"},
        "assessment_ref": nullable(code)})
    defs["cutoff"] = obj({"session_id": string(r"S-[A-Z0-9-]{1,48}"),
        "max_source_index": {"type": "integer", "minimum": 0}})
    defs["cohort_unit"] = obj({"unit_id": string(r"U-[A-Z0-9-]{1,48}"),
        "participant_id": string(r"P-[A-Z0-9-]{1,48}"), "task_id": string(r"T-[A-Z0-9-]{1,48}"),
        "approved": {"const": True}, "run_dirs": arr(string(), 1, True),
        "coding_review": enum(["draft", "reviewed"]),
        "covariates": obj({key: nullable(code) for key in FIELDS}),
        "outcome": reference("outcome"),
        "pre_outcome_window": nullable(arr(reference("cutoff"), 1)),
        "window_ref": nullable(code)})
    defs["comparison"] = obj({"field": enum(FIELDS), "level_a": code, "level_b": code})
    defs["cohort_plan"] = obj({"analysis_version": {"const": "0.2.0"},
        "data_mode": enum(["synthetic", "research"]), "selection_approved": {"const": True},
        "study_id": code, "grouping_basis": enum(["pre_analysis", "exploratory"]),
        "outcome_definition": obj({"metric_code": code, "rubric_version": code, "unit_code": code,
            "minimum": number, "maximum": number, "higher_is_better": {"type": "boolean"}}),
        "group_by": arr(enum(FIELDS), 1, True), "adjust_by": arr(enum(FIELDS), 0, True),
        "comparisons": arr(reference("comparison"), 0, True),
        "bootstrap_replicates": {"type": "integer", "minimum": 100, "maximum": 10000},
        "seed": {"type": "integer", "minimum": 0}, "units": arr(reference("cohort_unit"), 1)})
    return result


if __name__ == "__main__":
    write_json(ROOT / "schemas/cohort-contract.json", cohort_contract())
