"""Validate retrospective model metadata; never reconstruct settings from a final header."""


def validate(context, sessions, events, require):
    if context is None:
        return
    snapshots = context["snapshots"]
    require((context["collection_status"] == "observed") == bool(snapshots), "model_context_status")
    require(len({s["snapshot_id"] for s in snapshots}) == len(snapshots), "model_snapshot_duplicate_id")
    headers = [s["session_id"] for s in snapshots if s["scope"] == "task_session_header"]
    require(len(set(headers)) == len(headers), "one_latest_header_per_session")
    allowed = {s["session_id"] for s in sessions if s["purpose"] == "task" and
               s.get("approved", s.get("approval", False)) and
               s.get("access", "available") == "available"}
    for snapshot in snapshots:
        scope, sid, ref = snapshot["scope"], snapshot["session_id"], snapshot["response_ref"]
        if scope == "extraction_runtime":
            require(sid is None and ref is None, "extraction_model_not_task_session")
        else:
            require(sid in allowed, "model_snapshot_session_not_selected")
        if scope == "task_session_header":
            require(ref is None, "final_header_cannot_attribute_response")
        elif scope in {"task_response", "task_user_report"}:
            require(ref in events and events[ref]["session_id"] == sid, "model_snapshot_ref_not_read")
            actor = "assistant" if scope == "task_response" else "user"
            require(events[ref]["actor"] == actor, "model_snapshot_actor_mismatch")
        metrics = [(t["metric"], t["aggregation"]) for t in snapshot["token_counts"]]
        require(len(set(metrics)) == len(metrics), "model_snapshot_duplicate_token_metric")


def report_lines(context):
    lines = ["", "모델·추론 수준·토큰 관찰:"]
    if context is None:
        return lines + ["- 구버전 model_observation은 과제 모델/추출 모델의 구분이 미확인입니다. 과거 응답 설정으로 승계하지 않습니다."]
    lines.append("- 수집 상태: " + context["collection_status"] + ". captured_at은 종료 후 메타데이터를 읽은 시각이며 수행 시각이 아닙니다.")
    for s in context["snapshots"]:
        tokens = ", ".join(f"{t['metric']}({t['aggregation']})={t['value']}" for t in s["token_counts"]) or "미확인"
        settings = ", ".join(f"{k}={v}" for k, v in s["parameters"].items() if v is not None) or "미확인"
        lines.append(f"- {s['snapshot_id']} / {s['scope']} / 세션 {s['session_id'] or '해당 없음'} / "
                     f"응답 참조 {s['response_ref'] or '없음'}: 모델 {s['model_id'] or '미확인'}, "
                     f"추론 수준 {s['reasoning_level'] or '미확인'}, 토큰 {tokens}, 설정 {settings}; "
                     f"읽은 시각 {s['captured_at'] or '미확인'}, 원기록 시각 {s['source_timestamp'] or '미확인'}.")
    lines.append("- 세션 헤더는 마지막 저장값 관찰이며 과제 전체의 설정·변경 이력·응답별 사용값을 보증하지 않습니다. 토큰 종류/집계 범위 미확인은 사용량·한도로 바꾸지 않습니다.")
    return lines
