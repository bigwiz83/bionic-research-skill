# 발화별 관찰 축 계약 1.0.0 — v0.5.0

기본 7유형·24개 세부 행동·8속성·탐색 상세는 유지한다. 관찰 축은 행동 atom이 아닌 **각 사용자 발화**에 붙인다. 자료만 붙여 넣은 발화처럼 atoms=[]인 사건에도 관찰 축을 작성할 수 있다. 한 발화가 여러 질문·추론 대상을 포함하면 복수 값을 기록한다. 축을 붙여도 사용자 모듈 수와 원기록 순서는 바뀌지 않는다.

모델은 승인된 공개 기록을 읽어 작성하고 Python은 구조·참조를 검증한다. 단어 매칭이나 아래 합성 예제를 실제 분류기로 사용하지 않는다. 원문을 재실행하거나 입력 자료 파일을 새로 열지 않는다. 발화가 질문형 문장이 아니어도 명시된 설명·가설·비교 요청을 관찰할 수 있다.

## 값과 판단 경계

| 축 | 코드 | 관찰 기준 |
|---|---|---|
| input_transformation | verbatim / edited_summary / mixed / other_explicit | 원문 전달 / 편집·요약 입력 / 원문과 가공 입력 혼합 / 그 밖의 명시 방식. 출력 요약 요청과 구별 |
| query_mode | factual | 사실·수치·정의 등 정보 확인 요청 |
| query_mode | explanation | 이유·기전·설명 요청 |
| query_mode | hypothesis_probe | 명시된 가설·가능성·반례를 평가·시험하도록 요청 |
| query_mode | counterfactual_probe | 조건을 바꾼 가정에서의 결과를 질의 |
| query_mode | alternative_comparison | 여러 대안·설명의 차이·장단점 비교 요청 |
| query_mode | task_requirement_aligned | 확인 가능한 과제/평가 요구 항목과 질문의 대응. 구조화된 질문이나 단계 나누기만으로 코딩하지 않음 |
| query_mode | other_explicit | 위 구분에 맞지 않는 명시 질문 방식; 모호한 경우는 null |
| role_assignment | assigned_role | AI에게 지정한 역할·관점. 작업 위임, 말투/서식 요구와 구별 |
| reasoning_target | problem_definition / priority_setting | 문제 정의·판단 범위 / 중요도·우선순위·재평가 |
| reasoning_target | hypothesis_generation / hypothesis_evaluation | 후보 설명·가설 생성 / 가설 타당성 평가 |
| reasoning_target | judgement / planning / self_reflection / other_explicit | 판단 / 계획 / 자신의 지식 부족·편향을 명시한 성찰 / 그 밖의 명시 추론 대상 |

문헌 검색은 기존 information_search 또는 supporting_reference_search로 남긴다. 근거 제시는 request_evidence, 원문 대조는 source_crosscheck를 유지한다. 검색·검증이라는 이유만으로 hypothesis_probe를 추가하지 않는다. “왜 그런가”는 질문 방식이고 “어떤 가설을 검증하는가”는 추론 대상으로 별도로 기록할 수 있다. self_reflection은 사용자가 자신의 한계를 명시한 경우에만 기록하며 오류 교정·자료 누락·AI의 성찰을 사용자 자기 성찰로 바꾸지 않는다.

입력 원본을 읽지 못했는데 편집·원문 입력을 주장하지 않는다. 사용자가 “제가 요약했습니다”라고 명시하면 **사용자 진술**로 기록할 수 있지만 원본 대조 확인으로 바꾸지 않는다. 출력 요약을 요구한 것만으로 요약 입력이 되지 않는다. 과제 요구 대응 역시 사용자의 명시 진술과 실제 과제 항목 대조를 구별한다. 관찰되지 않은 역할·질문을 AI 응답에서 역추정하지 않는다.

## JSON

새 behavior-atoms.json의 atom_schema_version은 **1.2.0**이다. entries의 모든 사용자 행에 observation_axes를 넣고 위 4축을 모두 둔다. 기존 1.0.0/1.1.0은 그대로 읽으며 관찰 축은 **미수집/미확인**으로 해석한다. 과거 파일에 []를 채워 넣거나 기존 분류를 다시 쓰지 않는다.

각 축의 값은 null(자료/맥락을 확인 못했거나 판단 보류), [](해당 축을 검토한 읽은 범위에서 관찰 없음), 또는 아래 항목의 배열이다. atoms=null이어도 읽은 발화에서 관찰 축을 별도로 추출할 수 있다. 본문 전체를 읽지 못한 사건의 []는 읽은 부분만의 관찰 부재이며 전체 사건에서의 부재가 아니다.

