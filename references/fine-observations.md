# 세부 행동·반응 관찰 계약 v1.0.0

기본 7유형과 기존 상세 12항목을 유지한다. 한 발화의 여러 행동을 atom으로 나누되 모듈(한 사용자 발화+뒤따른 사건)의 개수는 바꾸지 않는다. 모델이 직접 읽은 관찰을 작성하며 Python은 의미를 추출하지 않는다.

behavior-atoms.json: 최상위 atom_schema_version="1.0.0", participant_id, entries, responses. entries에는 모든 포함 사용자 사건, responses에는 모든 포함 AI/도구 사건을 한 번씩 기록한다.

## 사용자 행동

사용자 항목은 event_id, observed_text_length, atoms, relations다. 미확인일 때 atoms/relations=null, 읽은 범위에 지시 행동이 없으면 atoms=[]/relations=[]다. 배열 위치는 실행 순서가 아니다.

atom 필드: atom_id(A-로 시작하는 고유 코드), category(7개 코드 또는 null), subtype, facets, evidence. subtype은 scripts/behavior_atoms.py의 SUBTYPES를 따른다. 해당 세부 유형을 관찰 못하면 other_explicit이고 기본 유형도 판단 못하면 category=null이다.

| 유형 | 세부 관찰 예 |
|---|---|
| 목표·조건 | 대상·조건·출력 지정 |
| 작업 분해 | 작업 나누기·순서 지정 |
| 위임·통제 | 위임·범위 제한·승인 요구·중단 |
| 검증 요청 | 근거 제시·원문 대조·재계산·중복/누락/예외/일관성 확인 |
| 오류 교정 | 오류 수정·누락 복구·조건 수정 |
| 재사용·재개 | 산출물 재사용·작업 재개 |
| 자료구조 파악 | 구조 확인 |

facets에는 8키를 모두 둔다: target(대상), method(방법), criterion(판단 기준), constraints(포함/제외/제약), requested_output(출력 요구), trigger_condition(실행 조건), control_boundary(위임/승인/중단 경계), prior_result_reference(이전 산출물 참조). 각 값은 null(미확인), [](읽은 범위에 명시 내용 없음), 또는 [{value,evidence}]다. value는 원문·환자정보를 복사하지 않은 최대 800자 추상화다.

evidence는 자기 발화의 {ref,start,end} 목록이다. Python Unicode code point 기준 [start,end)이며 observed_text_length는 모델이 읽은 정규화 문자열 길이의 주장이다. 자동 검사는 실제 길이·의미를 원문으로 독립 확인하지 않는다.

relations에는 같은 발화에서 원문이 명시한 관계만 {from_atom,to_atom,kind,evidence}로 기록한다. kind는 explicit_before/explicit_parallel이다. 단순 나열로 순서/병렬을 추정하지 않는다. 조건은 trigger_condition에 남긴다. 다른 발화·세션 간 관계를 생성하지 않으며 순환·병렬과 순서 모순은 거부한다.

## AI·도구 반응

response 항목은 event_id, observed_text_length, observations다. observations는 null/[]/[{aspect,value,evidence}], aspect는 action/method/output/limitation이다. 근거는 해당 AI/도구 사건 본문에만 연결한다. AI의 의향·완료 진술은 진술이고 도구 성공은 기록된 보고다. 실제 정답·독립 검증·사용자 요청 충족으로 바꾸지 않는다.

기존 모듈의 사건 ID로 반응을 연결하며 근거는 observation_window_not_proven_request_fulfillment다. 근거가 없으면 개별 atom에 어느 응답이 수행 결과인지 임의 배정하지 않는다. 기존 코딩과 세부 분류의 불일치는 fine_coding_mismatches로 보존한다.

```text
python scripts/structure_session.py --runs RESULT_FOLDER --details DETAILS_JSON --atoms ATOMS_JSON --out-root OUTPUT_FOLDER
```

모델이 상세 JSON을 작성한다. 새 실행에 session-structure.json, instruction-details.json, behavior-atoms.json, behavior-atoms.csv, modules.csv, report.md, integrity.json을 남긴다. --atoms 생략은 세부 관찰 미확인이며 추출 완료가 아니다.
