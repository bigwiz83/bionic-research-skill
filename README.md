# Bionic 사용자 지시 패턴 추출 스킬

한 참여자의 지정 과제 세션에서 사용자 지시 내용·근거·모듈 순서·AI/도구 사건·관찰 결과·누락을 구조화합니다.

## 바이오닉에서 설치

바이오닉에 다음 한 줄을 입력합니다.

> https://github.com/bigwiz83/bionic-research-skill 에 있는 스킬을 지원 파일과 함께 설치해 줘.

또는 `@Install Skill`을 선택하고 저장소 URL을 전달합니다. [공식 설치 안내](https://lmstudio.ai/docs/bionic/agent/skills).
설치 경로가 변경되어도 SKILL.md와 references/scripts/schemas를 함께 유지하세요.

## 참여자 사용

과제가 끝난 뒤 같은 프로젝트에서 추출용 새 세션을 만들고 `@bionic-research-skill`을 선택합니다.
긴 요청문은 필요 없습니다. 스킬이 참여자 ID·과제 ID를 묻고 분석할 세션을 선택하도록 안내합니다.
세션 목록 도구가 있으면 번호 목록을 사용하고, 없으면 `@` 세션 참조나 정확한 이름/ID로 지정합니다.
선택한 공개 기록의 열람 동의와 바이오닉의 접근 승인 후 추출합니다.

사용자가 JSON·배정표·평가표·정답지를 작성할 필요는 없습니다.
개별 스킬은 그룹핑·정답 판정·채점·인터벤션 전략 개발을 수행하지 않습니다.

v0.4.0은 7유형과 기존 상세 12항목에 더해 대상·방법·기준 등 세부 행동 8속성과 명시 순서·AI/도구 반응의 근거를 남깁니다.
마지막에 연구책임자 **bigwiz83@gmail.com**으로 전송할지 묻습니다. 동의하면 연구용 결과만 ZIP으로 묶어 연결된 첨부 지원 메일 도구 또는 설정된 TLS SMTP로 전송합니다.
메일 연결이 없으면 ZIP이 첨부된 EML 초안을 제공합니다. 자동 발송에는 최초 한 번 메일 연결이 필요하며 초안 생성은 발송이 아닙니다.
[세부 관찰 계약](references/fine-observations.md) · [메일 연결·제출 안내](references/research-submission.md)

## 산출물과 확인 범위

원천 추출은 actions.csv, patterns.json, coverage.json, report.md와 integrity.json을 남깁니다.
개별 상세 구조화는 session-structure.json, instruction-details.json, modules.csv와 검토 보고서를 남깁니다.
세부 행동은 behavior-atoms.json/behavior-atoms.csv, 제출은 research-patterns.zip과 delivery-state.json을 추가로 남깁니다.
모델이 승인된 기록을 읽어 추상화하며 Python은 근거·범위·구조를 검증합니다. 상세 입력이 없으면 미확인으로 유지합니다.
기록의 명령은 재실행하지 않으며 환자 원본 파일·개인 저장소를 직접 읽지 않습니다.

**개발·자동 검증에는 새로 만든 합성 자료만 사용했습니다.** 실제 바이오닉 등록·수집 어댑터·출력 저장의 전체 연결은 미검증입니다.
기존 extract.py 원천 intake 검증기는 synthetic 모드만 지원합니다. 연구 기록을 합성 자료로 거짓 표시하지 않습니다.
승인된 기관 내부에서 공식 도구로 수집·구조화하며 실제 어댑터 지원과 민감정보/의미 검토를 확인해야 합니다.

Python 3.10 이상 표준 라이브러리로 `python -B -m unittest discover -s tests -v`를 실행할 수 있습니다.
코드의 기존 추출/비교 모듈 버전과 배포 버전은 구분하며 배포 버전은 VERSION.json을 따릅니다.

[설치](INSTALL.md) · [사용](USAGE.md) · [검증](VALIDATION.md) · [재개 기록](RESUME.md)
