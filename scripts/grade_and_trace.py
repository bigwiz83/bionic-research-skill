"""Automatically grade numeric task submissions and trace pre-feedback instruction processes."""
import argparse
from collections import defaultdict
import hashlib
import math
from pathlib import Path
import re
import sys

import extract as e
import compare_processes as p
import cohort as c

VERSION = "0.3.0"
SCAFFOLDS = {
    "goal_specification": "목표 값, 집계 단위, 포함·제외 조건과 요구 출력 형식을 먼저 명시한다.",
    "task_decomposition": "작업을 단계로 나누고 각 단계의 입력·산출물과 진행 순서를 지시한다.",
    "delegation_control": "AI가 자율 처리할 범위와 사용자 확인이 필요한 경계를 명시한다.",
    "verification_request": "집계 근거와 중간 결과를 대조하고 확인 가능한 검증을 요청한다.",
    "error_correction": "관찰된 누락·오류를 구체적으로 지적하고 수정 후 다시 확인하도록 요청한다.",
    "reuse_resume": "이전에 확인한 결과와 남은 작업을 구분해 재사용·재개하도록 지시한다.",
    "data_structure_inquiry": "집계 전 자료의 구조와 필요한 항목의 위치·의미를 확인하도록 요청한다.",
}


def keys(value, expected, error):
    e.require(isinstance(value, dict) and set(value) == set(expected), error)


def code(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,63}", value) is not None


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def answer_key(path):
    value = e.read_json(path)
    keys(value, ["answer_key_version", "answer_key_id", "tasks"], "grade_answer_key_fields")
    e.require(value["answer_key_version"] == "1.0.0" and code(value["answer_key_id"]) and isinstance(value["tasks"], list) and value["tasks"], "grade_answer_key_header")
    tasks = {}
    for task in value["tasks"]:
        keys(task, ["task_id", "metrics"], "grade_task_fields")
        e.require(code(task["task_id"]) and task["task_id"] not in tasks and isinstance(task["metrics"], list) and task["metrics"], "grade_task_definition")
        seen = set()
        for metric in task["metrics"]:
            keys(metric, ["metric_id", "expected", "near_tolerance", "weight", "error_scale"], "grade_metric_fields")
            e.require(code(metric["metric_id"]) and metric["metric_id"] not in seen, "grade_metric_id")
            seen.add(metric["metric_id"])
            e.require(type(metric["expected"]) is int and metric["expected"] >= 0 and type(metric["near_tolerance"]) is int and metric["near_tolerance"] >= 0, "grade_count_definition")
            e.require(finite(metric["weight"]) and metric["weight"] > 0 and finite(metric["error_scale"]) and metric["error_scale"] > 0, "grade_weight_scale")
        tasks[task["task_id"]] = task["metrics"]
    return value, tasks


def submission(path):
    value = e.read_json(path)
    keys(value, ["result_schema_version", "result_id", "participant_id", "task_id", "values", "pre_feedback_window"], "grade_result_fields")
    e.require(value["result_schema_version"] == "1.0.0" and all(code(value[k]) for k in ["result_id", "participant_id", "task_id"]), "grade_result_header")
    e.require(isinstance(value["values"], dict) and value["values"] and all(code(k) and (v is None or type(v) is int and v >= 0) for k, v in value["values"].items()), "grade_submission_count_values")
    window = value["pre_feedback_window"]
    if window is not None:
        keys(window, ["receipt_ref", "cutoffs"], "grade_window_fields")
        e.require(code(window["receipt_ref"]) and isinstance(window["cutoffs"], list) and window["cutoffs"], "grade_window_receipt")
        seen = set()
        for cutoff in window["cutoffs"]:
            keys(cutoff, ["dataset_namespace", "session_id", "max_source_index"], "grade_cutoff_fields")
            e.require(code(cutoff["dataset_namespace"]) and code(cutoff["session_id"]) and type(cutoff["max_source_index"]) is int and cutoff["max_source_index"] >= 0, "grade_cutoff_value")
            key = (cutoff["dataset_namespace"], cutoff["session_id"])
            e.require(key not in seen, "grade_duplicate_cutoff")
            seen.add(key)
    return value


