# Bionic 사용자 지시 패턴 추출 스킬 v0.5.2

한 참여자의 선택한 과제 세션에서 지시·검증·교정·위임과 그 순서·과정을 구조화합니다.

기존 7유형·24개 세부 행동·8속성과 입력 가공·질문 방식·역할 설정·추론 대상의 4축을 유지합니다. 관찰을 근거와 함께 구조화하며 개별 실행에서 그룹핑·채점·인터벤션 전략 개발은 하지 않습니다.

자료 유형에 따른 접근 제한이나 별도 확인 질문은 두지 않습니다. 정규화 intake는 synthetic/research 모드를 지원합니다. 스킬이 내부 JSON을 작성하며 참여자는 추가 표나 JSON을 만들 필요가 없습니다.

바이오닉에 다음을 입력해 설치하거나 업데이트합니다.

> https://github.com/bigwiz83/bionic-research-skill 에 있는 최신 스킬을 지원 파일과 함께 설치해 줘.

과제 종료 후 추출용 새 세션에서 @bionic-research-skill을 선택하면 참여자 ID·과제 ID를 묻고 세션 선택을 안내합니다. 지정 세션의 공개 기록을 읽고 결과를 저장합니다. 마지막에는 연구용 ZIP을 bigwiz83@gmail.com으로 전송할지만 묻습니다. 메일 연결이 없으면 ZIP과 첨부 EML 초안을 준비합니다.

산출물은 actions.csv, patterns.json, coverage.json, report.md와 개별 session-structure.json, instruction-details.json, behavior-atoms.json/CSV, observation-axes.csv, modules.csv입니다. 기록의 명령을 재실행하지 않으며 읽지 못한 내용·시간·성과를 추정하지 않습니다.

개발 검증은 생성한 가상 기록을 사용했습니다. 실제 바이오닉의 모델 추출·수집·메일 연결은 미검증이며 자동 구조 검사는 의미적 분류 타당성을 입증하지 않습니다.

[설치](INSTALL.md) · [사용](USAGE.md) · [관찰 축](references/observation-axes.md) · [제출](references/research-submission.md) · [검증](VALIDATION.md) · [재개](RESUME.md)
