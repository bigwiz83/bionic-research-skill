"""Modularize and compare selected derived instruction records, without score tables."""
from collections import Counter, defaultdict
import argparse
import csv
import hashlib
from itertools import combinations
from pathlib import Path
import sys

import extract as e
import cohort as c

VERSION = "0.3.0"
KINDS = {label: kind for kind, label in e.OBSERVATIONS.items()}


def state(action):
    if not action["content_complete"] or action["decision"] == "deferred":
        return "UNRESOLVED"
    if action["decision"] != "coded" or not action["categories"]:
        return "UNCLASSIFIED"
    # Simultaneous categories are one bundle, never an invented within-utterance order.
    return "+".join(category for category in e.CRITERIA if category in action["categories"])


def readable(token):
    if token == "UNRESOLVED":
        return "보류·불완전"
    if token == "UNCLASSIFIED":
        return "미분류"
    return " + ".join(e.CRITERIA[category][1] for category in token.split("+"))


def align(left, right):
    """Unit-cost edit alignment on bundled user-module states, not duration/quality."""
    table = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i in range(len(left) + 1):
        table[i][0] = i
    for j in range(len(right) + 1):
        table[0][j] = j
    for i, a in enumerate(left, 1):
        for j, b in enumerate(right, 1):
            table[i][j] = min(table[i-1][j]+1, table[i][j-1]+1, table[i-1][j-1]+(a != b))
    i, j, edits = len(left), len(right), []
    while i or j:
        if i and j and table[i][j] == table[i-1][j-1]+(left[i-1] != right[j-1]):
            edits.append({"operation": "same" if left[i-1] == right[j-1] else "replace",
                "left_index": i-1, "right_index": j-1, "left": left[i-1], "right": right[j-1]})
            i, j = i-1, j-1
        elif i and table[i][j] == table[i-1][j]+1:
            edits.append({"operation": "left_only", "left_index": i-1, "right_index": None, "left": left[i-1], "right": None})
            i -= 1
        else:
            edits.append({"operation": "right_only", "left_index": None, "right_index": j-1, "left": None, "right": right[j-1]})
            j -= 1
    return {"edit_distance": table[-1][-1],
        "normalized_edit_distance": table[-1][-1] / max(len(left), len(right)) if left or right else 0,
        "alignment": list(reversed(edits)), "meaning": "descriptive_sequence_difference_not_skill_or_performance_score"}


def session_modules(process_id, rows, coverage):
    rows = sorted(rows, key=lambda a: a["source_index"])
    order = "source_sequence" if rows and all(a["source_sequence"] is not None for a in rows) and all(
        a["source_sequence"] < b["source_sequence"] for a, b in zip(rows, rows[1:])) else "normalized_package_order"
    anchors = [i for i, a in enumerate(rows) if a["actor"] == "user"]
    modules = []
    for ordinal, start in enumerate(anchors):
        end = anchors[ordinal+1] if ordinal+1 < len(anchors) else len(rows)
        user, following = rows[start], rows[start+1:end]
        module_id = f"{process_id}/M-{ordinal+1:04d}"
        modules.append({"module_id": module_id, "ordinal": ordinal+1,
            "state": state(user), "categories": user["categories"], "decision": user["decision"],
            "user_event_id": user["event_id"], "user_ref": user["source_ref"], "evidence": user["evidence"],
            "related_refs": user["related_refs"], "user_content_complete": user["content_complete"],
            "following_event_ids": [a["event_id"] for a in following],
            "following_actor_sequence": [a["actor"] for a in following],
            "following_actor_counts": dict(Counter(a["actor"] for a in following)),
            "following_event_kind_sequence": [KINDS.get(a["observation"], "other_recorded_event") for a in following],
            "observed_tool_failures": sum(a["observation"] == e.OBSERVATIONS["tool_failure"] for a in following),
            "following_truncated_events": sum(not a["content_complete"] for a in following),
            "order_basis": order, "elapsed_seconds": None,
            "boundary": "next_observed_user_utterance" if ordinal+1 < len(anchors) else "observed_session_end",
            "interpretation": "observation_segment_not_confirmed_instruction_execution_or_causal_episode"})
    sequence = [m["state"] for m in modules]
    transitions = [{"from_module": a["module_id"], "to_module": b["module_id"],
        "from": a["state"], "to": b["state"], "order_basis": order,
        "meaning": "adjacent_observed_user_modules"} for a, b in zip(modules, modules[1:])]
    return {"process_id": process_id, "session_id": coverage["session_id"],
        "max_observed_source_index": max((a["source_index"] for a in rows), default=0),
        "known_total_events": coverage["total_events"],
        "scope_status": coverage["status"], "attempt_statuses": coverage["attempt_statuses"],
        "order_basis": order, "sequence": sequence, "modules": modules, "transitions": transitions,
        "unanchored_initial_event_ids": [a["event_id"] for a in rows[:anchors[0] if anchors else len(rows)]],
        "repeated_state_count": len(sequence) - len(set(sequence)),
        "adjacent_repeat_count": sum(a == b for a, b in zip(sequence, sequence[1:])),
        "ambiguous_modules": sum(s in {"UNRESOLVED", "UNCLASSIFIED"} for s in sequence),
        "comparison_quality": "complete_observed_coding_draft" if coverage["status"] == "complete_public_scope" and not any(s in {"UNRESOLVED", "UNCLASSIFIED"} for s in sequence) and modules else "partial_or_ambiguous_observed_coding_draft"}


