# 잠정 분류 기준 v0.1.0

기준 ID `instruction-patterns-0.1.0`. 문헌으로 검증된 성향 척도가 아닌 관찰 코딩 후보다. 단위는 사용자 발화/사건이며 앞뒤 공개 응답·도구 사건을 근거로 연결한다. 단일 발화에 여러 분류를 붙일 수 있어 분류 합계가 사용자 사건 수보다 클 수 있다.

| 분류 | 판단 기준 코드 | 포함 | 경계·반례 |
|---|---|---|---|
| `goal_specification` 목표 구체화 | `explicit_goal_or_constraint` | 결과 형태·범위·대상·조건의 명시/추가 | 일반 위임만으로 구체적 목표라고 하지 않음 |
| `task_decomposition` 작업 분해 | `explicit_parts_or_order` | 항목·단계·순서로 작업을 나누라는 지시 | AI가 스스로 만든 단계는 사용자 분해가 아님 |
| `delegation_control` 위임·통제 | `explicit_delegation_or_boundary` | 맡기는 범위·진행 승인·중단·제한 | ‘알아서 해줘’는 위임이며 검증 요청은 아님 |
| `verification_request` 검증 요청 | `explicit_evidence_or_check_request` | 근거·대조·누락·정확성 검사를 명시적으로 요구 | AI의 자율 확인·도구 성공은 사용자 검증 요청이 아님 |
| `error_correction` 오류 교정 | `explicit_error_or_revision` | 잘못되거나 빠진 결과·조건을 짚고 수정 요구 | 단순 새 조건인지 오류 교정인지 모호하면 보류 |
| `reuse_resume` 이전 결과 재사용·재개 | `explicit_prior_result_or_resume` | 앞선 결과·중간 산출물을 이어 쓰거나 중단 지점 재개 요구 | 동일 문구 반복만으로 재개라고 하지 않음 |
| `data_structure_inquiry` 자료구조 파악 | `explicit_structure_request` | 자료의 시트·열·구조를 먼저 살펴달라는 요구 | AI가 자율 탐색한 것은 사용자 행위가 아님 |

기존 D15a A/C22/AR-05/AR-09에서 정한 ‘AI 초안 + 연구진 확인’과 자료구조 파악·AI 위임·원문 대조 요구·결과 검토/수정·오류 대응 예시를 반영했다. 새 후보와 기존 영역은 일대일 확정 대응이 아니며 `data_structure_inquiry`를 보존해 기존 예시를 누락하지 않는다.

분류할 수 없는 공개 사용자 발화는 `decision=unclassified`, 분류·판단 코드 없이 남긴다. 해석이 애매하면 `decision=deferred`, `ambiguity=ambiguous_intent` 또는 `insufficient_context`로 남긴다. 관찰 못한 사건은 생성하지 않고 coverage에 누락을 남긴다. 잘린 발화는 기본적으로 `deferred/insufficient_context`로 처리한다.

사용자 아닌 사건에는 사용자 패턴 분류를 붙이지 않는다. 공개 AI 답변은 `assistant_statement`, 도구 요청/성공/실패/중단은 각각 `tool_request`, `tool_success`, `tool_failure`, `tool_cancelled`로 관찰 유형만 남긴다. AI가 ‘확인 완료’라고 말한 경우는 진술이며 독립 실행 검증이 아니다. `related_refs`는 공개 맥락 관계이며 인과성·요청 충족 판정을 뜻하지 않는다.

분모는 실제 읽고 포함한 고유 사용자 사건 수다. 못 읽은 세션·부분 구간까지 포함한 참여자 전체 행동 비율을 계산하지 않는다. 분모가 0이면 비율은 `null`이다. 확정률·인지시간·프롬프트 품질점수는 산출하지 않는다.
