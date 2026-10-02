"""Maintain the JSON Schema contract used by the portable validator."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ["goal_specification", "task_decomposition", "delegation_control", "verification_request", "error_correction", "reuse_resume", "data_structure_inquiry"]
REASONS = ["explicit_goal_or_constraint", "explicit_parts_or_order", "explicit_delegation_or_boundary", "explicit_evidence_or_check_request", "explicit_error_or_revision", "explicit_prior_result_or_resume", "explicit_structure_request"]


def obj(props, optional=()):
    return {"type": "object", "properties": props, "required": [k for k in props if k not in optional], "additionalProperties": False}


def string(pattern=None):
    return {"type": "string", **({"pattern": pattern} if pattern else {})}


def enum(values):
    return {"enum": values}


def arr(items, minimum=0, unique=False):
    return {"type": "array", "items": items, "minItems": minimum, "uniqueItems": unique}


def nullable(schema):
    return {**schema, "type": [schema["type"], "null"]}


def reference(name):
    return {"$ref": "#/$defs/" + name}


def contract():
    boolean = {"type": "boolean"}
    integer = {"type": "integer", "minimum": 0}
    positive = {"type": "integer", "minimum": 1}
    nullable_integer = nullable(integer)
    timestamp = nullable({"type": "string", "format": "date-time"})
    sid = string(r"S-[A-Z0-9-]{1,48}")
    source_ref = string(r"S-[A-Z0-9-]{1,48}/row-[0-9]{6,}")
    event_id = string(r"E-[0-9a-f]{64}")
    hash_value = string(r"[0-9a-f]{64}")
    label_list = arr(enum(LABELS), unique=True)
    reasons = arr(enum(REASONS), unique=True)
    definitions = {}
    definitions["span"] = obj({"ref": source_ref, "start": integer, "end": positive})
    definitions["model"] = obj({"model_id": nullable(string(r"[A-Za-z0-9_./:-]{1,128}")),
                                "model_id_confirmed": boolean, "settings_confirmed": boolean,
                                "temperature": nullable({"type": "number", "minimum": 0}),
                                "top_p": nullable({"type": "number", "minimum": 0, "maximum": 1}),
                                "context_length": nullable(positive)})
    definitions["session"] = obj({"session_id": sid, "purpose": enum(["task", "analysis"]), "approved": boolean,
        "attempt_status": enum(["completed", "failed", "cancelled", "interrupted", "resumed", "unknown"]),
        "access": enum(["available", "missing_access", "unreadable", "missing_record"]),
        "events_file": nullable(string()), "total_events": nullable_integer, "end_verified": boolean,
        "analysis_start_index": nullable(positive), "read_receipts": arr(string())})
    definitions["manifest"] = obj({"schema_version": {"const": "1.0.0"}, "data_mode": enum(["synthetic", "research"]),
        "dataset_namespace": string(r"(?:SYN|DS)-[A-Z0-9-]{1,64}"), "participant_id": string(r"P-[A-Z0-9-]{1,48}"),
        "task_id": string(r"T-[A-Z0-9-]{1,48}"), "adapter": enum(["synthetic-export-v1", "bionic-introspection-normalized-unverified"]),
        "model_observation": reference("model"), "sessions": arr(reference("session"), 1)})
    definitions["event"] = obj({"source_index": positive, "source_id": nullable(string()),
        "source_sequence": nullable_integer, "timestamp": timestamp, "actor": enum(["user", "assistant", "tool", "system"]),
        "kind": enum(["user_message", "assistant_statement", "tool_request", "tool_success", "tool_failure", "tool_cancelled", "system_event", "compaction", "private"]),
        "visibility": enum(["public", "private"]), "phase": enum(["task", "analysis"]), "content_complete": boolean, "text": string()})
    definitions["events"] = arr(reference("event"))
    definitions["coding"] = obj({"source_ref": source_ref, "decision": enum(["coded", "deferred", "unclassified"]),
        "categories": label_list, "criterion_codes": reasons, "ambiguity": enum([None, "ambiguous_intent", "insufficient_context"]),
        "evidence": arr(reference("span"), 1), "related_refs": arr(source_ref, unique=True)})
    definitions["codings"] = obj({"taxonomy_version": {"const": "instruction-patterns-0.1.0"}, "entries": arr(reference("coding"))})
    definitions["action"] = obj({"event_id": event_id, "participant_id": string(r"P-[A-Z0-9-]{1,48}"),
        "task_id": string(r"T-[A-Z0-9-]{1,48}"), "session_id": sid, "source_index": positive,
        "source_sequence": nullable_integer, "actor": enum(["user", "assistant", "tool", "system"]),
        "observation": string(), "categories": label_list, "decision": enum(["coded", "deferred", "unclassified", "not_user"]),
        "ambiguity": enum([None, "ambiguous_intent", "insufficient_context"]), "criterion_codes": reasons,
        "source_ref": source_ref, "ref_kind": {"const": "package_row"}, "timestamp": timestamp,
        "content_complete": boolean, "evidence": arr(reference("span")), "related_refs": arr(source_ref, unique=True)})
    definitions["count"] = obj({"category": enum(LABELS), "label": string(), "criterion": enum(REASONS),
        "count": integer, "denominator": integer, "proportion": nullable({"type": "number", "minimum": 0, "maximum": 1}),
        "event_ids": arr(event_id, unique=True)})
    definitions["patterns"] = obj({"skill_version": {"const": "0.1.0"}, "schema_version": {"const": "1.0.0"},
        "taxonomy_version": {"const": "instruction-patterns-0.1.0"}, "review_status": {"const": "draft"},
        "denominator_definition": {"const": "included_unique_public_user_events"}, "denominator": integer,
        "counts": arr(reference("count"), 7), "uncertainties": arr(obj({"event_id": event_id, "source_ref": source_ref, "reason": enum(["ambiguous_intent", "insufficient_context"])})),
        "unclassified_event_ids": arr(event_id, unique=True), "actions": arr(reference("action"))})
    definitions["coverage_session"] = obj({"session_id": sid,
        "attempt_status": enum(["completed", "failed", "cancelled", "interrupted", "resumed", "unknown"]),
        "approval": boolean, "purpose": enum(["task", "analysis"]),
        "status": enum(["complete_public_scope", "partial", "excluded_analysis_session", "missing_approval", "missing_access", "unreadable", "missing_record"]),
        "total_events": nullable_integer, "read_ranges": arr(arr(positive, 2)), "read_rows": integer,
        "included_events": integer, "missing_ranges": arr(arr(positive, 2)),
        "excluded": arr(obj({"ref": source_ref, "reason": enum(["private_content", "compaction_summary", "after_extraction_start"])})),
        "duplicates": arr(obj({"ref": source_ref, "canonical_ref": source_ref})), "truncated_refs": arr(source_ref, unique=True),
        "unknown_timestamps": integer, "end_verified": boolean, "receipt_sha256": nullable(hash_value),
        "error_code": enum([None, "json_unreadable_or_invalid"])})
    definitions["coverage"] = obj({"skill_version": {"const": "0.1.0"}, "schema_version": {"const": "1.0.0"},
        "taxonomy_version": {"const": "instruction-patterns-0.1.0"}, "data_mode": enum(["synthetic", "research"]),
        "dataset_namespace": string(r"(?:SYN|DS)-[A-Z0-9-]{1,64}"), "adapter": enum(["synthetic-export-v1", "bionic-introspection-normalized-unverified"]),
        "complete_extraction": boolean, "requested_sessions": positive, "requested_task_sessions": integer,
        "read_sessions": integer, "included_events": integer, "included_user_events": integer,
        "sessions": arr(reference("coverage_session"), 1), "source_hashes": arr(obj({"session_id": sid, "sha256": hash_value})),
        "manifest_sha256": hash_value, "codings_sha256": hash_value, "model_observation": reference("model"),
        "implementation_sha256": hash_value, "contract_sha256": hash_value, "skill_sha256": hash_value, "taxonomy_sha256": hash_value,
        "sensitive_review": {"const": "pending_human_review"}, "errors": arr(string()),
        "run_id": string(r"run-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}"), "created_at": {"type": "string", "format": "date-time"}},
        optional=["run_id", "created_at", "sensitive_review"])
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:bionic-research-skill:1.0.0",
            "title": "Bionic normalized synthetic and research session intake and output contract", "$defs": definitions}


if __name__ == "__main__":
    target = ROOT / "schemas/contract.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(contract(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
