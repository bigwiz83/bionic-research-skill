import copy
from email import policy
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import extract as e
import structure_session as s
import behavior_atoms as b
import submission as m
from make_process_synthetic import generate

class AtomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='bionic-fine-synthetic-')
        cls.root=Path(cls.tmp.name)
        cls.runs,_=generate(cls.root)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def doc(self):
        value=s.analyze([self.runs[0]])
        doc=copy.deepcopy(value['behavior_atoms'])
        doc['atom_schema_version']='1.1.0'
        for row in doc['entries']:row.pop('observation_axes',None)
        by_id={a['event_id']:a for a in value['observed_actions']}
        for index,row in enumerate(doc['entries'],1):
            a=by_id[row['event_id']]
            row['observed_text_length']=max(span['end'] for span in a['evidence'])
            cat=a['categories'][0]
            row['atoms']=[{'atom_id':f'A-SYN-{index}','category':cat,'subtype':'other_explicit',
                'facets':{name:None for name in b.FACETS},'evidence':copy.deepcopy(a['evidence'])}]
            row['relations']=[]
        self.path=self.root/'atoms-input.json'
        return doc,value
    def use(self,doc):
        e.write_json(self.path,doc)
        return s.analyze([self.runs[0]],atom_path=self.path)

    def test_unknown_is_not_claimed_extracted(self):
        value=s.analyze([self.runs[0]])
        self.assertEqual(value['atom_status'],'not_extracted_unknown')
        self.assertTrue(all(row['atoms'] is None for row in value['behavior_atoms']['entries']))
        self.assertTrue(all(row['observations'] is None for row in value['behavior_atoms']['responses']))

    def test_multiple_actions_keep_one_module_and_no_implicit_order(self):
        doc,_=self.doc()
        row=doc['entries'][3]
        row['atoms'][0]['subtype']='source_crosscheck'
        row['atoms'].append({**copy.deepcopy(row['atoms'][0]),'atom_id':'A-SYN-EXTRA','subtype':'request_evidence'})
        value=self.use(doc)
        module=value['processes'][0]['modules'][3]
        self.assertEqual(len(value['processes'][0]['modules']),5)
        self.assertEqual(len(module['fine_action_ids']),2)
        self.assertEqual(module['explicit_within_utterance_relations'],[])
        self.assertFalse(value['grouping_performed'])
        self.assertFalse(value['grading_performed'])

    def test_method_criterion_have_own_evidence(self):
        doc,_=self.doc();atom=doc['entries'][3]['atoms'][0]
        atom['facets']['method']=[{'value':'합성 관찰 원문 대조 요구','evidence':copy.deepcopy(atom['evidence'])}]
        value=self.use(doc)
        self.assertEqual(value['behavior_atoms']['entries'][3]['atoms'][0]['facets']['method'],atom['facets']['method'])
        atom['facets']['criterion']=[{'value':'가상 기준','evidence':[{'ref':'OTHER/row-000001','start':0,'end':1}]}]
        with self.assertRaisesRegex(e.ContractError,'own_span'):self.use(doc)

    def test_invalid_subtype_and_duplicate_ids_rejected(self):
        doc,_=self.doc();doc['entries'][0]['atoms'][0]['subtype']='check_duplicates'
        with self.assertRaisesRegex(e.ContractError,'subtype'):self.use(doc)
        doc,_=self.doc();doc['entries'][1]['atoms'][0]['atom_id']=doc['entries'][0]['atoms'][0]['atom_id']
        with self.assertRaisesRegex(e.ContractError,'unique_id'):self.use(doc)

    def test_order_cycles_cross_utterance_and_parallel_conflicts_rejected(self):
        doc,_=self.doc();row=doc['entries'][3]
        row['atoms'].append({**copy.deepcopy(row['atoms'][0]),'atom_id':'A-SYN-SECOND'})
        left,right=[a['atom_id'] for a in row['atoms']]
        def rel(a,z,kind):return {'from_atom':a,'to_atom':z,'kind':kind,'evidence':copy.deepcopy(row['atoms'][0]['evidence'])}
        row['relations']=[rel(left,right,'explicit_before')]
        self.assertEqual(self.use(doc)['behavior_atoms']['entries'][3]['relations'],row['relations'])
        row['relations'].append(rel(right,left,'explicit_before'))
        with self.assertRaisesRegex(e.ContractError,'cycle'):self.use(doc)
        row['relations']=[rel(left,right,'explicit_before'),rel(left,right,'explicit_parallel')]
        with self.assertRaisesRegex(e.ContractError,'parallel_order_conflict'):self.use(doc)
        row['relations']=[rel(left,doc['entries'][0]['atoms'][0]['atom_id'],'explicit_before')]
        with self.assertRaisesRegex(e.ContractError,'same_utterance'):self.use(doc)

    def test_response_own_body_evidence_not_user_fulfillment(self):
        doc,value=self.doc();row=doc['responses'][0]
        a=next(a for a in value['observed_actions'] if a['event_id']==row['event_id'])
        row['observed_text_length']=20
        row['observations']=[{'aspect':'action','value':'AI 대조 의향 진술, 실제 완료 미확인','evidence':[{'ref':a['source_ref'],'start':0,'end':2}]}]
        result=self.use(doc)
        self.assertEqual(result['processes'][0]['modules'][0]['response_link_basis'],'observation_window_not_proven_request_fulfillment')
        row['observations'][0]['evidence'][0]['end']=21
        with self.assertRaisesRegex(e.ContractError,'own_span'):self.use(doc)

    def test_detail_source_coding_mismatch_preserved_not_overwritten(self):
        doc,value=self.doc();row=doc['entries'][2]
        row['atoms'].append({**copy.deepcopy(row['atoms'][0]),'atom_id':'A-SYN-VERIFY','category':'verification_request','subtype':'other_explicit'})
        result=self.use(doc)
        self.assertEqual(result['fine_coding_mismatches'][0]['fine_categories_missing_from_source_coding'],['verification_request'])
        self.assertEqual(result['observed_actions'],value['observed_actions'])

    def test_missing_events_unknown_with_relations_and_ai_in_user_scope_rejected(self):
        doc,_=self.doc();doc['entries'].pop()
        with self.assertRaisesRegex(e.ContractError,'exact_event_scope'):self.use(doc)
        doc,_=self.doc();doc['entries'][0]['atoms']=None
        with self.assertRaisesRegex(e.ContractError,'unknown_atoms'):self.use(doc)
        doc,_=self.doc();doc['entries'][0]['event_id']=doc['responses'][0]['event_id']
        with self.assertRaisesRegex(e.ContractError,'exact_event_scope'):self.use(doc)

    def search_atom(self,row,aid,category,subtype):
        evidence=copy.deepcopy(row['atoms'][0]['evidence'])
        return {'atom_id':aid,'category':category,'subtype':subtype,
            'facets':{name:None for name in b.FACETS},'evidence':evidence,
            'search_details':{'search_terms':[{'value':'합성 주제의 명시 검색어','evidence':copy.deepcopy(evidence)}],
                'source_constraints':[],'selection_criteria':None,'claim_reference':None}}

    def test_search_purposes_separate_keep_source_coding_and_unknowns(self):
        doc,original=self.doc();row=doc['entries'][0]
        row['atoms']=[self.search_atom(row,'A-SEARCH-INFO','goal_specification','information_search'),
            self.search_atom(row,'A-SEARCH-SUPPORT','verification_request','supporting_reference_search')]
        value=self.use(doc)
        self.assertEqual([a['subtype'] for a in value['behavior_atoms']['entries'][0]['atoms']],
            ['information_search','supporting_reference_search'])
        self.assertEqual(value['observed_actions'],original['observed_actions'])
        self.assertEqual(value['fine_coding_mismatches'][0]['fine_categories_missing_from_source_coding'],['verification_request'])
        self.assertEqual(len(value['processes'][0]['modules']),5)
        self.assertEqual(value['processes'][0]['modules'][0]['explicit_within_utterance_relations'],[])
        self.assertIsNone(row['atoms'][0]['search_details']['selection_criteria'])
        self.assertEqual(row['atoms'][0]['search_details']['source_constraints'],[])
        self.assertFalse(value['grading_performed'])

    def test_search_fields_and_own_spans_required(self):
        doc,_=self.doc();row=doc['entries'][0]
        row['atoms']=[self.search_atom(row,'A-SEARCH','goal_specification','information_search')]
        self.use(doc)
        del row['atoms'][0]['search_details']['selection_criteria']
        with self.assertRaisesRegex(e.ContractError,'search_detail_fields'):self.use(doc)
        row['atoms'][0]['search_details']['selection_criteria']=None
        row['atoms'][0]['search_details']['search_terms'][0]['evidence'][0]['ref']='OTHER/row-000001'
        with self.assertRaisesRegex(e.ContractError,'own_span'):self.use(doc)

    def test_search_new_contract_and_category_boundary_legacy_accepted(self):
        doc,_=self.doc();doc['atom_schema_version']='1.0.0'
        self.assertEqual(self.use(doc)['behavior_atoms']['atom_schema_version'],'1.0.0')
        row=doc['entries'][0]
        row['atoms']=[self.search_atom(row,'A-SEARCH','goal_specification','information_search')]
        with self.assertRaisesRegex(e.ContractError,'search_contract_required'):self.use(doc)
        doc['atom_schema_version']='1.1.0';self.use(doc)
        row['atoms'][0]['category']='verification_request'
        with self.assertRaisesRegex(e.ContractError,'atom_subtype'):self.use(doc)

    def test_search_details_missing_or_on_nonsearch_type_rejected(self):
        doc,_=self.doc();row=doc['entries'][0]
        row['atoms']=[self.search_atom(row,'A-SEARCH','goal_specification','information_search')]
        del row['atoms'][0]['search_details']
        with self.assertRaisesRegex(e.ContractError,'search_contract_required'):self.use(doc)
        row['atoms'][0]['subtype']='specify_target';row['atoms'][0]['search_details']={name:None for name in b.SEARCH_FIELDS}
        with self.assertRaisesRegex(e.ContractError,'only_for_search_actions'):self.use(doc)

    def test_search_observations_preserved_in_structure_csv_and_submission_zip(self):
        doc,_=self.doc();row=doc['entries'][0]
        row['atoms']=[self.search_atom(row,'A-SEARCH-EXPORT','goal_specification','information_search')]
        e.write_json(self.path,doc)
        structured=s.build([self.runs[0]],self.root/'search-structure',atom_path=self.path)
        with patch.object(m.smtplib,'SMTP',side_effect=AssertionError('must not connect')):
            folder=m.prepare([self.runs[0]],structured,self.root/'search-bundles')
        with zipfile.ZipFile(folder/'research-patterns.zip') as z:
            exported=json.loads(z.read('individual/behavior-atoms.json'))
            self.assertEqual(exported['entries'][0]['atoms'][0]['search_details'],row['atoms'][0]['search_details'])
            import csv,io
            rows=list(csv.DictReader(io.StringIO(z.read('individual/behavior-atoms.csv').decode('utf-8-sig'))))
            self.assertEqual(json.loads(rows[0]['search_details']),row['atoms'][0]['search_details'])
            self.assertEqual(rows[0]['subtype'],'information_search')
            self.assertIn('information_search',z.read('individual/report.md').decode('utf-8'))
        self.assertEqual(e.read_json(folder/'delivery-state.json')['status'],'prepared_not_sent')