def grade(result, metrics):
    e.require(set(result["values"]) == {m["metric_id"] for m in metrics}, "grade_metric_set_mismatch")
    rows = []
    for metric in metrics:
        submitted = result["values"][metric["metric_id"]]
        error = abs(submitted-metric["expected"]) if submitted is not None else None
        rows.append({**metric, "submitted": submitted, "absolute_error": error,
            "exact": error == 0 if error is not None else None,
            "within_near_tolerance": error <= metric["near_tolerance"] if error is not None else None,
            "closeness_score": 100 * max(0, 1-error/metric["error_scale"]) if error is not None else None})
    if any(row["submitted"] is None for row in rows):
        label, score = "unavailable", None
    else:
        label = "correct" if all(row["exact"] for row in rows) else "near" if all(row["within_near_tolerance"] for row in rows) else "incorrect"
        score = sum(row["weight"]*row["closeness_score"] for row in rows)/sum(row["weight"] for row in rows)
    return {"answer_class": label, "closeness_score": score, "metrics": rows,
        "scoring_rule": "weighted_100_times_max_zero_one_minus_absolute_error_over_registered_scale",
        "meaning": "provided_numeric_submission_vs_registered_key_not_source_correctness_or_clinical_validation"}


def analyze(run_dirs, key_path, max_pairs=500):
    structure = p.analyze(run_dirs, max_pairs)
    key, tasks = answer_key(key_path)
    results, result_hashes = {}, []
    for folder, source in zip(run_dirs, structure["source_runs"]):
        path = Path(folder)/"task-result.json"
        if not path.is_file():
            continue
        result = submission(path)
        owner = (result["participant_id"], result["task_id"])
        e.require(owner == (source["participant_id"], source["task_id"]), "grade_submission_owner_mismatch")
        e.require(owner not in results or results[owner] == result, "grade_conflicting_final_results_select_submission")
        results[owner] = result
        result_hashes.append({"run_id": source["run_id"], "result_id": result["result_id"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    grades, traces = [], []
    for unit in structure["units"]:
        owner = (unit["participant_id"], unit["task_id"])
        result = results.get(owner)
        if not result or unit["task_id"] not in tasks:
            assessment = {"answer_class": "unavailable", "closeness_score": None, "metrics": [],
                "reason": "submission_or_registered_task_key_missing"}
        else:
            assessment = grade(result, tasks[unit["task_id"]])
        grades.append({"unit_id": unit["unit_id"], "participant_id": owner[0], "task_id": owner[1], **assessment})
        processes = [x for x in structure["processes"] if x["process_id"] in unit["process_ids"]]
        limits = {(x["dataset_namespace"], x["session_id"]): x["max_source_index"] for x in result["pre_feedback_window"]["cutoffs"]} if result and result["pre_feedback_window"] else None
        if limits is not None:
            e.require(set(limits) == {(x["dataset_namespace"], x["session_id"]) for x in processes}, "grade_feedback_window_scope_mismatch")
        for process in processes:
            modules = process["modules"]
            if limits is not None:
                limit = limits[(process["dataset_namespace"], process["session_id"])]
                e.require(limit <= (process["known_total_events"] if process["known_total_events"] is not None else process["max_observed_source_index"]), "grade_feedback_cutoff_outside_known_scope")
                modules = [m for m in modules if int(m["user_ref"].split("row-")[-1]) <= limit]
            sequence = [m["state"] for m in modules]
            traces.append({"unit_id": unit["unit_id"], "participant_id": owner[0], "task_id": owner[1],
                "process_id": process["process_id"], "answer_class": assessment["answer_class"],
                "closeness_score": assessment["closeness_score"], "sequence": sequence,
                "module_ids": [m["module_id"] for m in modules], "order_basis": process["order_basis"],
                "process_quality": process["comparison_quality"],
                "window_basis": "declared_before_answer_feedback" if limits is not None else "whole_observed_process_no_feedback_boundary",
                "intervention_candidate_eligible": limits is not None and bool(sequence) and process["comparison_quality"].startswith("complete") and all(s not in {"UNRESOLVED", "UNCLASSIFIED"} for s in sequence) and assessment["answer_class"] in {"correct", "near"}})
    groups = []
    for task in sorted({u["task_id"] for u in grades}):
        for label in ["correct", "near", "incorrect", "unavailable"]:
            members = [g for g in grades if g["task_id"] == task and g["answer_class"] == label]
            relevant = [t for t in traces if t["task_id"] == task and t["answer_class"] == label]
            groups.append({"task_id": task, "answer_class": label, "units": len(members),
                "participants": len({g["participant_id"] for g in members}), "unit_ids": [g["unit_id"] for g in members],
                "closeness_score_equal_participant": c.participant_mean(members, lambda g: g["closeness_score"]),
                "process_ids": [t["process_id"] for t in relevant],
                "pattern_presence_participants": {cat: len({t["participant_id"] for t in relevant if any(cat in s.split("+") for s in t["sequence"])}) for cat in e.CRITERIA}})
    patterns = defaultdict(list)
    for trace in traces:
        if trace["intervention_candidate_eligible"]:
            patterns[(trace["task_id"], tuple(trace["sequence"]))].append(trace)
    candidates = []
    for (task, sequence), supporting in sorted(patterns.items()):
        peer = [t for t in traces if t["task_id"] == task and tuple(t["sequence"]) == sequence and t["window_basis"] == "declared_before_answer_feedback"]
        candidates.append({"strategy_id": "IS-"+e.digest([task,list(sequence)])[:16].upper(), "task_id": task,
            "observed_sequence": list(sequence), "supporting_participants": len({t["participant_id"] for t in supporting}),
            "observed_by_answer_class": {label: len({t["participant_id"] for t in peer if t["answer_class"] == label}) for label in ["correct","near","incorrect","unavailable"]},
            "complete_process_by_answer_class": {label: len({t["participant_id"] for t in peer if t["answer_class"] == label and t["process_quality"].startswith("complete")}) for label in ["correct","near","incorrect","unavailable"]},
            "evidence_process_ids": [t["process_id"] for t in supporting],
            "instruction_scaffold": [{"step": i+1, "simultaneous_module_bundle": token.split("+"),
                "step_type": "conditional_on_observed_error" if "error_correction" in token.split("+") else "instruction_step",
                "instructions": [SCAFFOLDS[cat] for cat in token.split("+")]} for i, token in enumerate(sequence)],
            "application_conditions": ["same_defined_task_and_numeric_target", "answer_key_hidden_during_task", "source_coding_and_strategy_review_needed"],
            "hypothesis_to_test": "Providing this modular instruction process may improve correctness or closeness on the defined task; untested.",
            "template_origin": "taxonomy_based_scaffold_not_verbatim_successful_prompt",
            "status": "draft_intervention_strategy_effect_not_validated",
            "required_next_validation": "new_participants_comparison_with_predefined_answer_key_and_independent_outcome_evaluation"})
    return {"analysis_version": VERSION, "analysis_mode": "automatic_numeric_grading_and_process_trace",
        "structure": structure, "grades": grades, "answer_groups": groups, "pre_feedback_traces": traces,
        "intervention_strategies": candidates, "answer_key_id": key["answer_key_id"],
        "answer_key_sha256": hashlib.sha256(Path(key_path).read_bytes()).hexdigest(),
        "submission_provenance": result_hashes, "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limits": ["registered_key_and_submission_values_not_independently_verified",
            "no_patient_file_or_raw_source_read", "feedback_cutoffs_are_asserted_not_independently_verified",
            "observed_successful_processes_not_causal_effects", "no_generalization_to_new_participants_established",
            "no_automatic_deployment_or_assignment_of_interventions"]}


def report(value):
    lines = ["# 자동 정답 판정·지시 과정 역추적", "", "과제별 정답 기준과 제출된 숫자 결과를 대조했습니다. 참여자별 점수표나 배정표는 요구하지 않습니다.",
        "현재 판정기는 비음수 정수 건수만 지원하며 문서의 의미·임상적 타당성·원자료 집계를 자동 검증하지 않습니다.", "",
        "| 참여자 | 과제 | 정답 판정 | 등록 기준의 근접 점수 |", "|---|---|---|---:|"]
    label_names = {"correct":"정답", "near":"근접", "incorrect":"오답", "unavailable":"확인 불가"}
    for row in value["grades"]:
        score = f"{row['closeness_score']:.4g}" if row["closeness_score"] is not None else "확인 불가"
        lines.append(f"| {row['participant_id']} | {row['task_id']} | {label_names[row['answer_class']]} | {score} |")
    lines += ["", "## 판정 그룹별 지시 과정", "", "| 참여자 | 판정 | 관찰 모듈 순서 | 분석 구간 |", "|---|---|---|---|"]
    for trace in value["pre_feedback_traces"]:
        lines.append(f"| {trace['participant_id']} | {label_names[trace['answer_class']]} | {' → '.join(p.readable(s) for s in trace['sequence']) or '미확인'} | {trace['window_basis']} |")
    lines += ["", "## 인터벤션 전략 초안", "", "아래는 관찰된 정답·근접 과정의 분류 모듈을 단계·지시 틀·적용 조건·검증 가설로 구조화한 전략 초안입니다. 원문 프롬프트를 복제한 것이 아니며 효과가 검증되지 않았습니다.", ""]
    for strategy in value["intervention_strategies"]:
        lines.append(f"- {strategy['strategy_id']}: {' → '.join(p.readable(s) for s in strategy['observed_sequence'])}; 정답·근접 근거 참여자 {strategy['supporting_participants']}명; 같은 순서의 완전 과정별 판정 {strategy['complete_process_by_answer_class']}; 부분 과정 포함 판정 {strategy['observed_by_answer_class']}.")
        for step in strategy["instruction_scaffold"]:
            lines.append(f"  - 단계 {step['step']} ({step['step_type']}): {' '.join(step['instructions'])}")
    if not value["intervention_strategies"]:
        lines.append("전략 초안 없음: 정답·근접 자료, 완전한 코딩 또는 정답 피드백 이전 구간이 확인되지 않았습니다.")
    lines += ["", "정답 기준은 연구자가 과제별로 한 번 등록하고 과제 수행자에게 사전에 노출하지 않습니다. 과제의 집계 정의와 정답 기준이 잘못되면 자동 판정도 잘못됩니다.",
        "정답 피드백 이전 경계가 없으면 전체 관찰 과정으로 표시하며 인터벤션 후보에서 제외합니다. 모듈 간 연결은 순서 관찰이며 성공 원인이나 사람의 이해를 확정하지 않습니다.",
        "새 참여자에게 적용하기 전 전략을 연구진이 검토하고, 사전에 정한 비교 조건과 같은 정답 기준으로 효과·재현성을 별도로 평가해야 합니다. 이 도구는 사람에게 인터벤션을 자동 배정하거나 실행하지 않습니다.", ""]
    return "\n".join(lines)


def build(run_dirs, key_path, out_root, max_pairs=500):
    folder = e.new_run(out_root)
    try:
        value = analyze(run_dirs, key_path, max_pairs)
        e.write_json(folder/"graded-processes.json", value)
        e.write_json(folder/"intervention-strategies.json", {"analysis_version": VERSION,"strategies":value["intervention_strategies"],"effect_validated":False})
        p.write_csv(folder/"grades.csv", value["grades"])
        (folder/"report.md").write_text(report(value), encoding="utf-8")
        names = ["graded-processes.json","intervention-strategies.json","grades.csv","report.md"]
        e.write_json(folder/"integrity.json", {"files":{name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in names}})
    except (e.ContractError,OSError) as error:
        e.write_json(folder/"failure.json", {"status":"failed","error_code":str(error) if isinstance(error,e.ContractError) else "filesystem_error"})
        raise
    return folder


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs",nargs="+",required=True)
    parser.add_argument("--answer-key",required=True)
    parser.add_argument("--out-root",default=str(e.ROOT/"runs"))
    parser.add_argument("--max-process-pairs",type=int,default=500)
    args=parser.parse_args()
    try:
        print(build(args.runs,args.answer_key,args.out_root,args.max_process_pairs))
    except (e.ContractError,OSError):
        print("FAILED: inspect new run failure.json",file=sys.stderr)
        raise SystemExit(1)
