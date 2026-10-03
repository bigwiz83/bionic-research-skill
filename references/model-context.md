# 종료 후 모델·추론 수준·토큰 메타데이터 수집 — 1.0.0

이 스킬은 과제가 끝난 뒤 선택한 세션을 돌아본다. 실시간 설정 감시나 바이오닉 앱 변경은 수행하지 않는다. 세션 헤더가 단일 값으로 갱신된다는 사용자의 관찰을 고려하되, 해당 설치 버전의 실제 반환 형식과 값의 뜻은 공식 도구 반환에서 확인한다. 헤더의 단일 최신값만 확보했다면 과거 모델·파라미터 변경 이력을 복원할 수 없다.

## 수집과 해석

1. 선택한 과제 세션의 공식 메타데이터/Introspection 반환에서 마지막 저장 헤더의 모델명·추론 수준·토큰 표시와 제공된 파라미터를 읽는다. 헤더가 반환되지 않으면 not_available을 기록한다. 내부 DB나 설정 파일을 추측해서 탐색하지 않는다.
2. 원기록에 응답별 메타데이터가 실제 남아 있으면 그 응답 참조와 함께 별도로 수집한다. 마지막 헤더 값을 모든 응답에 채우지 않는다. 종료 후 헤더가 바뀌었을 가능성도 있으므로 마지막 저장 헤더를 '과제 종료 시 설정'이라고 단정하지 않는다.
3. 추출을 수행하는 모델의 설정은 공식 실행 메타데이터에서 확인된 경우 extraction_runtime으로 분리한다. 과제 세션의 헤더를 추출 모델의 설정으로 재사용하지 않는다. 사용자 발화의 '모델을 바꿨다'는 진술은 task_user_report로 구별하며 실제 적용 증거로 승격하지 않는다.
4. captured_at은 추출 중 해당 메타데이터를 읽은 시각이다. 시각을 실제 확인할 수 없으면 null이다. source_timestamp는 헤더의 저장/수정 시각 또는 응답 생성 시각처럼 원기록에 제공된 시각이며 없으면 null이다. 추출 시각을 과제 시각으로 바꾸지 않는다.
5. 토큰의 종류와 집계 범위를 구별한다. input_tokens/output_tokens/total_tokens/context_used_tokens는 뜻이 확인된 경우만 쓴다. 단순 '토큰 수'는 displayed_unknown으로 남기고 aggregation=unknown을 쓴다. 세션 누계와 응답별 사용량을 합산하거나 차감해 사용량을 만들지 않는다. 출력 한도는 parameters.max_output_tokens로 구별한다.
6. 선택한 세션마다 최신 헤더 한 개를 기록한다. 여러 세션을 선택했다면 세션별 헤더를 구분한다. 헤더만으로 사용자 변경 행동을 생성하지 않는다. 응답별 메타데이터는 별도로 실제 제공된 경우에만 보존하며 필수 입력이 아니다.

## 정규화 계약

manifest.json에 선택 필드 model_context를 둔다. 새 실행에서는 확인 시도 후 수집 상태를 반드시 작성한다. 기존 파일에서 필드가 없으면 구버전 미수집이며 관찰 부재가 아니다. Python은 메타데이터를 자동 수집하거나 의미를 추정하지 않고 모델/어댑터가 작성한 관찰을 검증한다.

- context_version: 1.0.0
- collection_status: observed(스냅샷 있음), not_available(시도했으나 확보 불가), not_collected(수집 미실행)
- snapshots: 각 관찰의 배열. snapshot_id는 MS- 가명, evidence_ref는 META- 가명이다. evidence_ref와 실제 반환/읽기 영수증의 대응은 내부 intake에만 둔다. 원본 ID·전체 헤더·인증 정보는 복사하지 않는다.
- scope: task_session_header / task_response / extraction_runtime / task_user_report
- session_id: 선택한 승인된 과제 세션 가명. extraction_runtime은 null이다.
- response_ref: task_response는 실제 읽은 AI 사건, task_user_report는 실제 읽은 사용자 사건의 패키지 참조. 헤더와 추출 실행은 null이다.
- captured_at / source_timestamp: 시간대가 있는 ISO 시각 또는 null
- model_id / reasoning_level: 확인된 식별자·추론 수준 표현 또는 null. 추론 수준을 temperature 등으로 변환하지 않는다.
- parameters: temperature, top_p, top_k, max_output_tokens, context_length, seed. 확인 못한 항목은 null이다. seed는 음수를 포함해 관찰된 정수를 보존한다.
- token_counts: {metric, aggregation, value} 목록. aggregation은 response/session/unknown이고 value는 관찰한 0 이상 정수다. []는 확인된 토큰 관찰값 없음이며 사용량 0을 뜻하지 않는다.

합성 형태 예시(실제 모델이나 바이오닉 반환 형식을 뜻하지 않음):

```json
{
  "context_version": "1.0.0",
  "collection_status": "observed",
  "snapshots": [{
    "snapshot_id": "MS-SYN-HEADER",
    "scope": "task_session_header",
    "session_id": "S-A",
    "response_ref": null,
    "evidence_ref": "META-SYN-HEADER",
    "captured_at": "2026-10-03T15:00:00+09:00",
    "source_timestamp": null,
    "model_id": "synthetic/task-model",
    "reasoning_level": "high",
    "parameters": {"temperature": null, "top_p": null, "top_k": null, "max_output_tokens": null, "context_length": null, "seed": null},
    "token_counts": [{"metric": "displayed_unknown", "aggregation": "unknown", "value": 12000}]
  }]
}
```

## 보존과 후속 비교

coverage.json.model_context, session-structure.json의 coverage/source_runs, 보고서와 기존 제출 ZIP에 보존한다. 응답별 참조가 없는 헤더는 모듈/응답의 사용 모델로 채우지 않는다. 최종 헤더만 있는 세션은 '최종 저장 헤더 기준'의 탐색 비교만 가능하며, 동일 모델로 전체 과제를 수행했다고 분류하지 않는다.

기존 model_observation은 유지하지만 과제/추출 역할과 시점이 미구분인 이전 관찰이다. 구버전 값을 새 역할로 자동 변환하지 않는다. 새 필드 수집의 완전성은 사건 본문 추출의 complete_extraction과 별개다. 실제 바이오닉에서 헤더·응답별 설정 반환이 가능한지는 설치 환경에서 확인해야 하며 이번 합성 검증으로 지원을 보증하지 않는다.
