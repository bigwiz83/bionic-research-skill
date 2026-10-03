"""Package one participant's observable instructions and process; no group analysis or scoring."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import sys

import extract as e
import cohort as c
import compare_processes as p
import grade_and_trace as g
import behavior_atoms as b
import observation_axes as x

VERSION="0.5.3"
DETAIL_FIELDS=["goal","target","constraints","output_requirements","explicit_steps",
    "delegation_scope","control_boundary","verification_request","correction_issue",
    "reuse_resume","question_focus","evaluation_reference"]


def details(path,participant_id,users,known):
    if path is None:
        return {"structure_version":"1.0.0","participant_id":participant_id,
            "sensitive_review":"pending_human_review","entries":[
                {"event_id":a["event_id"],"observed_text_length":None,
                    "fields":{field:None for field in DETAIL_FIELDS}} for a in users]}
    value=e.read_json(path)
    g.keys(value,["structure_version","participant_id","sensitive_review","entries"],"detail_header_fields")
    e.require(value["structure_version"]=="1.0.0" and value["participant_id"]==participant_id and value["sensitive_review"]=="pending_human_review" and isinstance(value["entries"],list),"detail_header")
    e.require(all(isinstance(row,dict) for row in value["entries"]),"detail_entries_objects")
    e.require({row.get("event_id") for row in value["entries"]}=={a["event_id"] for a in users} and len(value["entries"])==len(users),"detail_exact_user_scope")
    by_id={a["event_id"]:a for a in users}
    for row in value["entries"]:
        g.keys(row,["event_id","observed_text_length","fields"],"detail_entry_fields")
        e.require(type(row["observed_text_length"]) is int and row["observed_text_length"]>=0,"detail_observed_length")
        g.keys(row["fields"],DETAIL_FIELDS,"detail_field_set")
        action=by_id[row["event_id"]]
        for observations in row["fields"].values():
            e.require(observations is None or isinstance(observations,list),"detail_observation_list_or_unknown")
            for observation in observations or []:
                g.keys(observation,["value","evidence"],"detail_observation_fields")
                e.require(isinstance(observation["value"],str) and 0<len(observation["value"])<=800,"detail_abstraction_length")
                e.require(isinstance(observation["evidence"],list) and observation["evidence"],"detail_evidence_required")
                for span in observation["evidence"]:
                    g.keys(span,["ref","start","end"],"detail_span_fields")
                    e.require(span["ref"]==action["source_ref"] and span["ref"] in known and
                        type(span["start"]) is int and type(span["end"]) is int and
                        0<=span["start"]<span["end"]<=row["observed_text_length"],"detail_own_span_bounds")
    return value


def analyze(run_dirs,detail_path=None,atom_path=None):
    people=set()
    for folder in run_dirs:
        patterns=e.read_json(Path(folder)/"patterns.json")
        e.check_schema(patterns,"patterns",c.CONTRACT)
        people.update(a["participant_id"] for a in patterns["actions"])
    e.require(len(people)==1,"individual_structure_one_participant_required")
    # Compare-process helpers are used only to form observation modules for this person.
    structure=p.analyze(run_dirs,max_pairs=0,individual_only=True)
    pid=next(iter(people))
    actions,coverage,result_records={},[],[]
    for folder,source in zip(run_dirs,structure["source_runs"]):
        patterns,cov,_=c.load_run(folder,source["data_mode"])
        coverage.append(cov)
        for a in patterns["actions"]:
            actions[a["event_id"]]=a
        result_path=Path(folder)/"task-result.json"
        if result_path.is_file():
            result=g.submission(result_path)
            e.require(result["participant_id"]==pid and result["task_id"]==source["task_id"],"individual_result_identity_mismatch")
            result_records.append({"run_id":source["run_id"],"result":result,
                "sha256":hashlib.sha256(result_path.read_bytes()).hexdigest(),"meaning":"observed_numeric_result_not_correctness_judgment"})
    users=[a for a in actions.values() if a["actor"]=="user"]
    detail_doc=details(detail_path,pid,users,{a["source_ref"] for a in actions.values()})
    atom_doc=b.validate(atom_path,pid,list(actions.values()))
    atom_mismatches=b.enrich(atom_doc,structure['processes'],list(actions.values()))
    return {"structure_version":"1.0.0","package_version":VERSION,"participant_id":pid,
        "purpose":"individual_observation_extraction_only","review_status":"draft",
        "observed_actions":list(actions.values()),"instruction_details":detail_doc,
        "detail_status":"source_abstractions_supplied_not_semantically_verified" if detail_path else "not_extracted_fields_unknown",
        "behavior_atoms":atom_doc,"atom_status":"observations_supplied_not_semantically_verified" if atom_path else "not_extracted_unknown",
        "observation_axis_contract":"1.0.0",
        "observation_axis_summary":x.summarize(atom_doc),
        "fine_coding_mismatches":atom_mismatches,
        "module_dictionary":structure["module_dictionary"],"processes":structure["processes"],
        "task_units":structure["units"],"coverage":coverage,"source_runs":structure["source_runs"],
        "observed_task_results":result_records,"missing_task_result_units":[u["unit_id"] for u in structure["units"] if not any(r["result"]["task_id"]==u["task_id"] for r in result_records)],
        "grouping_performed":False,"grading_performed":False,"intervention_strategy_development_performed":False,
        "implementation_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limits":["detail_values_are_observed_abstractions_not_raw_quotes","semantic_and_sensitive_review_pending",
            "detail_span_lengths_are_assertions_not_independently_checked_raw_text",
            "module_boundary_is_observation_window_not_confirmed_execution_cause",
            "no_cross_session_stitching_or_missing_time_inference"]}


def report(value):
    lines=["# 개별 참여자 지시·모듈·과정 구조화", "",f"참여자 {value['participant_id']} / 과제 {len(value['task_units'])}개 / 세션 {len(value['processes'])}개.",
        "집단 그룹핑·정답 판정·점수·인터벤션 전략 개발은 수행하지 않았습니다. 이 파일은 후속 분석용 관찰 추출 자료입니다.",
        f"세부 지시 구조 상태: {value['detail_status']}. 값은 근거 연결된 추상화입니다.","",
        "| 과제 | 세션 | 관찰 모듈 순서 | 관찰 범위 |", "|---|---|---|---|"]
    for process in value["processes"]:
        lines.append(f"| {process['task_id']} | {process['session_id']} | {' → '.join(p.readable(s) for s in process['sequence']) or '미확인'} | {process['scope_status']} |")
    counts=Counter(a["actor"] for a in value["observed_actions"])
    lines += ["", f"관찰 사건 {len(value['observed_actions'])}개 / 사용자 {counts['user']}개 / AI {counts['assistant']}개 / 도구 {counts['tool']}개. 아래 비율의 분모는 각 과제의 관찰 사용자 사건이며 전체 행동량으로 일반화하지 않습니다."]
    for unit in value["task_units"]:
        lines.append(f"과제 {unit['task_id']}: 사용자 {unit['user_events']}개, 보류·미분류 사건 {unit['ambiguous_user_events']}개, 본문 불완전 사건 {unit['truncated_events']}개, 관찰 도구 실패 {unit['observed_tool_failures']}개.")
    lines += ["", "| 모듈 | 사용자 근거 | 뒤따른 사건 수 | 순서 근거 |", "|---|---|---:|---|"]
    for process in value["processes"]:
        for module in process["modules"]:
            spans=", ".join(f"{span['ref']}[{span['start']}:{span['end']}]" for span in module["evidence"])
            lines.append(f"| {module['module_id']} | {spans or module['user_ref']} | {len(module['following_event_ids'])} | {module['order_basis']} |")
    lines += ["", "확인된 결과 관찰값:"]
    for record in value["observed_task_results"]:
        result=record["result"]
        lines.append(f"- 과제 {result['task_id']}: {e.canonical(result['values'])}; 피드백 전 경계 {'제공됨(관찰 참조)' if result['pre_feedback_window'] else '미확인'}. 정답 여부 미판정.")
    if value["missing_task_result_units"]:
        lines.append(f"- 결과값 미확인 단위 {len(value['missing_task_result_units'])}개.")
    lines += ["", "출처·읽기 범위와 확인된 모델 설정:"]
    for source in value["source_runs"]:
        lines.append(f"- {source['run_id']}: 모드 {source['data_mode']}, 완전 추출 표시 {source['complete_extraction']}, 모델 관찰 {e.canonical(source['model_observation'])}.")
    for coverage in value["coverage"]:
        lines += e.mc.report_lines(coverage.get("model_context"))
    lines +=['','세부 행동 상태: '+value['atom_status']+'. 같은 발화 안의 순서는 명시 근거가 있는 관계만 보존합니다.',
        '| 사용자 사건 | 세부 행동 | 명시 순서/병렬 관계 수 |','|---|---|---:|']
    for row in value['behavior_atoms']['entries']:
        labels=' / '.join((atom['category'] or '미분류')+':'+atom['subtype'] for atom in row['atoms'] or [])
        lines.append(f"| {row['event_id']} | {labels if row['atoms'] is not None else '미확인'} | {len(row['relations'] or [])} |")
    lines +=['',f"상세 행동과 기존 코딩 불일치 {len(value['fine_coding_mismatches'])}건. 원래 코딩은 덮어쓰지 않고 검토 대상으로 유지합니다.",
        'AI 진술과 도구 보고의 내용은 별도 근거로 추출하며 사용자 요청 충족이나 정답을 판정하지 않습니다.']
    lines += ['', '관찰 축: 입력 가공·질문 방식·역할 설정·추론 대상. 사용자 진술과 원본 대조 관찰을 구별합니다.',
        '| 사용자 사건 | 입력 가공 | 질문 방식 | 역할 설정 | 추론 대상 |', '|---|---|---|---|---|']
    for row in value['behavior_atoms']['entries']:
        axes=x.from_row(row)
        cells=['미확인' if axes[axis] is None else (' / '.join(item['code']+' ('+item['basis']+')' for item in axes[axis]) or '읽은 범위에 관찰 없음') for axis in x.AXES]
        lines.append('| '+row['event_id']+' | '+' | '.join(cells)+' |')
    for axis,counts in value['observation_axis_summary'].items():
        lines.append(f"- {axis}: 사용자 사건 {counts['total_user_events']}개 중 미확인 {counts['unknown_events']}개, 관찰 없음 {counts['observed_absent_events']}개, 관찰값 있음 {counts['events_with_observations']}개. 복수 코드는 중복될 수 있습니다.")
    lines +=["", "지시 상세 항목은 목표·대상·조건·출력 요구·명시 단계·위임 범위·통제 경계·검증 요청·교정 대상·재사용·질문 초점·평가 기준 참조입니다.",
        "null은 확인 못함, []는 읽은 범위에서 해당 항목이 관찰되지 않음입니다. 둘을 행동 없음으로 합치지 않습니다.",
        "AI/도구 사건과 사용자 지시는 별개이며 같은 발화의 복수 패턴에 순서를 만들지 않습니다. 세션 사이를 이어 붙이지 않습니다.",
        "원본 순번·시각·최종 결과가 없으면 누락으로 남깁니다. 최종 숫자는 관찰값일 뿐 정답인지 판정하지 않습니다.",
        "자동 구조 검사는 관찰 의미·분류 타당성을 확인하지 않습니다.", ""]
    return "\n".join(lines)


def build(run_dirs,out_root,detail_path=None,atom_path=None):
    folder=e.new_run(out_root)
    try:
        value=analyze(run_dirs,detail_path,atom_path)
        e.write_json(folder/"session-structure.json",value)
        e.write_json(folder/"instruction-details.json",value["instruction_details"])
        e.write_json(folder/'behavior-atoms.json',value['behavior_atoms'])
        p.write_csv(folder/'behavior-atoms.csv',b.csv_rows(value['behavior_atoms']))
        p.write_csv(folder/'observation-axes.csv',x.csv_rows(value['behavior_atoms']))
        p.write_csv(folder/"modules.csv",[{"process_id":proc["process_id"],"task_id":proc["task_id"],"session_id":proc["session_id"],**m} for proc in value["processes"] for m in proc["modules"]])
        (folder/"report.md").write_text(report(value),encoding="utf-8")
        names=["session-structure.json","instruction-details.json","behavior-atoms.json","behavior-atoms.csv","observation-axes.csv","modules.csv","report.md"]
        e.write_json(folder/"integrity.json",{"files":{name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in names}})
    except (e.ContractError,OSError) as error:
        e.write_json(folder/"failure.json",{"status":"failed","error_code":str(error) if isinstance(error,e.ContractError) else "filesystem_error"})
        raise
    return folder


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs",nargs="+",required=True)
    parser.add_argument("--details")
    parser.add_argument('--atoms')
    parser.add_argument("--out-root",default=str(e.ROOT/"runs"))
    args=parser.parse_args()
    try:
        print(build(args.runs,args.out_root,args.details,args.atoms))
    except (e.ContractError,OSError):
        print("FAILED: inspect new run failure.json",file=sys.stderr)
        raise SystemExit(1)
