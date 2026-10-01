# 바이오닉 수집 어댑터 계약

2026-09-30 공식 문서 확인: [Skills](https://lmstudio.ai/docs/bionic/agent/skills), [Introspection](https://lmstudio.ai/blog/introducing-introspection), [Projects and Sessions](https://lmstudio.ai/docs/bionic/projects-and-sessions).

공식 문서는 Settings → Skills의 `SKILL.md` 등록, `@`의 스킬·세션 참조, 다른 세션 읽기의 승인, 저장 원기록 검색 및 발췌 뒤 선택 읽기를 설명한다. 문서에서 전체 로그 내보내기의 고정 JSON 계약이나 공개 도구 함수명을 확인하지 않았다. 현재 구현은 이 문서를 근거로 설계한 **정규화 intake 어댑터**이며 바이오닉 내부 저장소를 직접 파싱하지 않는다.

실제 실행 환경에서 기본 Introspection 안내와 반환 필드를 확인한다. 승인된 세션만 탐색하고 반환 결과를 아래 규칙으로 정규화한다. 검색 발췌만으로 전체 읽기를 선언하지 않는다. 검색 결과가 없다는 사실은 행동 없음의 증거가 아니다.

- 세션별 가명 alias를 `S-...`, 참여자 `P-...`, 과제 `T-...`로 둔다. 원본 제목·개인 식별 ID는 내부 대응표에만 둔다.
- 각 공개 사건을 `source_index` 순서로 배치하고 `source_id`에는 실제 ID가 반환된 경우만 기록한다. `source_index`는 이 패키지의 intake 참조 번호이며 원본 순번이라고 주장하지 않는다.
- 원본 파일을 스크립트가 모두 로드했더라도 모델 도구 출력이 잘렸으면 실제 모델이 확인한 발췌만 별도 intake에 둔다. 원본 파일의 `content_complete=true`를 모델의 전체 읽기 증거로 승계하지 않는다. 서로 떨어진 문자 범위는 영수증에 기록하고 근거에 쓰는 정규화 문자열과 그 실제 원문 구간을 대응시킨다.
- 사건의 전체 공개 본문을 읽었을 때만 `content_complete=true`로 둔다. 읽은 일부 발췌는 false다. 원기록 시각이 반환되지 않으면 `timestamp=null`을 쓴다.
- `total_events`는 승인 범위의 원기록 전체 사건 수를 실제 확인했을 때만 숫자로 둔다. 알 수 없으면 null. `end_verified`는 전체 사건 수와 모든 사건의 본문 읽기 및 기록 끝을 확인한 경우만 true. 사용한 도구·읽은 구간·기록 끝 확인은 `read_receipts`에 내부 기록한다. 외부 출력은 이 기록의 해시와 존재 여부만 포함한다.
- 부분 문자 범위를 읽을 때 정규화 본문은 실제 읽은 문자열만 담는다. 코딩의 `start/end`는 이 문자열 기준 0부터 시작하는 Python Unicode code point 범위이며 끝은 제외한다. 전체 원본 문자 위치와 동일하다고 하지 않는다.
- private 사고를 요청하지 않는다. 수집된 사건에 private 표시가 있으면 포함하지 않는다. compaction 요약은 `kind=compaction`, 근거에서 제외한다. 요약에만 나타난 과거 사건을 새 사건으로 만들지 않는다.
- 추출 시작 경계를 확인할 수 있으면 `analysis_start_index`로 기록한다. 경계 뒤 사건과 `phase=analysis` 사건은 제외한다. 분석용 세션은 `purpose=analysis`로 두고 원기록 파일을 읽지 않는다.
- 접근 실패, 거부, 잘림, 누락 범위는 세션별로 남긴다. 알 수 없는 총량·ID·시각·모델 설정은 null/unknown으로 둔다.

아직 확인하지 않은 사항: 바이오닉 데스크톱의 실제 스킬 등록, 지원 파일을 함께 읽는 방식, 합성 과제 세션의 실제 Introspection 반환, 실제 모델 반복 분류 변동, 장기 세션 끝 확인. [LIVE-BIONIC-CHECKLIST.md](../LIVE-BIONIC-CHECKLIST.md)에 시험 절차가 있다. 이 불확실성이 해소되기 전 실자료 어댑터를 검증 완료로 표시하지 않는다.
