# 개별 참여자 관찰 추출·구조화 계약 v1.0.0 — 스킬 v0.4.0

스킬은 참여자 한 명이 지정한 과제 세션들에서 정보를 최대한 관찰해 구조화한다. 참여자 간 그룹핑, 정답지 채점, 성과 요인 역추적, 인터벤션 전략 개발은 이 스킬의 실행 범위가 아니다. 개별 출력은 그 후속 연구가 가능한 근거 자료다. 배정표·점수표·정답지를 참여자에게 요구하지 않는다.

## 추출해야 하는 정보

| 층 | 관찰 정보 | 남겨야 하는 근거 |
|---|---|---|
| 사용자 지시 내용 | 목표·대상·조건·출력 요구·명시 단계·위임 범위·통제 경계·검증 요청·교정 대상·재사용·질문 초점·평가 기준 참조 | 발화 ID와 직접 읽은 문자 범위 |
| 행동 모듈 | 한 사용자 발화의 분류 묶음과 다음 관찰 사용자 발화 전까지 AI·도구 사건 | 사용자 발화·뒤따른 사건 ID, 주체, 도구 성공/실패/중단 관찰 |
| 순서와 과정 | 세션 내 모듈 순서·인접 전환·반복, 앞뒤 관련 사건 참조 | 실제 원본 순번 또는 패키지 행 순서 표시 |
| 최종 관찰 결과 | 확인된 제출 결과 참조, 숫자 집계값, 확인된 정답 피드백 전후 경계 | 내부 결과 참조·세션/행 구간, 확인 못함 표시 |
| 품질과 환경 | 요청/읽은 범위·누락·잘림·코딩 보류·원본 중복·시각·모델 설정 | coverage와 출처 해시·확인 범위 |

모듈 경계는 **관찰 구간**이며 실제 실행 경계·인과 연결을 뜻하지 않는다. 같은 발화의 두 분류는 발화 단위 묶음이다. 발화 내 세부 행동의 명시 전후/병렬 관계는 [세부 행동 계약](fine-observations.md)에 따로 기록한다. 사용자가 명시하지 않은 단계 순서나 세션 간 실행 순서를 만들지 않는다. 사용자 요청·AI 진술·도구 실행 결과를 분리한다. 기록에 없는 심리·이해도·클릭·외부 파일 편집·시간은 추정하지 않는다.

원문을 연구 출력에 그대로 복사하지 않고 근거 연결된 추상화로 작성한다. 환자 정보·개인정보·실제 이름·연락처·사적 파일 경로를 상세 필드에 옮기지 않는다. 원문 대응표와 실제 원기록은 승인된 기관 내부에서 보관한다. 자동 가명화나 형식 검사는 안전한 익명화를 보장하지 않는다.

## instruction-details.json은 모델이 작성하는 추출 산출물

직접 원기록을 읽은 스킬 모델/검토자가 작성한다. 사용자가 손으로 세부 JSON을 작성하거나 배경 정보를 보충하는 단계가 아니다. Python은 내용을 해석하는 추출 모델이 아니고 작성한 값·필드·근거 범위를 검증하는 실행기다.

최상위 키는 structure_version="1.0.0", participant_id, sensitive_review="pending_human_review", entries다. 모든 포함된 고유 사용자 사건에 한 항목이 필요하며 AI·도구 사건을 넣지 않는다.

한 사건의 fields에는 아래 12개 키가 모두 들어간다. 각 값은 `null` 또는 관찰 항목 배열이다.

```json
{
  "event_id": "E-ACTUAL-EXTRACTION-EVENT-ID",
  "observed_text_length": 20,
  "fields": {
    "goal": [{
      "value": "정의된 대상의 건수를 집계하도록 요청",
      "evidence": [{"ref": "S-001/row-000001", "start": 0, "end": 10}]
    }],
    "target": null,
    "constraints": null,
    "output_requirements": null,
    "explicit_steps": null,
    "delegation_scope": null,
    "control_boundary": null,
    "verification_request": null,
    "correction_issue": null,
    "reuse_resume": null,
    "question_focus": null,
    "evaluation_reference": null
  }
}
```

