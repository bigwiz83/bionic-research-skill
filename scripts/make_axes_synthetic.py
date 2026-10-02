"""Build an authored synthetic axis example, not a text classifier or human gold standard."""
import argparse
import copy
from pathlib import Path
from unittest.mock import patch
import extract as e
import behavior_atoms as b
import observation_axes as x
import structure_session as s
import submission as m
import make_process_synthetic as p

TEXT = {
    'goal_specification': '이 합성 자료는 제가 요약한 입력입니다. 자료 분석가 역할로 두 후보 설명을 비교하고 차이가 생긴 이유를 설명해 주세요.',
    'data_structure_inquiry': '자료 구조에서 집계 단위는 무엇인가요?',
    'task_decomposition': '문제 정의, 가설 생성, 평가 계획 순서로 나눠 주세요.',
    'verification_request': '두 후보가 같은 결과를 만들 것이라는 가설을 검증해 주세요. 조건을 바꾸면 결과가 어떻게 달라질까요?',
    'error_correction': '앞서 놓친 조건을 반영해 주세요.'}


def generate(out_root):
    root = Path(out_root)
    e.require(not root.exists(), 'axis_synthetic_target_exists')
    with patch.dict(p.TEXT, TEXT):
        runs, _ = p.generate(root/'synthetic-source')
    run = runs[0]
    value = s.analyze([run])
    doc = copy.deepcopy(value['behavior_atoms'])
    actions = {a['event_id']: a for a in value['observed_actions']}
    for i, row in enumerate(doc['entries']):
        action = actions[row['event_id']]
        row['observed_text_length'] = max(span['end'] for span in action['evidence'])
        row['atoms'] = [{'atom_id': f'A-AXIS-SYN-{i+1}', 'category': action['categories'][0],
            'subtype': 'other_explicit', 'facets': {name: None for name in b.FACETS},
            'evidence': copy.deepcopy(action['evidence'])}]
        row['relations'] = []
        row['observation_axes'] = {axis: [] for axis in x.AXES}

    def add(i, axis, code, abstract, basis='observable_expression'):
        row = doc['entries'][i]
        row['observation_axes'][axis].append({'code': code, 'value': abstract, 'basis': basis,
            'evidence': copy.deepcopy(row['atoms'][0]['evidence']), 'comparison_evidence': []})

    add(0, 'input_transformation', 'edited_summary', '요약한 입력이라는 사용자 진술; 원본 대조 미확인', 'explicit_statement')
    add(0, 'role_assignment', 'assigned_role', '자료 분석가 역할 지정')
    add(0, 'query_mode', 'alternative_comparison', '두 후보 설명의 비교 요청')
    add(0, 'query_mode', 'explanation', '차이가 발생한 이유 설명 요청')
    add(1, 'query_mode', 'factual', '집계 단위 확인 질문')
    for code, abstract in [('problem_definition', '문제 정의 작업 지정'),
                           ('hypothesis_generation', '가설 생성 작업 지정'), ('planning', '평가 계획 지정')]:
        add(2, 'reasoning_target', code, abstract)
    add(3, 'query_mode', 'hypothesis_probe', '명시된 동일 결과 가설의 검증 요청')
    add(3, 'query_mode', 'counterfactual_probe', '조건 변경 가정의 결과 질문')
    add(3, 'reasoning_target', 'hypothesis_evaluation', '동일 결과 가설 평가')
    # Unknown input transformation is distinct from observed absence on other axes.
    doc['entries'][3]['observation_axes']['input_transformation'] = None
    path = root/'authored-behavior-atoms.json'
    e.write_json(path, doc)
    structured = s.build([run], root/'individual', atom_path=path)
    bundle = m.prepare([run], structured, root/'submission')
    result = {'origin': 'entirely_invented_authored_observations_not_classifier_or_human_gold',
        'extraction_run': run, 'atom_input': str(path), 'structure_run': str(structured),
        'submission_run': str(bundle), 'external_email_sent': False,
        'semantic_validation_performed': False, 'bionic_live_verified': False}
    e.write_json(root/'example-result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-root', required=True)
    args = parser.parse_args()
    print(e.canonical(generate(args.out_root)))