def analyze(run_dirs, max_pairs=500, individual_only=False):
    e.require(run_dirs and len(run_dirs) == len({str(Path(p).resolve()) for p in run_dirs}), "process_duplicate_or_empty_run_paths")
    e.require(type(max_pairs) is int and max_pairs >= 0, "process_invalid_pair_limit")
    events, owners, sources, session_meta = {}, {}, [], defaultdict(list)
    for folder in run_dirs:
        # Only explicitly selected derived artifact metadata is used to detect the mode.
        mode = e.read_json(Path(folder) / "coverage.json")["data_mode"]
        patterns, coverage, hashes = c.load_run(folder, mode)
        identities = {(a["participant_id"], a["task_id"]) for a in patterns["actions"]}
        e.require(len(identities) == 1, "process_source_needs_one_nonempty_participant_task")
        pid, task = next(iter(identities))
        namespace = coverage["dataset_namespace"]
        sources.append({"run_id": coverage["run_id"], "participant_id": pid, "task_id": task,
            "dataset_namespace": namespace, "data_mode": mode, "artifact_hashes": hashes,
            "taxonomy_sha256": coverage["taxonomy_sha256"], "skill_sha256": coverage["skill_sha256"],
            "model_observation": coverage["model_observation"], "complete_extraction": coverage["complete_extraction"]})
        if "model_context" in coverage:
            sources[-1]["model_context"] = coverage["model_context"]
        for s in coverage["sessions"]:
            if s["purpose"] == "task":
                session_meta[(pid, task, namespace, s["session_id"])].append(s)
        for a in patterns["actions"]:
            event = a["event_id"]
            e.require(event not in owners or owners[event] == (pid, task), "process_event_multiple_owners")
            owners[event] = (pid, task)
            e.require(event not in events or events[event]["action"] == a, "process_unresolved_coding_conflict")
            events[event] = {"action": a, "scope": (pid, task, namespace, a["session_id"])}
    e.require(len({s["data_mode"] for s in sources}) == 1, "process_mixed_data_modes")
    e.require(len({s["taxonomy_sha256"] for s in sources}) == 1, "process_mixed_taxonomy_requires_harmonization")
    rows_by_session = defaultdict(list)
    for entry in events.values():
        rows_by_session[entry["scope"]].append(entry["action"])
    units, processes = {}, []
    for scope, metas in sorted(session_meta.items()):
        pid, task, namespace, sid = scope
        rows = rows_by_session[scope]
        e.require(len(rows) == len({a["source_ref"] for a in rows}), "process_conflicting_session_mapping")
        process_id = "PR-" + e.digest(list(scope))[:20]
        merged = {"session_id": sid,
            "total_events": max((s["total_events"] for s in metas if s["total_events"] is not None), default=None),
            "status": "complete_public_scope" if all(s["status"] == "complete_public_scope" for s in metas) else "partial_or_unread",
            "attempt_statuses": sorted({s["attempt_status"] for s in metas})}
        process = session_modules(process_id, rows, merged)
        process.update(participant_id=pid, task_id=task, dataset_namespace=namespace)
        processes.append(process)
        key = (pid, task)
        if key not in units:
            units[key] = {"unit_id": "U-"+e.digest(list(key))[:16].upper(), "participant_id": pid,
                "task_id": task, "process_ids": [], "actions": [], "complete_extraction": True}
        units[key]["process_ids"].append(process_id)
        units[key]["actions"].extend(rows)
        units[key]["complete_extraction"] &= merged["status"] == "complete_public_scope"
    for unit in units.values():
        rows = unit.pop("actions")
        users = [a for a in rows if a["actor"] == "user"]
        reliable = [a for a in users if state(a) not in {"UNRESOLVED", "UNCLASSIFIED"}]
        unit.update(user_events=len(users), observed_coded_user_events=len(reliable),
            ambiguous_user_events=len(users)-len(reliable), observed_pattern_rates=c.rates(users),
            profile=[category for category in e.CRITERIA if any(category in a["categories"] for a in reliable)],
            observed_tool_failures=sum(a["observation"] == e.OBSERVATIONS["tool_failure"] for a in rows),
            truncated_events=sum(not a["content_complete"] for a in rows),
            coding_status="source_draft_not_automatically_reviewed")
    feature_rows = list(units.values())
    if individual_only:
        e.require(len({u["participant_id"] for u in feature_rows})==1,"individual_structure_one_participant_required")
        return {"analysis_version":VERSION,"analysis_mode":"individual_modules_only",
            "units":feature_rows,"processes":processes,"source_runs":sources,
            "module_dictionary":[{"category":cat,"label":values[1],"criterion":values[0]} for cat,values in e.CRITERIA.items()],
            "comparison_computation_performed":False}
    profiles = defaultdict(list)
    for unit in feature_rows:
        # Keep incomplete coverage and complete coverage groups visibly separate.
        profiles[(unit["task_id"], tuple(unit["profile"]), unit["complete_extraction"], unit["ambiguous_user_events"] == 0)].append(unit)
    profile_groups = []
    for (task, labels, complete, unambiguous), members in sorted(profiles.items()):
        profile_groups.append({"task_id": task, "categories": list(labels), "complete_extraction": complete,
            "unambiguous_observed_coding": unambiguous, "units": len(members),
            "participants": len({r["participant_id"] for r in members}), "unit_ids": [r["unit_id"] for r in members],
            "rates_equal_participant": {category: c.participant_mean(members, lambda r, cat=category: r["observed_pattern_rates"][cat]) for category in e.CRITERIA},
            "interpretation": "descriptive_observed_profile_not_validated_personality_cluster"})
    sequence_groups = defaultdict(list)
    edge_groups, motif_groups = defaultdict(list), defaultdict(list)
    for process in processes:
        sequence_groups[(process["task_id"], tuple(process["sequence"]), process["order_basis"], process["comparison_quality"])].append(process)
        for transition in process["transitions"]:
            edge_groups[(process["task_id"], transition["from"], transition["to"], process["order_basis"])].append((process, transition))
        for length in [2, 3]:
            for index in range(len(process["sequence"])-length+1):
                motif_groups[(process["task_id"], tuple(process["sequence"][index:index+length]), process["order_basis"])].append(process)
    pair_results, total_pairs = [], 0
    for left, right in combinations(processes, 2):
        if left["participant_id"] == right["participant_id"] or left["task_id"] != right["task_id"]:
            continue
        total_pairs += 1
        if len(pair_results) >= max_pairs:
            continue
        e.require(len(left["sequence"]) * len(right["sequence"]) <= 1000000, "process_pair_too_large_select_shorter_scope")
        pair_results.append({"left_process_id": left["process_id"], "right_process_id": right["process_id"],
            "task_id": left["task_id"], "left_sequence": left["sequence"], "right_sequence": right["sequence"],
            "quality": "partial_or_ambiguous" if any(p["comparison_quality"].startswith("partial") for p in [left, right]) else "complete_observed_coding_draft",
            "order_bases": [left["order_basis"], right["order_basis"]],
            "left_tool_failures": sum(m["observed_tool_failures"] for m in left["modules"]),
            "right_tool_failures": sum(m["observed_tool_failures"] for m in right["modules"]),
            **align(left["sequence"], right["sequence"])})
    return {"analysis_version": VERSION, "analysis_mode": "pattern_process_only", "data_mode": sources[0]["data_mode"],
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_requirements": "selected_derived_run_folders_only_no_assignment_table_answer_key_or_score",
        "module_dictionary": [{"category": cat, "label": values[1], "criterion": values[0]} for cat, values in e.CRITERIA.items()],
        "units": feature_rows, "processes": processes, "profile_groups": profile_groups,
        "sequence_groups": [{"task_id": task, "sequence": list(seq), "order_basis": order, "quality": quality,
            "sessions": len(members), "participants": len({p["participant_id"] for p in members}),
            "process_ids": [p["process_id"] for p in members]} for (task, seq, order, quality), members in sorted(sequence_groups.items())],
        "transition_counts": [{"task_id": task, "from": a, "to": b, "order_basis": order,
            "occurrences": len(entries), "participants": len({p["participant_id"] for p, t in entries}),
            "edges": [{"process_id": p["process_id"], **t} for p, t in entries]} for (task, a, b, order), entries in sorted(edge_groups.items())],
        "repeated_fragments": [{"task_id": task, "sequence": list(seq), "order_basis": order,
            "occurrences": len(members), "participants": len({p["participant_id"] for p in members})}
            for (task, seq, order), members in sorted(motif_groups.items()) if len(members) >= 2],
        "process_comparisons": pair_results, "pair_coverage": {"eligible_pairs": total_pairs,
            "included_pairs": len(pair_results), "omitted_by_limit": total_pairs-len(pair_results), "max_pairs": max_pairs},
        "source_runs": sources, "score_analysis_performed": False, "causal_claim": "not_identified",
        "limits": ["coding_semantics_not_verified_from_raw_sources", "source_codings_remain_drafts",
            "normalized_order_may_not_be_original_chronology", "module_boundaries_are_observation_windows",
            "no_cross_session_stitching", "missing_and_partial_records_can_change_groups",
            "same_task_id_does_not_independently_prove_task_comparability",
            "group_defining_patterns_are_not_independent_explanatory_factors",
            "sequence_distance_is_not_performance_or_ability", "no_answer_key_or_score_required"]}


