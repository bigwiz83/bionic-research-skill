"""Prepare derived-only ZIP/EML and optionally send through configured TLS SMTP after consent."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import smtplib
import ssl
import sys
from datetime import datetime,timezone
from email.message import EmailMessage
from email.utils import make_msgid,parseaddr,formatdate
import zipfile

import extract as e
import cohort as c

RECIPIENT='bigwiz83@gmail.com'
BASE_FILES=['actions.csv','patterns.json','coverage.json','report.md','integrity.json']
STRUCTURE_FILES=['session-structure.json','instruction-details.json','behavior-atoms.json','behavior-atoms.csv','modules.csv','report.md','integrity.json']
AXIS_FILES=['observation-axes.csv']
MAX_ZIP_BYTES=15*1024*1024
MAX_UNCOMPRESSED_BYTES=64*1024*1024

def now():return datetime.now(timezone.utc).isoformat()
def digest(data):return hashlib.sha256(data).hexdigest()
def safe_file(root,name):
    root=Path(root).resolve()
    path=root/name
    e.require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root),'submission_file_outside_selected_run')
    return path

def prepare(run_dirs,structure_run,out_root):
    e.require(run_dirs and len(run_dirs)==len({str(Path(p).resolve()) for p in run_dirs}),'submission_duplicate_or_empty_runs')
    payloads,people,tasks,run_ids,modes,source_hashes={},{},set(),[],set(),{}
    for index,folder in enumerate(run_dirs,1):
        for name in BASE_FILES:safe_file(folder,name)
        mode=e.read_json(safe_file(folder,'coverage.json'))['data_mode']
        patterns,coverage,hashes=c.load_run(folder,mode)
        source_hashes[coverage['run_id']]=hashes
        identities={(a['participant_id'],a['task_id']) for a in patterns['actions']}
        e.require(len(identities)==1,'submission_source_identity')
        pid,task=next(iter(identities))
        people[pid]=True;tasks.add(task);run_ids.append(coverage['run_id']);modes.add(mode)
        for name in BASE_FILES:
            data=safe_file(folder,name).read_bytes()
            if name in hashes:e.require(digest(data)==hashes[name],'submission_source_changed_during_packaging')
            payloads[f'extraction-{index:03d}/'+name]=data
    e.require(len(people)==1 and len(modes)==1,'submission_one_participant_one_mode')
    pid=next(iter(people))
    for name in STRUCTURE_FILES:safe_file(structure_run,name)
    structure=e.read_json(safe_file(structure_run,'session-structure.json'))
    e.require(structure['participant_id']==pid and {s['run_id'] for s in structure['source_runs']}==set(run_ids),'submission_structure_source_mismatch')
    e.require(all(s['artifact_hashes']==source_hashes[s['run_id']] for s in structure['source_runs']),'submission_structure_source_hash_mismatch')
    e.require(not structure['grouping_performed'] and not structure['grading_performed'] and not structure['intervention_strategy_development_performed'],'submission_individual_scope')
    integrity=e.read_json(safe_file(structure_run,'integrity.json'))
    structure_files=STRUCTURE_FILES+(AXIS_FILES if structure.get('observation_axis_contract')=='1.0.0' else [])
    e.require(set(integrity['files'])==set(structure_files)-{'integrity.json'},'submission_structure_integrity_set')
    for name in structure_files:
        data=safe_file(structure_run,name).read_bytes()
        if name!='integrity.json':e.require(digest(data)==integrity['files'][name],'submission_structure_integrity_mismatch')
        payloads['individual/'+name]=data
    e.require(sum(len(data) for data in payloads.values())<=MAX_UNCOMPRESSED_BYTES,'submission_uncompressed_too_large')
    # Named artifacts only. No recursive folder collection, raw intake, task attachments, or credentials.
    manifest={'submission_version':'1.1.0','recipient':RECIPIENT,'participant_id':pid,'task_ids':sorted(tasks),
        'run_ids':run_ids,'data_mode':next(iter(modes)),'review_status':'draft_for_researcher_review',
        'files':{name:{'sha256':digest(data),'bytes':len(data)} for name,data in payloads.items()}}
    folder=e.new_run(out_root)
    archive=folder/'research-patterns.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in payloads.items():z.writestr(name,data)
        z.writestr('bundle-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8'))
    e.require(archive.stat().st_size<=MAX_ZIP_BYTES,'submission_zip_too_large')
    e.write_json(folder/'submission.json',{'submission_version':'1.1.0','recipient':RECIPIENT,
        'archive':'research-patterns.zip','archive_sha256':digest(archive.read_bytes()),'file_count':len(payloads)+1,
        'participant_id':pid,'task_ids':sorted(tasks),'created_at':now()})
    e.write_json(folder/'delivery-state.json',{'status':'prepared_not_sent','recipient':RECIPIENT})
    return folder

def checked_bundle(folder,approval_path):
    folder=Path(folder)
    meta=e.read_json(safe_file(folder,'submission.json'))
    e.require(meta['recipient']==RECIPIENT and meta['archive']=='research-patterns.zip','submission_fixed_destination')
    data=safe_file(folder,'research-patterns.zip').read_bytes()
    e.require(digest(data)==meta['archive_sha256'] and len(data)<=MAX_ZIP_BYTES,'submission_bundle_changed_or_too_large')
    approval=e.read_json(approval_path)
    required=['approval_version','recipient','archive_sha256','consent','consent_ref']
    # Older saved approvals may contain a privacy field; it is no longer a gate.
    if isinstance(approval,dict) and approval.get('approval_version')=='1.0.0' and 'privacy_confirmation' in approval:
        required.append('privacy_confirmation')
    e.require(isinstance(approval,dict) and set(approval)==set(required),'submission_approval_fields')
    e.require(approval['approval_version'] in {'1.0.0','1.1.0'} and approval['recipient']==RECIPIENT and approval['archive_sha256']==meta['archive_sha256'],'submission_approval_target')
    e.require(approval['consent'] is True,'submission_explicit_consent_required')
    e.require(isinstance(approval['consent_ref'],str) and 0<len(approval['consent_ref'])<=200,'submission_consent_reference')
    with zipfile.ZipFile(safe_file(folder,'research-patterns.zip')) as z:
        e.require(sum(info.file_size for info in z.infolist())<=MAX_UNCOMPRESSED_BYTES,'submission_uncompressed_too_large')
        e.require(z.testzip() is None,'submission_zip_corrupt')
        manifest=json.loads(z.read('bundle-manifest.json'))
        e.require(manifest['recipient']==RECIPIENT and set(z.namelist())==set(manifest['files'])|{'bundle-manifest.json'} and len(z.namelist())==len(set(z.namelist())),'submission_zip_file_set')
        for name,info in manifest['files'].items():
            e.require(not name.startswith('/') and '..' not in Path(name).parts and '\\' not in name,'submission_zip_path')
            pieces=name.split('/')
            e.require(len(pieces)==2 and (re.fullmatch(r'extraction-[0-9]{3,}',pieces[0]) and pieces[1] in BASE_FILES or pieces[0]=='individual' and pieces[1] in STRUCTURE_FILES+AXIS_FILES),'submission_zip_artifact_allowlist')
            payload=z.read(name)
            e.require(digest(payload)==info['sha256'] and len(payload)==info['bytes'],'submission_zip_content_changed')
    return meta,data,approval

def message(meta,data,sender=None):
    msg=EmailMessage()
    msg['To']=RECIPIENT
    if sender:msg['From']=sender
    msg['Subject']='[Bionic] 연구패턴 추출 결과 제출'
    msg['Date']=formatdate(localtime=False)
    msg['Message-ID']=make_msgid(domain='bionic-research.invalid')
    msg.set_content('참여자가 전송에 동의한 연구용 추출 결과 초안입니다.\n근거·누락·분류를 함께 첨부합니다.\n첨부 ZIP SHA256: '+meta['archive_sha256']+'\n')
    msg.add_attachment(data,maintype='application',subtype='zip',filename='research-patterns.zip')
    return msg

def make_eml(folder,approval_path):
    meta,data,_=checked_bundle(folder,approval_path)
    target=Path(folder)/'research-submission.eml'
    e.require(not target.exists(),'submission_eml_already_exists')
    draft=message(meta,data)
    draft['X-Unsent']='1'
    target.write_bytes(draft.as_bytes())
    return target

def send(folder,approval_path):
    folder=Path(folder)
    meta,data,approval=checked_bundle(folder,approval_path)
    state=e.read_json(safe_file(folder,'delivery-state.json'))
    if state['status']=='sent_smtp_accepted':return state
    e.require(state['status']=='prepared_not_sent','submission_prior_attempt_requires_manual_resolution')
    host=os.environ.get('BIONIC_SMTP_HOST','')
    user=os.environ.get('BIONIC_SMTP_USER','')
    password=os.environ.get('BIONIC_SMTP_PASSWORD','')
    sender=os.environ.get('BIONIC_SMTP_FROM',user)
    security=os.environ.get('BIONIC_SMTP_SECURITY','starttls')
    e.require(host and user and password,'submission_smtp_not_configured')
    e.require(security in {'starttls','ssl'},'submission_tls_required')
    e.require(sender and parseaddr(sender)[1]==sender and '\n' not in sender and '\r' not in sender and '@' in sender,'submission_sender_address')
    try:port=int(os.environ.get('BIONIC_SMTP_PORT','465' if security=='ssl' else '587'))
    except ValueError:raise e.ContractError('submission_smtp_port')
    e.require(1<=port<=65535,'submission_smtp_port')
    msg=message(meta,data,sender)
    lock=folder/'send.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise e.ContractError('submission_send_lock_exists')
    os.close(fd)
    started=False
    try:
        context=ssl.create_default_context()
        if security=='ssl':client=smtplib.SMTP_SSL(host,port,timeout=30,context=context)
        else:client=smtplib.SMTP(host,port,timeout=30)
        with client:
            if security=='starttls':client.ehlo();client.starttls(context=context);client.ehlo()
            client.login(user,password)
            e.write_json(folder/'delivery-state.json',{'status':'sending_acceptance_not_yet_known','recipient':RECIPIENT,'archive_sha256':meta['archive_sha256'],'started_at':now()})
            started=True
            refused=client.send_message(msg,from_addr=sender,to_addrs=[RECIPIENT])
            e.require(not refused,'submission_recipient_rejected')
            receipt={'status':'sent_smtp_accepted','recipient':RECIPIENT,'archive_sha256':meta['archive_sha256'],
                'message_id':msg['Message-ID'],'accepted_at':now(),'consent_ref':approval['consent_ref'],
                'consent_confirmed':True,'recipient_inbox_delivery_verified':False}
            e.write_json(folder/'delivery-state.json',receipt)
        return receipt
    except Exception:
        current=e.read_json(folder/'delivery-state.json')
        # A QUIT failure after a successful DATA acceptance does not undo acceptance.
        if current['status']=='sent_smtp_accepted':return current
        failure={'status':'delivery_uncertain_do_not_auto_retry' if started else 'failed_before_submission',
            'recipient':RECIPIENT,'archive_sha256':meta['archive_sha256'],'failed_at':now(),
            'error_code':'smtp_acceptance_unknown' if started else 'smtp_connection_or_authentication_failed'}
        e.write_json(folder/'delivery-state.json',failure)
        raise e.ContractError(failure['error_code']) from None

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prep=commands.add_parser('prepare')
    prep.add_argument('--runs',nargs='+',required=True);prep.add_argument('--structure-run',required=True)
    prep.add_argument('--out-root',required=True)
    for name in ['eml','send']:
        cmd=commands.add_parser(name);cmd.add_argument('--bundle',required=True);cmd.add_argument('--approval',required=True)
    args=parser.parse_args()
    try:
        if args.command=='prepare':print(prepare(args.runs,args.structure_run,args.out_root))
        elif args.command=='eml':print(make_eml(args.bundle,args.approval))
        else:print(e.canonical(send(args.bundle,args.approval)))
    except (e.ContractError,OSError,KeyError,zipfile.BadZipFile):
        print('FAILED: inspect bundle state; no automatic retry',file=sys.stderr)
        raise SystemExit(1)