이 항목은 필드 형식만 보여주는 가상 예다. ID·길이·범위·값은 실제 읽은 자료에서 작성한다. 코드포인트 기준 `[start,end)`이며 자기 사용자 발화를 직접 근거로 삼는다. observed_text_length는 모델/어댑터가 실제 읽은 정규화 문자열 길이다. 스크립트는 그 주장에 대한 범위를 검사하지만 환자/원문 파일을 열어 길이나 의미를 독립 확인하지 않는다.

- null: 읽지 못했거나 해당 내용을 판단할 근거가 부족함.
- []: 실제 읽은 범위에서 해당 내용이 관찰되지 않음. 실제 행동 부재나 개인 성향 부재를 뜻하지 않음.
- 항목 배열: 해당 필드에서 직접 관찰한 추상화와 근거. 각 value는 최대 800자이며 원문 인용 대신 관찰 내용만 요약한다.

explicit_steps 배열은 원문에 명시된 순서만 보존한다. 실행 사건의 시간순 배열이나 AI가 제안한 단계를 사용자의 단계 지시로 바꾸지 않는다. 필터 조건·집계 단위·출력 형식 등은 constraints/target/output_requirements에서 구체화하되 데이터 값·환자 사례를 복사하지 않는다.

## 개별 파일 포장

```powershell
& $pythonExe "$packageRoot\scripts\structure_session.py" --runs $individualRun --details $detailsFile --out-root "$packageRoot\runs"
```

동일 참여자의 여러 과제/재개 추출 폴더를 --runs에 지정할 수 있다. 다른 참여자가 포함되면 거부한다. 동일 event_id는 중복 제거하고 다른 코딩·매핑은 충돌로 남겨 중단한다. --details 없이 실행하면 상세 항목은 null이며 not_extracted_fields_unknown으로 표시한다. 상세 정보가 자동 추출됐다고 주장하지 않는다.

출력:

- session-structure.json: 사용자/AI/도구의 관찰 사건, 상세 지시 구조, 모듈 사전, 세션별 모듈·순서·전환·반복·미연결 초기 사건, 과제 단위, 전체 coverage, 모델 확인 범위, 관찰 결과, 출처 및 제한.
- instruction-details.json: 개별 사용자 지시의 상세 구조. 원문을 읽은 모델이 작성했는지 또는 미실행인지 구별한다.
- behavior-atoms.json, behavior-atoms.csv: 모델이 작성한 세부 행동·8속성·명시 관계·AI/도구 본문 관찰. `--atoms`로 입력하며 생략하면 미확인으로 보존한다.
- modules.csv: 같은 정보를 모듈 단위로 펼친 후속 분석용 표.
- report.md, integrity.json: 개별 범위·미확인 정보·검토 항목과 해시.

기존 actions.csv/patterns.json/coverage.json/report.md/integrity.json은 보존한다. 새 실행 폴더에 추가 구조화 산출물을 만들며 기존 실행을 덮어쓰지 않는다. extraction 모듈 출력의 skill_version은 0.1.0이며 개별 구조화/패키지 버전은 0.4.0이다. SKILL 지시 해시는 별도로 보존한다.

## 최종 결과 관찰 — 정답 판정 없이 보존

최종 제출 결과의 확인된 숫자를 task-result.json으로 정규화해 함께 보관할 수 있다. result_schema_version, result_id, participant_id, task_id, values, pre_feedback_window를 사용한다. 현재 숫자 계약은 비음수 정수 건수 또는 null이다. 관찰값의 정답 여부·근접 점수는 개별 스킬이 계산하지 않는다. 확인 못한 파일/값은 누락으로 남기며 환자 원자료를 읽어 다시 계산하지 않는다.

필드 형식은 후속 분석 문서의 task-result 예를 참고할 수 있으나 answer-key를 읽거나 grade_and_trace.py를 실행하지 않는다. 정답 피드백 경계는 근거가 있으면 보존하고 없으면 null이다. 기존 네 행동 추출 파일만으로 최종 집계값을 알고 있다고 주장하지 않는다. 실제 바이오닉의 최종 제출값 정규화 어댑터·파일/실행 도구 지원과 제출 연동은 아직 검증하지 않았다.

원천 의미 해석·민감정보 검토·분류 타당성은 사람이 검토할 대상이다. 구조 검증을 통과했다고 사람의 행동 해석이나 자동 익명화가 검증된 것은 아니다.