def report(result):
    lines = ["# 사용자 패턴 모듈·과정 비교", "", "지정한 추출 결과만 사용했습니다. 배정표·정답지·성과 점수·수동 비교 JSON은 필요하지 않습니다.",
        f"참여자 {len({u['participant_id'] for u in result['units']})}명 / 참여자·과제 {len(result['units'])}단위 / 세션 {len(result['processes'])}개.",
        "행동 모듈은 사용자 발화 한 건의 패턴 묶음과 다음 사용자 발화 전까지 관찰된 AI·도구 사건입니다. 실제 명령 실행의 경계나 인과 연결로 확정하지 않습니다.", "",
        "## 모듈 사전", "", "| 모듈 | 코드 |", "|---|---|"]
    for item in result["module_dictionary"]:
        lines.append(f"| {item['label']} | {item['category']} |")
    lines += ["", "## 참여자별 관찰 과정", "", "| 참여자 | 과제 | 세션 | 패턴 순서 | 범위 | 반복 상태 수 |", "|---|---|---|---|---|---:|"]
    for p in result["processes"]:
        lines.append(f"| {p['participant_id']} | {p['task_id']} | {p['session_id']} | {' → '.join(readable(s) for s in p['sequence']) or '사용자 발화 미확인'} | {p['scope_status']} | {p['repeated_state_count']} |")
    lines += ["", "## 자동 패턴 조합 그룹", "", "| 과제 | 관찰 패턴 조합 | 참여자 | 단위 | 범위 완전 | 보류 없음 |", "|---|---|---:|---:|---|---|"]
    for g in result["profile_groups"]:
        labels = " + ".join(e.CRITERIA[c][1] for c in g["categories"]) or "확인된 코딩 없음"
        lines.append(f"| {g['task_id']} | {labels} | {g['participants']} | {g['units']} | {g['complete_extraction']} | {g['unambiguous_observed_coding']} |")
    lines += ["", "같은 패턴 조합이어도 순서가 다르면 순서 그룹에서 구별합니다. 조합 그룹은 안정된 성향이나 검증된 통계 군집이 아닙니다.", "",
        "## 참여자 간 과정 대조", "", "| 왼쪽 과정 | 오른쪽 과정 | 필요한 순서 편집 수 | 확인 범위 |", "|---|---|---:|---|"]
    for pair in result["process_comparisons"]:
        lines.append(f"| {pair['left_process_id']} | {pair['right_process_id']} | {pair['edit_distance']} | {pair['quality']} |")
    pair_count = result["pair_coverage"]
    lines += ["", f"가능한 대조 {pair_count['eligible_pairs']}쌍 중 {pair_count['included_pairs']}쌍 포함, 설정 한도로 {pair_count['omitted_by_limit']}쌍 생략.",
        "편집 수는 두 관찰 순서를 맞추는 데 필요한 삽입·삭제·교체 수입니다. 점수·능력·좋은 전략 순위로 사용하지 않습니다. 위치별 대조와 사건 근거는 processes.json에 있습니다.", "",
        "## 해석 범위", "", "빈도·전환·반복·행동 구간의 사건 구성은 비교할 수 있습니다. 같은 발화의 복수 패턴은 동시에 묶고 내부 순서를 만들어내지 않습니다.",
        "별도 세션은 이어 붙이지 않습니다. source_sequence가 없으면 패키지 행 순서만 비교하며 경과시간·반응시간을 만들지 않습니다.",
        "부분 기록·보류·잘림과 초안 코딩을 표시합니다. 관찰 없음은 실제 행동 없음이 아닙니다. 그룹을 만든 패턴으로 그 그룹 차이의 원인을 설명하면 순환 논리가 됩니다.",
        "확인된 모델 설정과 범위 차이는 출처로 남기지만, 경험·난이도·성과·이해도·심리 상태는 기록에서 추정하지 않습니다. 도구 실패도 성과 점수와 구별합니다.", ""]
    return "\n".join(lines)


