"""Normalized session intake validation and evidence-linked draft publishing. No model calls."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
import model_context as mc

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
SCHEMA_VERSION = "1.0.0"
TAXONOMY_VERSION = "instruction-patterns-0.1.0"
CRITERIA = {
    "goal_specification": ("explicit_goal_or_constraint", "목표·조건 명시"),
    "task_decomposition": ("explicit_parts_or_order", "작업 분해·순서 지시"),
    "delegation_control": ("explicit_delegation_or_boundary", "위임·통제"),
    "verification_request": ("explicit_evidence_or_check_request", "검증·근거 요청"),
    "error_correction": ("explicit_error_or_revision", "오류·누락 교정"),
    "reuse_resume": ("explicit_prior_result_or_resume", "이전 결과 재사용·재개"),
    "data_structure_inquiry": ("explicit_structure_request", "자료구조 파악 요청"),
}
OBSERVATIONS = {
    "assistant_statement": "AI 공개 진술",
    "tool_request": "도구 실행 요청",
    "tool_success": "도구 성공 결과",
    "tool_failure": "도구 실패 결과",
    "tool_cancelled": "도구 중단 결과",
    "system_event": "시스템 공개 사건",
}
CSV_FIELDS = ["event_id", "participant_id", "task_id", "session_id", "source_index",
              "source_sequence", "actor", "observation", "categories", "decision",
              "ambiguity", "criterion_codes", "source_ref", "ref_kind", "timestamp",
              "content_complete", "evidence", "related_refs"]


class ContractError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ContractError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ContractError("json_unreadable_or_invalid") from None


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_schema(value, name, contract_path=None):
    """Validate exactly the published contract subset, rejecting unknown fields.

    Supports $ref, type, properties, required, additionalProperties, items, enum,
    const, minimum, maximum, minItems, uniqueItems, minLength, pattern, format.
    This is not a general-purpose JSON Schema implementation.
    """
    contract = read_json(contract_path or ROOT / "schemas/contract.json")
    types = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
             "string": lambda x: isinstance(x, str), "boolean": lambda x: isinstance(x, bool),
             "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
             "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
             "null": lambda x: x is None}

    def visit(item, schema, location):
        if "$ref" in schema:
            require(schema["$ref"].startswith("#/$defs/"), "unsupported_schema_reference")
            return visit(item, contract["$defs"][schema["$ref"].split("/")[-1]], location)
        expected = schema.get("type")
        if expected:
            accepted = expected if isinstance(expected, list) else [expected]
            require(any(types[t](item) for t in accepted), "schema_type:" + location)
        if "const" in schema:
            require(type(item) is type(schema["const"]) and item == schema["const"], "schema_const:" + location)
        if "enum" in schema:
            require(item in schema["enum"], "schema_enum:" + location)
        if isinstance(item, dict):
            require(all(k in item for k in schema.get("required", [])), "schema_required:" + location)
            props = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                require(set(item) <= set(props), "schema_unknown_field:" + location)
            for key, field in props.items():
                if key in item:
                    visit(item[key], field, location + "." + key)
        if isinstance(item, list):
            require(len(item) >= schema.get("minItems", 0), "schema_min_items:" + location)
            if schema.get("uniqueItems"):
                require(len({canonical(v) for v in item}) == len(item), "schema_unique_items:" + location)
            if "items" in schema:
                for i, field in enumerate(item):
                    visit(field, schema["items"], location + "[]")
        if isinstance(item, str):
            require(len(item) >= schema.get("minLength", 0), "schema_min_length:" + location)
            if "pattern" in schema:
                require(re.fullmatch(schema["pattern"], item) is not None, "schema_pattern:" + location)
            if schema.get("format") == "date-time":
                try:
                    parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
                    require(parsed.tzinfo is not None, "timestamp_timezone_required")
                except ValueError:
                    raise ContractError("timestamp_invalid") from None
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if "minimum" in schema:
                require(item >= schema["minimum"], "schema_minimum:" + location)
            if "maximum" in schema:
                require(item <= schema["maximum"], "schema_maximum:" + location)

    visit(value, contract["$defs"][name], name)


def contained_file(base, relative):
    requested = Path(relative)
    require(not requested.is_absolute() and ".." not in requested.parts, "source_path_escape")
    candidate = (base / requested).resolve()
    require(candidate.is_relative_to(base.resolve()), "source_path_escape")
    return candidate


def ref(session, index):
    return f"{session}/row-{index:06d}"


def load_sources(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = read_json(manifest_path)
    check_schema(manifest, "manifest")
    model = manifest["model_observation"]
    require(model["model_id_confirmed"] == (model["model_id"] is not None), "model_confirmation_inconsistent")
    known_settings = any(model[k] is not None for k in ["temperature", "top_p", "context_length"])
    require(model["settings_confirmed"] == known_settings, "settings_confirmation_inconsistent")
    require(len({s["session_id"] for s in manifest["sessions"]}) == len(manifest["sessions"]), "duplicate_session_alias")
    all_events, coverage_sessions, hashes = {}, [], []
    for session in manifest["sessions"]:
        sid = session["session_id"]
        coverage = {"session_id": sid, "attempt_status": session["attempt_status"],
                    "approval": session["approved"], "purpose": session["purpose"],
                    "status": "unread", "total_events": session["total_events"],
                    "read_ranges": [], "read_rows": 0, "included_events": 0,
                    "missing_ranges": [], "excluded": [], "duplicates": [],
                    "truncated_refs": [], "unknown_timestamps": 0,
                    "end_verified": False, "receipt_sha256": None, "error_code": None}
        coverage_sessions.append(coverage)
        if session["purpose"] == "analysis":
            coverage["status"] = "excluded_analysis_session"
            continue
        if not session["approved"]:
            coverage["status"] = "missing_approval"
            continue
        if session["access"] != "available":
            coverage["status"] = session["access"]
            continue
        require(session["events_file"] is not None, "events_file_required")
        path = contained_file(manifest_path.parent, session["events_file"])
        try:
            events = read_json(path)
        except ContractError:
            coverage["status"] = "unreadable"
            coverage["error_code"] = "json_unreadable_or_invalid"
            continue
        check_schema(events, "events")
        require(len({e["source_index"] for e in events}) == len(events), "duplicate_source_index")
        indices = sorted(e["source_index"] for e in events)
        require(indices == [e["source_index"] for e in events], "source_order_invalid")
        total = session["total_events"]
        require(total is None or all(i <= total for i in indices), "index_exceeds_total")
        coverage["read_rows"] = len(events)
        coverage["read_ranges"] = compress_ranges(indices)
        coverage["receipt_sha256"] = digest(session["read_receipts"])
        if total is not None:
            coverage["missing_ranges"] = missing_ranges(indices, total)
        coverage["end_verified"] = session["end_verified"]
        if session["end_verified"]:
            require(total is not None and not coverage["missing_ranges"] and bool(session["read_receipts"]), "unsupported_completeness_claim")
        hashes.append({"session_id": sid, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        seen_source_ids = {}
        for event in events:
            source_ref = ref(sid, event["source_index"])
            excluded = None
            if event["visibility"] != "public":
                excluded = "private_content"
            elif event["kind"] == "compaction":
                excluded = "compaction_summary"
            elif event["phase"] == "analysis" or (session["analysis_start_index"] is not None and event["source_index"] >= session["analysis_start_index"]):
                excluded = "after_extraction_start"
            if excluded:
                coverage["excluded"].append({"ref": source_ref, "reason": excluded})
                continue
            actor = event["actor"]
            valid_kinds = {"user": {"user_message"}, "assistant": {"assistant_statement"},
                           "tool": {"tool_request", "tool_success", "tool_failure", "tool_cancelled"},
                           "system": {"system_event"}}
            require(event["kind"] in valid_kinds[actor], "actor_kind_mismatch")
            if event["source_id"] is not None:
                payload = {k: v for k, v in event.items() if k != "source_index"}
                if event["source_id"] in seen_source_ids:
                    previous, previous_digest = seen_source_ids[event["source_id"]]
                    require(previous_digest == digest(payload), "conflicting_original_id")
                    coverage["duplicates"].append({"ref": source_ref, "canonical_ref": previous})
                    continue
                seen_source_ids[event["source_id"]] = (source_ref, digest(payload))
            origin_key = ["original_id", event["source_id"]] if event["source_id"] is not None else ["intake_row", event["source_index"]]
            event_id = "E-" + digest([manifest["dataset_namespace"], sid, origin_key])
            all_events[source_ref] = {**event, "source_ref": source_ref, "event_id": event_id,
                                      "session_id": sid, "ref_kind": "package_row"}
            coverage["included_events"] += 1
            if not event["content_complete"]:
                coverage["truncated_refs"].append(source_ref)
            if event["timestamp"] is None:
                coverage["unknown_timestamps"] += 1
        full = session["end_verified"] and not coverage["truncated_refs"]
        coverage["status"] = "complete_public_scope" if full else "partial"
    mc.validate(manifest.get("model_context"), manifest["sessions"], all_events, require)
    return manifest, all_events, coverage_sessions, hashes


def compress_ranges(indices):
    ranges = []
    for i in indices:
        if ranges and i == ranges[-1][1] + 1:
            ranges[-1][1] = i
        else:
            ranges.append([i, i])
    return ranges


def missing_ranges(indices, total):
    gaps, next_index = [], 1
    for index in indices:
        if index > next_index:
            gaps.append([next_index, index - 1])
        next_index = index + 1
    if next_index <= total:
        gaps.append([next_index, total])
    return gaps


def validated_codings(path, events):
    document = read_json(path)
    check_schema(document, "codings")
    require(document["taxonomy_version"] == TAXONOMY_VERSION, "taxonomy_version_mismatch")
    entries = document["entries"]
    require(len({c["source_ref"] for c in entries}) == len(entries), "duplicate_coding")
    codings = {c["source_ref"]: c for c in entries}
    require(set(codings) == {r for r, e in events.items() if e["actor"] == "user"}, "user_coding_coverage_mismatch")
    for source_ref, coding in codings.items():
        event = events[source_ref]
        labels = coding["categories"]
        require(set(coding["criterion_codes"]) == {CRITERIA[label][0] for label in labels}, "criterion_label_mismatch")
        if coding["decision"] == "coded":
            require(bool(labels) and coding["ambiguity"] is None, "coded_decision_invalid")
        else:
            require(not labels, "uncertain_coding_has_labels")
            require((coding["ambiguity"] is not None) == (coding["decision"] == "deferred"), "uncertain_decision_invalid")
        if not event["content_complete"]:
            require(coding["decision"] == "deferred" and coding["ambiguity"] == "insufficient_context", "truncated_coding_must_defer")
        require(any(s["ref"] == source_ref for s in coding["evidence"]), "own_evidence_required")
        for span in coding["evidence"]:
            require(span["ref"] in events, "evidence_ref_not_read")
            require(0 <= span["start"] < span["end"] <= len(events[span["ref"]]["text"]), "evidence_span_invalid")
        require(all(r in events for r in coding["related_refs"]), "related_ref_not_read")
    return document, codings


def calculate_patterns(actions):
    users = [a for a in actions if a["actor"] == "user"]
    counts = []
    for label, (criterion, description) in CRITERIA.items():
        matches = [a for a in users if label in a["categories"]]
        counts.append({"category": label, "label": description, "criterion": criterion,
                       "count": len(matches), "denominator": len(users),
                       "proportion": len(matches) / len(users) if users else None,
                       "event_ids": [a["event_id"] for a in matches]})
    return {"skill_version": VERSION, "schema_version": SCHEMA_VERSION,
            "taxonomy_version": TAXONOMY_VERSION, "review_status": "draft",
            "denominator_definition": "included_unique_public_user_events",
            "denominator": len(users), "counts": counts,
            "uncertainties": [{"event_id": a["event_id"], "source_ref": a["source_ref"],
                               "reason": a["ambiguity"]} for a in users if a["decision"] == "deferred"],
            "unclassified_event_ids": [a["event_id"] for a in users if a["decision"] == "unclassified"],
            "actions": actions}


def derive(manifest_path, codings_path):
    manifest, events, sessions, hashes = load_sources(manifest_path)
    coding_document, codings = validated_codings(codings_path, events)
    actions = []
    for source_ref, event in events.items():
        coding = codings.get(source_ref)
        labels = sorted(coding["categories"]) if coding else []
        observation = "; ".join(CRITERIA[c][1] for c in labels) if labels else ("판단 보류" if coding and coding["decision"] == "deferred" else "미분류 사용자 발화" if coding else OBSERVATIONS[event["kind"]])
        action = {"event_id": event["event_id"], "participant_id": manifest["participant_id"],
                  "task_id": manifest["task_id"], "session_id": event["session_id"],
                  "source_index": event["source_index"], "source_sequence": event["source_sequence"],
                  "actor": event["actor"], "observation": observation, "categories": labels,
                  "decision": coding["decision"] if coding else "not_user",
                  "ambiguity": coding["ambiguity"] if coding else None,
                  "criterion_codes": sorted(coding["criterion_codes"]) if coding else [],
                  "source_ref": source_ref, "ref_kind": "package_row", "timestamp": event["timestamp"],
                  "content_complete": event["content_complete"],
                  "evidence": coding["evidence"] if coding else [],
                  "related_refs": coding["related_refs"] if coding else []}
        actions.append(action)
    patterns = calculate_patterns(actions)
    task_sessions = [s for s in sessions if s["purpose"] == "task"]
    complete = bool(task_sessions) and all(s["status"] == "complete_public_scope" for s in task_sessions)
    coverage = {"skill_version": VERSION, "schema_version": SCHEMA_VERSION,
                "taxonomy_version": TAXONOMY_VERSION, "data_mode": manifest["data_mode"],
                "dataset_namespace": manifest["dataset_namespace"], "adapter": manifest["adapter"],
                "complete_extraction": complete, "requested_sessions": len(sessions),
                "requested_task_sessions": len(task_sessions),
                "read_sessions": sum(s["status"] in {"complete_public_scope", "partial"} for s in sessions),
                "included_events": len(actions), "included_user_events": patterns["denominator"],
                "sessions": sessions, "source_hashes": hashes,
                "manifest_sha256": digest(manifest), "codings_sha256": digest(coding_document),
                "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "contract_sha256": hashlib.sha256((ROOT / "schemas/contract.json").read_bytes()).hexdigest(),
                "skill_sha256": hashlib.sha256((ROOT / "SKILL.md").read_bytes()).hexdigest(),
                "taxonomy_sha256": hashlib.sha256((ROOT / "references/taxonomy-v0.1.md").read_bytes()).hexdigest(),
                "model_observation": manifest["model_observation"],
                "errors": [s["session_id"] + ":" + s["error_code"] for s in sessions if s["error_code"]]}
    if "model_context" in manifest:
        coverage["model_context"] = manifest["model_context"]
    check_schema(patterns, "patterns")
    check_schema(coverage, "coverage")
    return patterns, coverage


def csv_value(value):
    if isinstance(value, (list, dict)):
        return canonical(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def report(patterns, coverage):
    mode_label = "합성 자료 시험" if coverage['data_mode']=='synthetic' else "정규화 연구 세션 기록"
    lines = ["# 사용자 지시 패턴 추출 초안", "", mode_label+". 연구진 검토 전 초안이며 검증된 척도로 해석하지 않는다.", "",
             f"요청 {coverage['requested_sessions']}세션 / 과제 {coverage['requested_task_sessions']}세션 / 실제 읽음 {coverage['read_sessions']}세션.",
             f"포함 고유 사건 {coverage['included_events']}개, 관찰 사용자 사건 분모 {patterns['denominator']}개.",
             "전체 추출: " + ("승인된 공개 범위 확인" if coverage["complete_extraction"] else "확인하지 못함 — 누락·부분 범위 있음"), "",
             "| 세션 | 시도 상태 | 범위 상태 | 읽은 행 범위 | 누락 범위 | 잘린 발화 | 제외 | 원본 중복 |",
             "|---|---|---|---|---|---|---|---|"]
    for s in coverage["sessions"]:
        lines.append(f"| {s['session_id']} | {s['attempt_status']} | {s['status']} | {canonical(s['read_ranges'])} | {canonical(s['missing_ranges'])} | {len(s['truncated_refs'])} | {len(s['excluded'])} | {len(s['duplicates'])} |")
    lines += ["", "알 수 없는 전체량은 null이며 누락 범위 []가 완전성을 뜻하지 않는다. 행 번호와 근거 문자 범위는 패키지 intake 기준이다.", "",
              "| 관찰 분류 | 사건 수 | 관찰 사용자 분모 |", "|---|---|---|"]
    for c in patterns["counts"]:
        lines.append(f"| {c['label']} | {c['count']} | {c['denominator']} |")
    lines += ["", "복수 분류가 가능하다. 미관찰을 행동 없음으로 보지 않는다. 검증 요청·AI 진술·도구 실행 결과는 별개다.", "",
              f"판단 보류 {len(patterns['uncertainties'])}건. 근거와 관련 사건은 patterns.json/actions.csv의 내부 참조로 확인한다.",
              "원문·원본 ID는 출력에 복사하지 않았다. 모델 설정은 coverage.json의 확인 범위를 따른다.", "",
              "분석 범위: 세션 선택/누락, 잘림, 분모, 보류 판단, 기준 버전을 함께 기록했습니다.",
              "자동 형식 검증은 독립 코딩·연구적 타당성 검증을 대신하지 않는다.", ""]
    lines += mc.report_lines(coverage.get("model_context"))
    return "\n".join(lines)


def new_run(out_root):
    out_root = Path(out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex
    folder = out_root / name
    folder.mkdir(exist_ok=False)
    return folder


def build(manifest_path, codings_path, out_root):
    folder = new_run(out_root)
    try:
        patterns, coverage = derive(manifest_path, codings_path)
        coverage["run_id"] = folder.name
        coverage["created_at"] = datetime.now(timezone.utc).isoformat()
        check_schema(coverage, "coverage")
        write_json(folder / "patterns.json", patterns)
        write_json(folder / "coverage.json", coverage)
        with (folder / "actions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows({key: csv_value(a[key]) for key in CSV_FIELDS} for a in patterns["actions"])
        (folder / "report.md").write_text(report(patterns, coverage), encoding="utf-8")
        validate_run(folder, manifest_path, codings_path)
        write_json(folder / "integrity.json", {"files": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ["actions.csv", "patterns.json", "coverage.json", "report.md"]}})
    except (ContractError, OSError) as error:
        write_json(folder / "failure.json", {"status": "failed", "error_code": str(error) if isinstance(error, ContractError) else "filesystem_error", "run_id": folder.name})
        raise
    return folder


def validate_run(folder, manifest_path, codings_path):
    folder = Path(folder)
    require(not (folder / "failure.json").exists(), "failed_run_cannot_validate")
    patterns, coverage = derive(manifest_path, codings_path)
    actual_patterns = read_json(folder / "patterns.json")
    actual_coverage = read_json(folder / "coverage.json")
    check_schema(actual_patterns, "patterns")
    check_schema(actual_coverage, "coverage")
    require(actual_patterns == patterns, "patterns_source_mismatch")
    comparable = {k: v for k, v in actual_coverage.items() if k not in {"run_id", "created_at"}}
    require(comparable == coverage, "coverage_source_mismatch")
    require(actual_coverage.get("run_id") == folder.name, "run_identity_mismatch")
    with (folder / "actions.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames == CSV_FIELDS, "csv_header_mismatch")
        actual_rows = list(reader)
    expected_rows = [{key: csv_value(a[key]) for key in CSV_FIELDS} for a in patterns["actions"]]
    require(actual_rows == expected_rows, "csv_source_mismatch")
    require((folder / "report.md").read_text(encoding="utf-8") == report(patterns, coverage), "report_source_mismatch")
    if (folder / "integrity.json").exists():
        expected_hashes = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ["actions.csv", "patterns.json", "coverage.json", "report.md"]}
        require(read_json(folder / "integrity.json") == {"files": expected_hashes}, "integrity_mismatch")


def aggregate(run_paths, out_root):
    require(len(run_paths) == len({str(Path(p).resolve()) for p in run_paths}), "duplicate_run_path")
    variants, provenance = {}, []
    for path in run_paths:
        path = Path(path)
        require(not (path / "failure.json").exists(), "failed_run_cannot_aggregate")
        patterns = read_json(path / "patterns.json")
        coverage = read_json(path / "coverage.json")
        check_schema(patterns, "patterns")
        check_schema(coverage, "coverage")
        integrity = read_json(path / "integrity.json")
        require(integrity == {"files": {name: hashlib.sha256((path / name).read_bytes()).hexdigest() for name in ["actions.csv", "patterns.json", "coverage.json", "report.md"]}}, "aggregate_integrity_mismatch")
        require(patterns == calculate_patterns(patterns["actions"]), "aggregate_counts_mismatch")
        provenance.append({"run_id": coverage["run_id"], "dataset_namespace": coverage["dataset_namespace"], "patterns_sha256": digest(patterns), "complete_extraction": coverage["complete_extraction"]})
        for action in patterns["actions"]:
            key = action["event_id"]
            variants.setdefault(key, {})[digest(action)] = action
    conflicts = [{"event_id": key, "variants": list(value.values())} for key, value in variants.items() if len(value) > 1]
    resolved = [next(iter(value.values())) for value in variants.values() if len(value) == 1]
    output = {"skill_version": VERSION, "schema_version": SCHEMA_VERSION, "review_status": "draft",
              "source_runs": provenance, "unique_events": len(variants), "conflicts": conflicts,
              "resolved_patterns": calculate_patterns(resolved), "completeness": "not_inferred_across_runs"}
    folder = new_run(out_root)
    write_json(folder / "aggregate.json", output)
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["build", "validate"]:
        p = sub.add_parser(command)
        p.add_argument("--manifest", required=True)
        p.add_argument("--codings", required=True)
        p.add_argument("--out-root", default=str(ROOT / "runs")) if command == "build" else p.add_argument("--run", required=True)
    p = sub.add_parser("aggregate")
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--out-root", default=str(ROOT / "runs"))
    args = parser.parse_args()
    try:
        if args.command == "build":
            print(build(args.manifest, args.codings, args.out_root))
        elif args.command == "validate":
            validate_run(args.run, args.manifest, args.codings)
            print("VALID: schemas, source references, coverage, CSV/JSON/report and integrity")
        else:
            print(aggregate(args.runs, args.out_root))
    except (ContractError, OSError):
        print("FAILED: contract or filesystem check; inspect new run failure.json when present", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
