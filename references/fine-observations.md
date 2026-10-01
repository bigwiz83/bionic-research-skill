# 세부 행동·반응 관찰 계약 v1.1.0

기본 7유형과 기존 상세 12항목을 유지한다. 한 발화의 여러 행동을 atom으로 나누되 모듈(한 사용자 발화+뒤따른 사건)의 개수는 바꾸지 않는다. 모델이 직접 읽은 관찰을 작성하며 Python은 의미를 추출하지 않는다.

behavior-atoms.json: 최상위 atom_schema_version="1.1.0", participant_id, entries, responses. entries에는 모든 포함 사용자 사건, responses에는 모든 포함 AI/도구 사건을 한 번씩 기록한다. 기존 1.0.0의 22개 세부 유형 입력은 그대로 읽을 수 있다. 새 탐색 유형은 1.1.0으로 작성한다.

## 사용자 행동

사용자 항목은 event_id, observed_text_length, atoms, relations다. 미확인일 때 atoms/relations=null, 읽은 범위에 지시 행동이 없으면 atoms=[]/relations=[]다. 배열 위치는 실행 순서가 아니다.

atom 필드: atom_id(A-로 시작하는 고유 코드), category(7개 코드 또는 null), subtype, facets, evidence. subtype은 scripts/behavior_atoms.py의 SUBTYPES를 따른다. 해당 세부 유형을 관찰 못하면 other_explicit이고 기본 유형도 판단 못하면 category=null이다.

| 유형 | 세부 관찰 예 |
|---|---|
| 목표·조건 | 대상·조건·출력 지정·정보/문헌 탐색 |
| 작업 분해 | 작업 나누기·순서 지정 |
| 위임·통제 | 위임·범위 제한·승인 요구·중단 |
| 검증 요청 | 근거 제시·뒷받침 출처 탐색·원문 대조·재계산·중복/누락/예외/일관성 확인 |
| 오류 교정 | 오류 수정·누락 복구·조건 수정 |
| 재사용·재개 | 산출물 재사용·작업 재개 |
| 자료구조 파악 | 구조 확인 |

facets에는 8키를 모두 둔다: target(대상), method(방법), criterion(판단 기준), constraints(포함/제외/제약), requested_output(출력 요구), trigger_condition(실행 조건), control_boundary(위임/승인/중단 경계), prior_result_reference(이전 산출물 참조). 각 값은 null(미확인), [](읽은 범위에 명시 내용 없음), 또는 [{value,evidence}]다. value는 원문·환자정보를 복사하지 않은 최대 800자 추상화다.

evidence는 자기 발화의 {ref,start,end} 목록이다. Python Unicode code point 기준 [start,end)이며 observed_text_length는 모델이 읽은 정규화 문자열 길이의 주장이다. 자동 검사는 실제 길이·의미를 원문으로 독립 확인하지 않는다.

relations에는 같은 발화에서 원문이 명시한 관계만 {from_atom,to_atom,kind,evidence}로 기록한다. kind는 explicit_before/explicit_parallel이다. 단순 나열로 순서/병렬을 추정하지 않는다. 조건은 trigger_condition에 남긴다. 다른 발화·세션 간 관계를 생성하지 않으며 순환·병렬과 순서 모순은 거부한다.

## 정보·문헌 탐색과 검증의 경계

7대분류를 유지하고 이름 있는 세부 유형은 24개다(other_explicit 제외). 판단은 원문에 명시된 요청과 승인된 공개 맥락에 근거하며 목적·심리·검색 성공을 추정하지 않는다.

