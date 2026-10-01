"""Invent modular processes, numeric submissions and one reusable task answer key."""
import argparse
from pathlib import Path
import extract as e
from make_synthetic import event, session

TEXT = {"goal_specification":"집계 단위와 포함 조건을 명시해 줘.",
    "data_structure_inquiry":"먼저 필요한 자료 구조를 확인해 줘.",
    "task_decomposition":"자료 확인, 집계, 검증을 단계로 나눠 진행해 줘.",
    "verification_request":"집계 근거를 대조하고 검증해 줘.",
    "delegation_control":"나머지는 알아서 진행해 줘.",
    "error_correction":"관찰된 누락을 수정해 줘.",
    "reuse_resume":"앞서 확인한 결과를 이어서 사용해 줘."}


def generate(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    e.require(not (root/"selected-runs.json").exists(), "process_synthetic_target_exists")
    sequences = [
        (["goal_specification","data_structure_inquiry","task_decomposition","verification_request"],10),
        (["goal_specification","data_structure_inquiry","error_correction","verification_request"],10),
        (["goal_specification","task_decomposition","verification_request"],9),
        (["delegation_control","delegation_control","delegation_control"],14),
        (["goal_specification","verification_request","data_structure_inquiry","task_decomposition"],10),
        (["goal_specification","data_structure_inquiry","task_decomposition","verification_request"],14),
        (["delegation_control"],None),
        (["goal_specification","data_structure_inquiry","task_decomposition","verification_request"],10),
    ]
    runs = []
    for index,(sequence,submitted) in enumerate(sequences,1):
        pid,task,sid,namespace=f"P-SYN{index:03d}","T-SYN-COUNT","S-SYN-01",f"SYN-PROCESS-{index:03d}"
        raw=[]
        entries=[]
        for cat in [*sequence,"error_correction"]:
            i=len(raw)+1
            raw.append(event(i,"user",TEXT[cat],f"syn-{i}"))
            entries.append({"source_ref":e.ref(sid,i),"decision":"coded","categories":[cat],
                "criterion_codes":[e.CRITERIA[cat][0]],"ambiguity":None,
                "evidence":[{"ref":e.ref(sid,i),"start":0,"end":len(TEXT[cat])}],"related_refs":[]})
            raw.append(event(i+1,"assistant","가상 자료를 처리하며 AI가 자율적으로 대조하겠습니다.",f"syn-{i+1}"))
            raw.append(event(i+2,"tool","합성 도구 사건.",f"syn-{i+2}",
                kind="tool_failure" if index==4 else "tool_success",content_complete=not(index==8)))
        folder=root/f"intake-{index:03d}"
        folder.mkdir()
        manifest={"schema_version":"1.0.0","data_mode":"synthetic","dataset_namespace":namespace,
            "participant_id":pid,"task_id":task,"adapter":"synthetic-export-v1",
            "model_observation":{"model_id":"synthetic/model","model_id_confirmed":True,
                "settings_confirmed":False,"temperature":None,"top_p":None,"context_length":None},
            "sessions":[session(sid,len(raw),attempt_status="failed" if index==7 else "completed")]}
        e.write_json(folder/"manifest.json",manifest)
        e.write_json(folder/"S-SYN-01.json",raw)
        e.write_json(folder/"codings.json",{"taxonomy_version":e.TAXONOMY_VERSION,"entries":entries})
        run=e.build(folder/"manifest.json",folder/"codings.json",root/"derived")
        # Extra numeric result artifact: only invented aggregate count, never patient rows.
        if index != 7:
            e.write_json(run/"task-result.json",{"result_schema_version":"1.0.0","result_id":f"R-SYN{index:03d}",
                "participant_id":pid,"task_id":task,"values":{"TARGET_COUNT":submitted},
                "pre_feedback_window":{"receipt_ref":"SYN-BEFORE-ANSWER-FEEDBACK",
                    "cutoffs":[{"dataset_namespace":namespace,"session_id":sid,"max_source_index":len(sequence)*3}]}})
        runs.append(str(run))
    key={"answer_key_version":"1.0.0","answer_key_id":"SYN-COUNT-KEY-1","tasks":[
        {"task_id":"T-SYN-COUNT","metrics":[{"metric_id":"TARGET_COUNT","expected":10,
            "near_tolerance":1,"weight":1,"error_scale":10}]}]}
    e.write_json(root/"answer-key.json",key)
    e.write_json(root/"selected-runs.json",{"runs":runs,"origin":"entirely_invented_no_patient_or_actual_participant_records"})
    return runs,root/"answer-key.json"


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root",required=True)
    args=parser.parse_args()
    runs,key=generate(args.out_root)
    print(e.canonical({"runs":runs,"answer_key":str(key)}))