def write_csv(path, rows, fields=None):
    fields = fields or (list(rows[0]) if rows else ["no_observed_rows"])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: e.csv_value(row.get(k)) for k in fields} for row in rows)


def build(run_dirs, out_root, max_pairs=500):
    folder = e.new_run(out_root)
    try:
        result = analyze(run_dirs, max_pairs)
        e.write_json(folder / "processes.json", result)
        e.write_json(folder / "comparison-inputs.json", {"analysis_version": VERSION,
            "input_kind": "selected_derived_runs", "source_runs": result["source_runs"],
            "generated_automatically": True, "external_tables_required": False})
        write_csv(folder / "features.csv", result["units"])
        write_csv(folder / "modules.csv", [{"process_id": p["process_id"], "participant_id": p["participant_id"],
            "task_id": p["task_id"], "session_id": p["session_id"], **m} for p in result["processes"] for m in p["modules"]])
        write_csv(folder / "transitions.csv", result["transition_counts"])
        (folder / "report.md").write_text(report(result), encoding="utf-8")
        names = ["processes.json", "comparison-inputs.json", "features.csv", "modules.csv", "transitions.csv", "report.md"]
        e.write_json(folder / "integrity.json", {"files": {name: hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in names}})
    except (e.ContractError, OSError) as error:
        e.write_json(folder / "failure.json", {"status": "failed", "error_code": str(error) if isinstance(error, e.ContractError) else "filesystem_error"})
        raise
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--out-root", default=str(e.ROOT / "runs"))
    parser.add_argument("--max-process-pairs", type=int, default=500)
    args = parser.parse_args()
    try:
        print(build(args.runs, args.out_root, args.max_process_pairs))
    except (e.ContractError, OSError):
        print("FAILED: inspect new run failure.json", file=sys.stderr)
        raise SystemExit(1)