| 명시 요청의 합성 예 | 분류/세부 유형 | 구별 |
|---|---|---|
| “재발률 관련 논문을 찾아줘.” | goal_specification / information_search | 지정 주제의 정보·문헌 확보 |
| “이 주장에 근거가 되는 논문을 찾아줘.” | verification_request / supporting_reference_search | 특정 주장/결과를 뒷받침하는 출처 탐색 |
| “앞서 사용한 근거를 보여줘.” | verification_request / request_evidence | 이미 사용한 근거 제시; 검색을 요구했다고 만들지 않음 |
| “그 논문이 이 주장을 뒷받침하는지 대조해.” | verification_request / source_crosscheck | 출처 내용과 주장/결과의 대응 확인 |
| “레퍼런스 좀.”만 있고 맥락을 읽지 못함 | 보류/미확인 | 탐색인지 제시인지 검증인지 추정하지 않음 |

한 발화에서 탐색과 대조를 모두 명시하면 두 atom을 남긴다. 순서는 원문이 명시한 경우에만 관계로 기록한다. 출처 제한은 그 자체로 검증 요청이 아니며 일반 위임이 명시된 경우 기존 위임 기준을 함께 적용할 수 있다. 기존 원천 코딩은 자동 변경하지 않고 누락 분류는 불일치로 남긴다.

두 탐색 유형의 atom에는 search_details를 추가하고 다음 4키를 모두 둔다. 각 값은 기존 속성과 동일하게 null, [], 또는 [{value,evidence}]다. 각 근거는 자기 사용자 발화의 범위여야 한다. 읽지 못한 맥락·관찰되지 않은 검색어를 보충하지 않는다.

| search_details 키 | 기록 내용 |
|---|---|
| search_terms | 명시된 검색어·검색식의 안전한 정규화/추상화 |
| source_constraints | 요구한 출처 종류·기간·언어·포함/제외 조건 |
| selection_criteria | 출처를 선택할 때 요구한 관련성·품질 기준 |
| claim_reference | 근거 탐색 대상인 기존 주장/결과의 명시 참조; 주장 내용 미확인은 별도로 유지 |

탐색 대상은 facets.target, 검색 방법은 facets.method에도 관찰하며 8속성은 그대로 유지한다. 원문 전체 검색식·환자정보·개인 경로는 복사하지 않는다. AI가 스스로 만든 검색어·선정 기준은 사용자 필드에 넣지 않고 해당 AI/도구 response의 method 등으로 분리한다. 사용자 요청만으로 실제 검색·출처 발견·근거 타당성을 확정하지 않는다. 분석 단계에서는 요청을 재실행하거나 새로운 문헌을 검색하지 않는다.

다른 세부 유형에는 search_details를 넣지 않는다. 기존 1.0.0 입력에서 이 항목이 없는 것은 미수집이며 탐색이 없었다는 뜻이 아니다. CSV에도 search_details JSON을 보존한다. 출력 파일 이름과 제출 ZIP 허용 목록은 바뀌지 않는다.

## AI·도구 반응

response 항목은 event_id, observed_text_length, observations다. observations는 null/[]/[{aspect,value,evidence}], aspect는 action/method/output/limitation이다. 근거는 해당 AI/도구 사건 본문에만 연결한다. AI의 의향·완료 진술은 진술이고 도구 성공은 기록된 보고다. 실제 정답·독립 검증·사용자 요청 충족으로 바꾸지 않는다.

기존 모듈의 사건 ID로 반응을 연결하며 근거는 observation_window_not_proven_request_fulfillment다. 근거가 없으면 개별 atom에 어느 응답이 수행 결과인지 임의 배정하지 않는다. 기존 코딩과 세부 분류의 불일치는 fine_coding_mismatches로 보존한다.

```text
python scripts/structure_session.py --runs RESULT_FOLDER --details DETAILS_JSON --atoms ATOMS_JSON --out-root OUTPUT_FOLDER
```

모델이 상세 JSON을 작성한다. 새 실행에 session-structure.json, instruction-details.json, behavior-atoms.json, behavior-atoms.csv, modules.csv, report.md, integrity.json을 남긴다. --atoms 생략은 세부 관찰 미확인이며 추출 완료가 아니다.