class FakeSMTP:
    sent=[]
    def __init__(self,*args,**kwargs):self.tls=False
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def ehlo(self):pass
    def starttls(self,context):self.tls=True
    def login(self,user,password):
        assert self.tls,'TLS required before authentication'
    def send_message(self,msg,from_addr,to_addrs):
        self.sent.append((msg,from_addr,to_addrs));return {}

class SubmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='bionic-send-synthetic-')
        cls.root=Path(cls.tmp.name);cls.runs,_=generate(cls.root)
        cls.structured=s.build([cls.runs[0]],cls.root/'structure')
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):FakeSMTP.sent=[]
    def bundle(self):return m.prepare([self.runs[0]],self.structured,self.root/'bundles')
    def approval(self,folder,**updates):
        meta=e.read_json(folder/'submission.json')
        doc={'approval_version':'1.1.0','recipient':m.RECIPIENT,'archive_sha256':meta['archive_sha256'],'consent':True,
            'consent_ref':'S-SYN-CONSENT/row-000001'}
        doc.update(updates);path=folder/'approval.json';e.write_json(path,doc);return path
    def env(self):return patch.dict(os.environ,{'BIONIC_SMTP_HOST':'smtp.synthetic.invalid','BIONIC_SMTP_PORT':'587',
        'BIONIC_SMTP_USER':'synthetic@sender.invalid','BIONIC_SMTP_PASSWORD':'synthetic-test-secret','BIONIC_SMTP_SECURITY':'starttls','BIONIC_SMTP_FROM':'synthetic@sender.invalid'})

    def test_allowlist_excludes_raw_extra_credentials_and_contains_integrity(self):
        extra=Path(self.runs[0])/'patient-raw-synthetic.txt';extra.write_text('ENTIRELY INVENTED FOR NON-READ TEST',encoding='utf-8')
        folder=self.bundle()
        with zipfile.ZipFile(folder/'research-patterns.zip') as z:
            self.assertNotIn(extra.name,z.namelist())
            self.assertFalse(any('intake' in name or 'password' in name for name in z.namelist()))
            self.assertIn('individual/behavior-atoms.json',z.namelist())
            self.assertIn('bundle-manifest.json',z.namelist())
            self.assertIsNone(z.testzip())
        self.assertEqual(e.read_json(folder/'delivery-state.json')['status'],'prepared_not_sent')

    def test_wrong_participant_and_modified_structure_refused(self):
        with self.assertRaisesRegex(e.ContractError,'structure_source_mismatch'):
            m.prepare([self.runs[1]],self.structured,self.root/'bundles')
        original=(self.structured/'report.md').read_bytes()
        try:
            (self.structured/'report.md').write_text('SYNTHETIC MODIFIED',encoding='utf-8')
            with self.assertRaisesRegex(e.ContractError,'integrity_mismatch'):self.bundle()
        finally:(self.structured/'report.md').write_bytes(original)

    def test_decline_missing_consent_reference_and_wrong_recipient_never_open_smtp(self):
        for changes in [{'consent':False},{'consent_ref':''},{'recipient':'other@synthetic.invalid'}]:
            folder=self.bundle();approval=self.approval(folder,**changes)
            with patch.object(m.smtplib,'SMTP',side_effect=AssertionError('must not connect')):
                with self.assertRaises(e.ContractError):m.send(folder,approval)

    def test_privacy_confirmation_removed_and_legacy_field_not_a_gate(self):
        folder=self.bundle()
        approval=self.approval(folder)
        self.assertNotIn('privacy_confirmation',e.read_json(approval))
        with zipfile.ZipFile(folder/'research-patterns.zip') as z:
            manifest=json.loads(z.read('bundle-manifest.json'))
            self.assertNotIn('sender_privacy_confirmation_required_before_send',manifest)
        with patch.object(m.smtplib,'SMTP',side_effect=AssertionError('draft must not send')):
            eml=m.make_eml(folder,approval)
        self.assertNotIn('민감정보',BytesParser(policy=policy.default).parsebytes(eml.read_bytes()).get_body(preferencelist=('plain',)).get_content())
        for updates in [{'approval_version':'1.0.0'},
                        {'approval_version':'1.0.0','privacy_confirmation':'pending'}]:
            folder=self.bundle()
            m.checked_bundle(folder,self.approval(folder,**updates))

    def test_changed_zip_or_wrong_hash_never_sent(self):
        folder=self.bundle();approval=self.approval(folder)
        (folder/'research-patterns.zip').write_bytes(b'NOT A ZIP SYNTHETIC')
        with patch.object(m.smtplib,'SMTP',side_effect=AssertionError('must not connect')):
            with self.assertRaisesRegex(e.ContractError,'bundle_changed'):m.send(folder,approval)
        folder=self.bundle();approval=self.approval(folder,archive_sha256='0'*64)
        with self.assertRaisesRegex(e.ContractError,'approval_target'):m.make_eml(folder,approval)

    def test_unconfigured_transport_and_plaintext_tls_refused(self):
        folder=self.bundle();approval=self.approval(folder)
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(e.ContractError,'not_configured'):m.send(folder,approval)
        with self.env(),patch.dict(os.environ,{'BIONIC_SMTP_SECURITY':'none'}):
            with self.assertRaisesRegex(e.ContractError,'tls_required'):m.send(folder,approval)
        self.assertEqual(e.read_json(folder/'delivery-state.json')['status'],'prepared_not_sent')

    def test_eml_has_exact_zip_attachment_fixed_recipient_and_no_network(self):
        folder=self.bundle();approval=self.approval(folder)
        with patch.object(m.smtplib,'SMTP',side_effect=AssertionError('EML must not send')):
            eml=m.make_eml(folder,approval)
        msg=BytesParser(policy=policy.default).parsebytes(eml.read_bytes())
        self.assertEqual(msg['To'],m.RECIPIENT)
        attachments=list(msg.iter_attachments());self.assertEqual(len(attachments),1)
        self.assertEqual(attachments[0].get_content_type(),'application/zip')
        self.assertEqual(attachments[0].get_payload(decode=True),(folder/'research-patterns.zip').read_bytes())
        self.assertEqual(e.read_json(folder/'delivery-state.json')['status'],'prepared_not_sent')

    def test_fake_smtp_acceptance_fixed_destination_and_no_duplicate_send(self):
        folder=self.bundle();approval=self.approval(folder)
        with self.env(),patch.object(m.smtplib,'SMTP',FakeSMTP):
            receipt=m.send(folder,approval);again=m.send(folder,approval)
        self.assertEqual(receipt,again);self.assertEqual(receipt['status'],'sent_smtp_accepted')
        self.assertFalse(receipt['recipient_inbox_delivery_verified'])
        self.assertEqual(len(FakeSMTP.sent),1)
        self.assertEqual(FakeSMTP.sent[0][2],[m.RECIPIENT])
        self.assertNotIn('synthetic-test-secret',(folder/'delivery-state.json').read_text())

    def test_timeout_after_submission_is_uncertain_no_automatic_retry(self):
        class TimeoutSMTP(FakeSMTP):
            def send_message(self,*args,**kwargs):raise TimeoutError('SYNTHETIC NETWORK TIMEOUT')
        folder=self.bundle();approval=self.approval(folder)
        with self.env(),patch.object(m.smtplib,'SMTP',TimeoutSMTP):
            with self.assertRaisesRegex(e.ContractError,'acceptance_unknown'):m.send(folder,approval)
            with self.assertRaisesRegex(e.ContractError,'prior_attempt'):m.send(folder,approval)
        self.assertEqual(e.read_json(folder/'delivery-state.json')['status'],'delivery_uncertain_do_not_auto_retry')

    def test_extra_zip_member_rejected_even_with_new_hash_and_consent(self):
        folder=self.bundle()
        with zipfile.ZipFile(folder/'research-patterns.zip','a') as z:z.writestr('patient-intake.json','SYNTHETIC TEST ONLY')
        meta=e.read_json(folder/'submission.json');meta['archive_sha256']=hashlib.sha256((folder/'research-patterns.zip').read_bytes()).hexdigest();e.write_json(folder/'submission.json',meta)
        with self.assertRaisesRegex(e.ContractError,'zip_file_set'):m.make_eml(folder,self.approval(folder))

if __name__=='__main__':unittest.main()