```json
{
  "code": "explanation",
  "value": "두 합성 결과의 차이가 발생한 이유 설명 요청",
  "basis": "observable_expression",
  "evidence": [{"ref": "S-SYN-01/row-000001", "start": 0, "end": 10}],
  "comparison_evidence": []
}
```

위 ref와 문자 범위는 형식 예시다. 실제 실행에서는 읽은 사건과 실제 범위로 교체한다. value는 최대 800자의 안전한 추상화이며 원문·개인 경로를 복사하지 않는다. evidence는 자기 사용자 발화의 [start,end) 문자 범위다.

| basis | 의미 |
|---|---|
| explicit_statement | 사용자 본인의 명시 진술·자기 보고. 그 진술의 사실 여부는 미확인 |
| observable_expression | 발화 자체에 관찰 가능한 질문·역할·추론 요청. 입력 가공이나 과제 요구 대응 확인에 사용하지 않음 |
| observed_comparison | 승인 범위에서 이미 읽은 앞선 공개 사건과 직접 대조. comparison_evidence 필수 |

comparison_evidence도 {ref,start,end} 배열이다. 같은 참여자·과제·세션의 **앞선 사용자/AI/도구 사건**이어야 하며 그 본문의 observed_text_length가 확인되어야 한다. 후속 AI 답변, 다른 세션, 지정 범위 밖 문서, 읽지 않은 원본을 대조 근거로 쓸 수 없다. 원본이 별도 파일로만 존재하거나 다른 세션에 있어 이 계약으로 대조할 수 없으면 null 또는 자기 보고로 남긴다. explicit_statement/observable_expression의 comparison_evidence는 []다. 비교 근거 링크가 있다고 Python이 내용 일치·요약 충실도를 확인한 것은 아니다.

## 출력과 과정 비교 준비

- behavior-atoms.json과 session-structure.json, 각 사용자 모듈에 관찰 축을 보존한다.
- observation-axes.csv는 **모든 사용자 사건을 한 행씩** 담는다. atom이 없거나 미확인인 사건도 빠지지 않는다. 각 축은 JSON 셀이며 근거와 basis를 보존한다.
- 보고서에 발화별 코드·basis와 축별 분모/미확인/관찰 없음/관찰값 있음을 표시한다. 코드별 빈도는 동일 발화에서 같은 코드를 중복 집계하지 않는다. 복수 코드는 서로 중복되므로 합계가 사용자 사건 수를 넘을 수 있다.
- 세션별 기존 모듈 순서에서 각 축의 이동·반복을 후속 분석할 수 있다. 발화 내 배열 순서, 같은 발화의 복수 축에서 새 행동 순서를 만들지 않는다. 세션 사이를 이어 붙이거나 소요시간·인과·성과를 추정하지 않는다.
- 새 CSV도 연구용 제출 ZIP에 포함한다. 이전 버전의 구조화 결과 ZIP도 계속 준비할 수 있다. 전송은 기존 별도 동의 절차를 따른다.

## 문헌 근거의 범위

Healy 등(2026), Human–AI collaboration in clinical reasoning: a UK replication and interaction analysis, DOI [10.1515/dx-2025-0176](https://doi.org/10.1515/dx-2025-0176), Table 1: 원문/편집 입력, 과제 평가 항목 대응/개념 탐색/단순 사실 질문, 역할 설정의 6코드가 입력·질문·역할 축의 출발점이다. explanation·hypothesis_probe·counterfactual_probe·alternative_comparison은 논문의 개념 탐색을 더 나눈 **우리의 관찰 후보**이며 논문에 동일한 독립 코드로 검증된 것이 아니다. 논문의 프롬프트 유형별 성과 차이는 통계적으로 유의하지 않았다.

McBee 등(2019), Use of clinical reasoning tasks by medical students, DOI [10.1515/dx-2018-0077](https://doi.org/10.1515/dx-2018-0077), Table 1: 4영역·26개 임상추론 과제를 참고해 추론 대상 축을 일반 과제에도 쓸 수 있게 추상화했다. 26개 과제의 직접 복제나 검증된 인지능력 척도가 아니다. 연구에서 추론의 순서·반복을 기술했지만 행동–정답률 연관성을 입증하지 않았다.

축 코드는 문헌을 참고한 연구 초안이다. 실제 의미 분류의 독립 평가자 일치도, 과제별 타당성, 실제 성과의 연관성은 후속 연구로 확인한다. Python 합성 검사는 이를 대신하지 않는다.
