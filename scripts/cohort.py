"""Group approved derived outputs; compare outcomes and exploratory associations.

Reads only the five named result artifacts and the explicit comparison plan.
No raw sessions, source manifests, model calls, or patient files are accessed.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
from datetime import datetime
import hashlib
import math
from pathlib import Path
import random
import statistics
import sys

import extract as e
from build_cohort_contract import FIELDS

VERSION = "0.2.0"
CONTRACT = e.ROOT / "schemas/cohort-contract.json"
ARTIFACTS = ["actions.csv", "patterns.json", "coverage.json", "report.md"]


def mean(values):
    return statistics.mean(values) if values else None


def participant_mean(rows, value):
    by_person = defaultdict(list)
    for row in rows:
        v = value(row)
        if v is not None:
            by_person[row["participant_id"]].append(v)
    return mean([mean(v) for v in by_person.values()])


def load_run(folder, mode):
    folder = Path(folder).resolve()
    e.require(not (folder / "failure.json").exists(), "cohort_failed_source_run")
    integrity = e.read_json(folder / "integrity.json")
    hashes = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ARTIFACTS}
    e.require(integrity == {"files": hashes}, "cohort_source_integrity")
    patterns = e.read_json(folder / "patterns.json")
    coverage = e.read_json(folder / "coverage.json")
    e.check_schema(patterns, "patterns", CONTRACT)
    e.check_schema(coverage, "coverage", CONTRACT)
    e.require(coverage["data_mode"] == mode, "cohort_data_mode_mismatch")
    recomputed = e.calculate_patterns(patterns["actions"])
    recomputed["skill_version"] = patterns["skill_version"]
    e.require(patterns == recomputed, "cohort_counts_mismatch")
    e.require(patterns["taxonomy_version"] == coverage["taxonomy_version"], "cohort_taxonomy_mismatch")
    e.require(len(patterns["actions"]) == coverage["included_events"] and
              patterns["denominator"] == coverage["included_user_events"], "cohort_coverage_counts")
    task_sessions = [s for s in coverage["sessions"] if s["purpose"] == "task"]
    e.require(coverage["complete_extraction"] == (bool(task_sessions) and all(s["status"] == "complete_public_scope" for s in task_sessions)), "cohort_complete_claim_inconsistent")
    for s in task_sessions:
        if s["status"] == "complete_public_scope":
            e.require(s["approval"] and s["end_verified"] and s["total_events"] is not None and
                not s["missing_ranges"] and not s["truncated_refs"] and s["read_rows"] == s["total_events"], "cohort_complete_session_inconsistent")
    actions = patterns["actions"]
    e.mc.validate(coverage.get("model_context"), coverage["sessions"],
                  {a["source_ref"]: a for a in actions}, e.require)
    e.require(len({a["event_id"] for a in actions}) == len(actions), "cohort_duplicate_source_event")
    e.require(len({a["source_ref"] for a in actions}) == len(actions), "cohort_duplicate_source_ref")
    known = {a["source_ref"] for a in actions}
    session_ids = {s["session_id"] for s in task_sessions}
    for a in actions:
        e.require(a["session_id"] in session_ids, "cohort_non_task_session_action")
        e.require(a["source_ref"] == e.ref(a["session_id"], a["source_index"]), "cohort_ref_mismatch")
        e.require(a["actor"] == "user" or not a["categories"], "cohort_nonuser_coding")
        e.require(all(r in known for r in a["related_refs"]), "cohort_missing_related_ref")
        e.require(all(s["ref"] in known and s["end"] > s["start"] for s in a["evidence"]), "cohort_bad_evidence")
        if a["actor"] == "user":
            e.require(any(s["ref"] == a["source_ref"] for s in a["evidence"]), "cohort_own_evidence_required")
            e.require(sorted(a["criterion_codes"]) == sorted(e.CRITERIA[c][0] for c in a["categories"]), "cohort_criterion_mismatch")
    with (folder / "actions.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        e.require(reader.fieldnames == e.CSV_FIELDS, "cohort_csv_fields")
        e.require(list(reader) == [{k: e.csv_value(a[k]) for k in e.CSV_FIELDS} for a in actions], "cohort_csv_mismatch")
    return patterns, coverage, hashes


def rates(users):
    # Missing/ambiguous/truncated user coding is not treated as evidence of absence.
    valid = [a for a in users if a["content_complete"] and a["decision"] == "coded"]
    return {c: sum(c in a["categories"] for a in valid) / len(valid) if valid else None for c in e.CRITERIA}


def feature_unit(unit, actions, coverages):
    users = [a for a in actions if a["actor"] == "user"]
    complete = all(c["complete_extraction"] and not c["errors"] for c in coverages)
    uncertain = sum(a["decision"] != "coded" or not a["content_complete"] for a in users)
    feature_ok = complete and unit["coding_review"] == "reviewed" and bool(users) and uncertain == 0
    outcome = unit["outcome"]
    y = outcome["value"] if outcome["reviewed"] else None
    windows = unit["pre_outcome_window"]
    early = None
    if windows is not None:
        e.require(unit["window_ref"] is not None, "cohort_window_receipt_required")
        limits = {w["session_id"]: w["max_source_index"] for w in windows}
        e.require(len(limits) == len(windows), "cohort_duplicate_window_session")
        included_sessions = {s["session_id"] for c in coverages for s in c["sessions"] if s["purpose"] == "task"}
        e.require(set(limits) == included_sessions, "cohort_window_must_cover_task_sessions")
        for sid, limit in limits.items():
            totals = [s["total_events"] for c in coverages for s in c["sessions"] if s["session_id"] == sid]
            e.require(all(t is None or limit <= t for t in totals), "cohort_window_outside_scope")
        early = [a for a in users if a["source_index"] <= limits[a["session_id"]]]
    profiles = [c for c in e.CRITERIA if any(c in a["categories"] for a in users)]
    sessions = defaultdict(list)
    for a in actions:
        sessions[a["session_id"]].append(a)
    transitions, timing = [], []
    for sid, rows in sorted(sessions.items()):
        rows.sort(key=lambda a: a["source_index"])
        source_order = all(a["source_sequence"] is not None for a in rows) and all(
            a["source_sequence"] < b["source_sequence"] for a, b in zip(rows, rows[1:]))
        us = [a for a in rows if a["actor"] == "user"]
        for a, b in zip(us, us[1:]):
            transitions.append({"session_id": sid, "from_event": a["event_id"], "to_event": b["event_id"],
                "from_categories": a["categories"], "to_categories": b["categories"],
                "intermediate_observed_events": sum(a["source_index"] < r["source_index"] < b["source_index"] for r in rows),
                "order_basis": "source_sequence" if source_order else "normalized_package_order"})
        times = [datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00")) if a["timestamp"] else None for a in rows]
        duration = None
        if source_order and len(times) >= 2 and all(t is not None for t in times) and all(a <= b for a, b in zip(times, times[1:])):
            duration = (times[-1] - times[0]).total_seconds()
        timing.append({"session_id": sid, "observed_span_seconds": duration,
            "meaning": "first_to_last_observed_event_not_active_user_time"})
    return {"unit_id": unit["unit_id"], "participant_id": unit["participant_id"], "task_id": unit["task_id"],
        "covariates": unit["covariates"], "user_events": len(users), "all_events": len(actions),
        "coded_complete_user_events": len(users) - uncertain, "uncertain_user_events": uncertain,
        "complete_extraction": complete, "coding_review": unit["coding_review"],
        "session_attempts": [{"session_id": sid, "observed_statuses": sorted({s["attempt_status"] for c in coverages for s in c["sessions"] if s["session_id"] == sid})}
            for sid in sorted({s["session_id"] for c in coverages for s in c["sessions"] if s["purpose"] == "task"})],
        "primary_eligible": feature_ok, "observed_rates": rates(users), "observed_profile": profiles,
        "pre_outcome_rates": rates(early) if early is not None else None,
        "factor_eligible": feature_ok and bool(early), "outcome_value": y,
        "outcome_status": "reviewed" if y is not None else "missing_or_unreviewed",
        "transitions": transitions, "timing": timing}


def group_summary(rows):
    primary = [r for r in rows if r["primary_eligible"]]
    return {"units": len(rows), "participants": len({r["participant_id"] for r in rows}),
        "primary_units": len(primary), "outcome_observed_units": sum(r["outcome_value"] is not None for r in primary),
        "missing_or_unreviewed_outcome_units": sum(r["outcome_value"] is None for r in rows),
        "uncertain_user_events": sum(r["uncertain_user_events"] for r in rows),
        "primary_outcome_mean_equal_participant": participant_mean(primary, lambda r: r["outcome_value"]),
        "pattern_rates_equal_participant": {c: participant_mean(primary, lambda r: r["observed_rates"][c]) for c in e.CRITERIA}}


def difference(rows, select, value):
    a = participant_mean([r for r in rows if select(r) == "A"], value)
    b = participant_mean([r for r in rows if select(r) == "B"], value)
    return a - b if a is not None and b is not None else None


def standardized(rows, select, adjust, value):
    strata = defaultdict(list)
    for r in rows:
        key = tuple(r["covariates"][f] for f in adjust)
        if None not in key and select(r) in {"A", "B"} and value(r) is not None:
            strata[key].append(r)
    cells = []
    # Equal weight per common stratum and then equal participant per group/stratum.
    # This defines an overlap-population estimand, not the full-cohort causal effect.
    for key, cell in sorted(strata.items()):
        delta = difference(cell, select, value)
        if delta is not None:
            cells.append({"stratum": dict(zip(adjust, key)), "difference_a_minus_b": delta,
                "mean_a": participant_mean([r for r in cell if select(r) == "A"], value),
                "mean_b": participant_mean([r for r in cell if select(r) == "B"], value),
                "participants_a": len({r["participant_id"] for r in cell if select(r) == "A"}),
                "participants_b": len({r["participant_id"] for r in cell if select(r) == "B"})})
    common = {tuple(c["stratum"][f] for f in adjust) for c in cells}
    n_overlap = sum(tuple(r["covariates"][f] for f in adjust) in common and select(r) in {"A", "B"} and value(r) is not None for r in rows)
    return {"difference_a_minus_b": mean([c["difference_a_minus_b"] for c in cells]),
        "common_strata": cells, "overlap_units": n_overlap,
        "weighting": "equal_common_strata_then_equal_participant",
        "missing_adjustment_units": sum(any(r["covariates"][f] is None for f in adjust) for r in rows)}


def bootstrap(rows, select, value, reps, seed):
    relevant = [r for r in rows if select(r) in {"A", "B"} and value(r) is not None]
    persons = sorted({r["participant_id"] for r in relevant})
    per_group = {g: len({r["participant_id"] for r in relevant if select(r) == g}) for g in ["A", "B"]}
    output = {"method": "participant_cluster_percentile", "level": 0.95,
        "independent_participants_by_group": per_group, "interval": None,
        "valid_replicates": 0, "requested_replicates": reps, "status": "insufficient_participants"}
    # Operational display threshold, not a proof of adequacy or a power calculation.
    if min(per_group.values()) < 5:
        return output
    by_person = {p: [r for r in relevant if r["participant_id"] == p] for p in persons}
    rng, deltas = random.Random(seed), []
    for _ in range(reps):
        sample = []
        for i in range(len(persons)):
            for row in by_person[rng.choice(persons)]:
                sample.append({**row, "participant_id": f"BOOT-{i}"})
        delta = difference(sample, select, value)
        if delta is not None:
            deltas.append(delta)
    output["valid_replicates"] = len(deltas)
    output["status"] = "unstable_bootstrap"
    if len(deltas) >= reps * .95:
        deltas.sort()
        def quantile(q):
            point = q * (len(deltas) - 1)
            lo = int(point)
            hi = min(lo + 1, len(deltas) - 1)
            return deltas[lo] + (point - lo) * (deltas[hi] - deltas[lo])
        output.update(interval=[quantile(.025), quantile(.975)], status="exploratory_interval")
    return output


def contrast(rows, select, plan, adjust):
    value = lambda r: r["outcome_value"]
    subset = [r for r in rows if select(r) in {"A", "B"}]
    primary = [r for r in subset if r["primary_eligible"]]
    reviewed = [r for r in subset if r["coding_review"] == "reviewed"]
    primary_delta = difference(primary, select, value)
    adjusted = standardized(primary, select, adjust, value) if adjust else None
    return {"difference_a_minus_b": primary_delta,
        "direction": "a_higher" if primary_delta is not None and primary_delta > 0 else "b_higher" if primary_delta is not None and primary_delta < 0 else "equal" if primary_delta == 0 else "unavailable",
        "primary_groups": {g: group_summary([r for r in subset if select(r) == g]) for g in ["A", "B"]},
        "adjusted": adjusted,
        "reversal_after_adjustment": bool(adjusted and primary_delta is not None and adjusted["difference_a_minus_b"] is not None and primary_delta * adjusted["difference_a_minus_b"] < 0),
        "sensitivity_including_partial_reviewed_difference": difference(reviewed, select, value),
        "uncertainty": bootstrap(primary, select, value, plan["bootstrap_replicates"], plan["seed"]),
        "interpretation": "observed_association_not_causal_effect"}


def analyze(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = e.read_json(plan_path)
    e.check_schema(plan, "cohort_plan", CONTRACT)
    e.require(len({u["unit_id"] for u in plan["units"]}) == len(plan["units"]), "cohort_duplicate_unit")
    e.require(len({(u["participant_id"], u["task_id"]) for u in plan["units"]}) == len(plan["units"]), "cohort_repeated_task_requires_distinct_task_id")
    definition = plan["outcome_definition"]
    e.require(math.isfinite(definition["minimum"]) and math.isfinite(definition["maximum"]) and definition["minimum"] < definition["maximum"], "cohort_outcome_scale")
    e.require(not set(plan["group_by"]) & set(plan["adjust_by"]), "cohort_group_adjust_overlap")
    for c in plan["comparisons"]:
        e.require(c["field"] in plan["group_by"] and c["level_a"] != c["level_b"], "cohort_invalid_comparison")
    features, sources, owners = [], [], {}
    for unit in plan["units"]:
        outcome = unit["outcome"]
        y = outcome["value"]
        e.require(y is None or math.isfinite(y) and definition["minimum"] <= y <= definition["maximum"], "cohort_outcome_out_of_range")
        e.require(not outcome["reviewed"] or y is None or outcome["assessment_ref"] is not None, "cohort_outcome_receipt_required")
        actions, coverages = {}, []
        paths = [(plan_path.parent / p).resolve() for p in unit["run_dirs"]]
        e.require(len(set(paths)) == len(paths), "cohort_duplicate_resolved_path")
        for folder in paths:
            patterns, coverage, hashes = load_run(folder, plan["data_mode"])
            e.require(all(a["participant_id"] == unit["participant_id"] and a["task_id"] == unit["task_id"] for a in patterns["actions"]), "cohort_unit_identity_mismatch")
            coverages.append(coverage)
            sources.append({"unit_id": unit["unit_id"], "run_id": coverage["run_id"],
                "dataset_namespace": coverage["dataset_namespace"], "artifact_hashes": hashes,
                "skill_sha256": coverage["skill_sha256"], "taxonomy_sha256": coverage["taxonomy_sha256"],
                "model_observation": coverage["model_observation"],
                "complete_extraction": coverage["complete_extraction"]})
            if "model_context" in coverage:
                sources[-1]["model_context"] = coverage["model_context"]
            for a in patterns["actions"]:
                event = a["event_id"]
                e.require(event not in owners or owners[event] == unit["unit_id"], "cohort_event_assigned_multiple_units")
                owners[event] = unit["unit_id"]
                e.require(event not in actions or actions[event] == a, "cohort_unresolved_coding_conflict")
                actions[event] = a
        # No merging shifted row numbers or unlike exports under a shared session alias.
        refs = [a["source_ref"] for a in actions.values()]
        e.require(len(refs) == len(set(refs)), "cohort_conflicting_session_alias")
        features.append(feature_unit(unit, list(actions.values()), coverages))
    e.require(len({s["taxonomy_sha256"] for s in sources}) <= 1, "cohort_mixed_taxonomy_requires_harmonization")
    groups = []
    for field in plan["group_by"]:
        for level in sorted({r["covariates"][field] or "UNKNOWN" for r in features}):
            rows = [r for r in features if (r["covariates"][field] or "UNKNOWN") == level]
            groups.append({"field": field, "level": level, **group_summary(rows)})
    comparisons = []
    for c in plan["comparisons"]:
        select = lambda r, c=c: "A" if r["covariates"][c["field"]] == c["level_a"] else "B" if r["covariates"][c["field"]] == c["level_b"] else None
        comparisons.append({**c, **contrast(features, select, plan, plan["adjust_by"])})
    factors = []
    eligible = [r for r in features if r["factor_eligible"]]
    for category in e.CRITERIA:
        select = lambda r, c=category: "A" if r["pre_outcome_rates"][c] is not None and r["pre_outcome_rates"][c] > 0 else "B" if r["pre_outcome_rates"][c] == 0 else None
        aligned = []
        if {select(r) for r in eligible} == {"A", "B"}:
            for field in FIELDS:
                if all(r["covariates"][field] is not None for r in eligible):
                    by_level = defaultdict(set)
                    for r in eligible:
                        by_level[r["covariates"][field]].add(select(r))
                    if all(len(values) == 1 for values in by_level.values()):
                        aligned.append(field)
        factors.append({"category": category, "comparison": "observed_before_outcome_vs_not_coded_in_complete_window",
            "eligible_units": len(eligible), **contrast(eligible, select, plan, plan["adjust_by"]),
            "whole_window_observed_units": sum(r["observed_rates"][category] is not None and r["observed_rates"][category] > 0 for r in features),
            "pre_window_observed_units": sum(select(r) == "A" for r in eligible),
            "perfectly_aligned_covariates": aligned,
            "within_covariate_independent_contrast": "not_observed" if aligned else "not_established_by_this_check",
            "multiple_comparisons": "seven_exploratory_contrasts_no_confirmatory_p_values"})
    profiles = sorted({tuple(r["observed_profile"]) for r in features})
    return {"analysis_version": VERSION, "study_id": plan["study_id"], "data_mode": plan["data_mode"],
        "grouping_basis": plan["grouping_basis"], "plan_sha256": e.digest(plan),
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "outcome_definition": definition, "units": features, "groups": groups,
        "comparisons": comparisons, "candidate_factors": factors,
        "observed_profile_groups": [{"categories": list(k),
            **group_summary([r for r in features if tuple(r["observed_profile"]) == k]),
            "interpretation": "post_hoc_session_profile_not_personality_or_validated_cluster"} for k in profiles],
        "source_runs": sources, "causal_identification": "not_established",
        "measurement_diagnostics": {"distinct_skill_instruction_hashes": len({s["skill_sha256"] for s in sources}),
            "distinct_model_observations": len({e.canonical(s["model_observation"]) for s in sources}),
            "unknown_model_settings_source_runs": sum(not s["model_observation"]["settings_confirmed"] for s in sources),
            "missing_covariate_units": {f: sum(r["covariates"][f] is None for r in features) for f in FIELDS}},
        "limits": ["approval_and_review_flags_are_assertions_not_independently_verified",
            "no_raw_semantic_or_outcome_rubric_verification", "missingness_may_be_informative",
            "unmeasured_confounders_and_reverse_causation_remain", "no_active_user_time_inference",
            "small_sample_intervals_exploratory_not_power_or_validity_proof",
            "exact_strata_adjustment_not_regression_or_randomization"]}


def markdown(result):
    lines = ["# 그룹·결과 비교 초안", "", "실자료 수집·원문 재열람 없이 지정한 파생 산출물과 비교 계획만 분석했습니다.",
        f"데이터 모드: {result['data_mode']} / 참여자 {len({r['participant_id'] for r in result['units']})}명 / 참여자·과제 {len(result['units'])}단위.",
        "원인을 확정하지 않습니다. 결과 점수는 외부 평가값이며 스킬이 성공을 추정하지 않습니다.", "",
        "| 그룹 변수 | 수준 | 참여자 | 단위 | 주 분석 단위 | 결과 평균 |", "|---|---|---:|---:|---:|---:|"]
    def fmt(v):
        return "확인 불가" if v is None else f"{v:.4g}"
    for g in result["groups"]:
        lines.append(f"| {g['field']} | {g['level']} | {g['participants']} | {g['units']} | {g['primary_units']} | {fmt(g['primary_outcome_mean_equal_participant'])} |")
    lines += ["", "## 관찰 패턴 조합별 기술 비교", "", "사후 조합 그룹이며 평가 이전 요인 그룹이나 안정된 사용자 유형이 아닙니다.", "",
        "| 관찰 패턴 조합 | 참여자 | 단위 | 주 분석 단위 | 결과 평균 |", "|---|---:|---:|---:|---:|"]
    for g in result["observed_profile_groups"]:
        labels = ", ".join(e.CRITERIA[c][1] for c in g["categories"]) or "코딩된 패턴 없음"
        lines.append(f"| {labels} | {g['participants']} | {g['units']} | {g['primary_units']} | {fmt(g['primary_outcome_mean_equal_participant'])} |")
    lines += ["", "평균은 각 참여자의 과제 평균을 구한 뒤 참여자별 동일 가중으로 계산합니다. 발화 수를 독립 표본 수로 쓰지 않습니다.",
        "주 분석은 완전 추출·검토 코딩·확인된 사용자 분류만 사용합니다. 불완전한 검토본을 포함한 민감도 결과는 별도입니다.", "",
        "## 지정 그룹 비교", ""]
    for c in result["comparisons"]:
        adj = c["adjusted"]
        lines.append(f"- {c['field']}: {c['level_a']} − {c['level_b']}, 차이 {fmt(c['difference_a_minus_b'])}; 공통 층 보정 {fmt(adj['difference_a_minus_b']) if adj else '미지정'}; 보정 후 방향 역전 {c['reversal_after_adjustment']}.")
        ci = c["uncertainty"]
        interval = " ~ ".join(fmt(v) for v in ci["interval"]) if ci["interval"] is not None else "표시 안 함"
        lines.append(f"  - 전체 차이의 탐색 95% 구간: {interval} ({ci['status']}); 부분 검토본 포함 차이 {fmt(c['sensitivity_including_partial_reviewed_difference'])}.")
        if adj:
            lines += [f"  - 공통 조건 단위 {adj['overlap_units']} / 보정 조건 누락 단위 {adj['missing_adjustment_units']}. 보정 차이의 신뢰구간은 미계산.", "",
                "| 공통 조건 | A 참여자 | B 참여자 | A 평균 | B 평균 | A−B |", "|---|---:|---:|---:|---:|---:|"]
            for cell in adj["common_strata"]:
                label = ", ".join(f"{key}={value}" for key, value in cell["stratum"].items())
                lines.append(f"| {label} | {cell['participants_a']} | {cell['participants_b']} | {fmt(cell['mean_a'])} | {fmt(cell['mean_b'])} | {fmt(cell['difference_a_minus_b'])} |")
    lines += ["", "## 결과 차이와 함께 관찰된 후보 패턴", "", "결과 평가 이전으로 지정한 구간만 사용합니다. 구간이 없으면 요인 분석에서 제외합니다. 시각 순서의 독립 검증은 하지 않았습니다.", "",
        "| 패턴 | 있음 단위/참여자 | 없음 단위/참여자 | 있음−없음 결과 차이 | 공통 층 보정 |", "|---|---:|---:|---:|---:|"]
    for f in result["candidate_factors"]:
        a, b = f["primary_groups"]["A"], f["primary_groups"]["B"]
        lines.append(f"| {e.CRITERIA[f['category']][1]} | {a['units']}/{a['participants']} | {b['units']}/{b['participants']} | {fmt(f['difference_a_minus_b'])} | {fmt(f['adjusted']['difference_a_minus_b']) if f['adjusted'] else '미지정'} |")
    lines.append("")
    for f in result["candidate_factors"]:
        if f["perfectly_aligned_covariates"]:
            lines.append(f"- {e.CRITERIA[f['category']][1]} 있음/없음은 {', '.join(f['perfectly_aligned_covariates'])}와 완전히 겹칩니다. 해당 조건 내 독립 비교가 없어 패턴의 독립적 요인 효과를 분리할 수 없습니다.")
        if f["whole_window_observed_units"] and not f["pre_window_observed_units"]:
            lines.append(f"- {e.CRITERIA[f['category']][1]}은 전체 구간 {f['whole_window_observed_units']}단위에서 관찰됐지만 평가 전 적격 구간에서는 0단위입니다. 평가 전 구간 밖의 관찰 또는 구간/품질 제외 때문에 요인 비교에 포함되지 않았습니다.")
    units, diag = result["units"], result["measurement_diagnostics"]
    lines += ["", "## 누락·측정 조건", "",
        f"전체 {len(units)}단위 중 주 분석 제외 {sum(not u['primary_eligible'] for u in units)}, 부분 추출 {sum(not u['complete_extraction'] for u in units)}, 미검토 코딩 {sum(u['coding_review'] != 'reviewed' for u in units)}.",
        f"결과 누락/미검토 {sum(u['outcome_value'] is None for u in units)}단위, 평가 전 구간 없음 {sum(u['pre_outcome_rates'] is None for u in units)}단위, 불확실 사용자 발화 {sum(u['uncertain_user_events'] for u in units)}건.",
        f"관찰 시각 간격 계산 불가 {sum(s['observed_span_seconds'] is None for u in units for s in u['timing'])}세션. 스킬 지시 해시 {diag['distinct_skill_instruction_hashes']}종, 모델 관찰 설정 {diag['distinct_model_observations']}종, 모델 설정 미확인 원천 실행 {diag['unknown_model_settings_source_runs']}개."]
    lines += ["", "| 비교 조건 | 정보 누락 단위 |", "|---|---:|"]
    for field, count in diag["missing_covariate_units"].items():
        lines.append(f"| {field} | {count} |")
    lines += ["", "층화는 지정 조건이 동일하고 두 그룹이 함께 관찰된 층만 비교합니다. 층별 동일 가중 대상이므로 원래 전체 그룹 평균과 대상 집단이 다릅니다.",
        "일곱 후보를 탐색하며 유의한 원인 순위를 만들지 않습니다. 누락된 점수는 실패나 0점으로 대체하지 않습니다.",
        "같은 참여자의 반복 과제를 묶어 부트스트랩합니다. 그룹별 참여자 5명 미만이면 구간을 표시하지 않습니다. 5명 이상도 표본 적정성의 보증이 아닙니다.",
        "시간은 원본 순번과 모든 시각이 확인된 세션의 첫·마지막 관찰 간격만 제시합니다. 작업 전체 시간·사용자 활동 시간은 아닙니다.",
        "모델 설정·과제 난이도·경험·학습·선택 편향·미측정 요인이 남을 수 있습니다. 인과 검증에는 사전 연구 설계와 별도 검토가 필요합니다.",
        "분류 근거·평가 점수·승인 표시의 진위는 이 분석기가 검증하지 않습니다. 출처 해시와 제외 조건은 analysis.json을 확인합니다.", ""]
    return "\n".join(lines)


def build(plan, out_root):
    folder = e.new_run(out_root)
    try:
        result = analyze(plan)
        e.write_json(folder / "analysis.json", result)
        (folder / "report.md").write_text(markdown(result), encoding="utf-8")
        rows = []
        for r in result["units"]:
            rows.append({k: e.csv_value(v) for k, v in r.items() if k not in {"transitions", "timing"}})
        with (folder / "features.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        e.write_json(folder / "integrity.json", {"files": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ["analysis.json", "features.csv", "report.md"]}})
    except (e.ContractError, OSError) as error:
        e.write_json(folder / "failure.json", {"status": "failed", "error_code": str(error) if isinstance(error, e.ContractError) else "filesystem_error"})
        raise
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--plan", help="Optional external outcome comparison plan")
    inputs.add_argument("--runs", nargs="+", help="Pattern/process comparison directly from selected result folders; no score plan")
    parser.add_argument("--max-process-pairs", type=int, default=500)
    parser.add_argument("--out-root", default=str(e.ROOT / "runs"))
    args = parser.parse_args()
    try:
        if args.runs:
            from compare_processes import build as build_processes
            print(build_processes(args.runs, args.out_root, args.max_process_pairs))
        else:
            print(build(args.plan, args.out_root))
    except (e.ContractError, OSError):
        print("FAILED: inspect new analysis failure.json", file=sys.stderr)
        raise SystemExit(1)
