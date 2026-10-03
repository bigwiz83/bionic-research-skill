# 참여자 사용 v0.5.3

1. 과제 종료 후 같은 프로젝트에서 추출용 새 세션을 만듭니다.
2. @bionic-research-skill을 선택합니다.
3. 참여자 ID와 과제 ID를 답합니다.
4. 번호 목록 또는 세션 참조로 분석할 세션을 선택합니다. 실패·중단·재개도 포함할 수 있습니다.
5. 선택한 공개 기록의 열람과 바이오닉 자체 접근 절차를 진행합니다.
6. 결과 폴더·읽은 범위·누락을 확인합니다.
7. “이 ZIP을 연구책임자 bigwiz83@gmail.com으로 전송하시겠습니까?”에 답합니다. 동의한 경우 전송하며 거절·미응답이면 로컬 보관합니다.

자료 유형별 접근 제한·별도 확인 질문·참여자의 수동 JSON 작성 단계는 없습니다. 내부 manifest와 관찰 JSON은 모델이 작성합니다. research 모드의 정규화 기록을 합성 자료로 바꿔 표시하지 않습니다.

기존 7유형·24개 세부 행동·8속성과 입력 가공·질문 방식·역할 설정·추론 대상의 4축을 유지합니다. 관찰을 근거와 함께 구조화하며 개별 실행에서 그룹핑·채점·인터벤션 전략 개발은 하지 않습니다.

개발용 가상 예제를 새 경로에서 재현할 수 있습니다.

```text
python -B scripts/make_axes_synthetic.py --out-root NEW_SYNTHETIC_OUTPUT_FOLDER
python -B -m unittest discover -s tests -v
```

예제의 작성된 코딩은 실제 기록의 자동 분류기가 아닙니다. Python은 모델이 읽어 작성한 관찰의 구조·범위·근거를 검증합니다.

[세부 관찰](references/fine-observations.md) · [관찰 축](references/observation-axes.md) · [출력 계약](references/output-contract.md)

종료 후 선택 세션의 최종 저장 헤더·응답별 메타데이터·추출 실행 모델을 구분합니다. 모델명·추론 수준·토큰 의미·확인된 파라미터와 읽은 시각/원기록 시각을 보존하며 최신 헤더로 과거 설정을 채우지 않습니다. [모델 환경 수집 안내](references/model-context.md).
