import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import extract as e
import structure_session as s
import submission as m
import cohort as c
from make_synthetic import fixtures


def snapshot(scope='task_session_header', sid='S-A', ref=None):
    return {'snapshot_id': 'MS-SYN-HEADER', 'scope': scope, 'session_id': sid,
            'response_ref': ref, 'evidence_ref': 'META-SYN-HEADER',
            'captured_at': '2026-10-03T15:00:00+09:00', 'source_timestamp': None,
            'model_id': 'synthetic/task-model', 'reasoning_level': 'high',
            'parameters': {k: None for k in ['temperature', 'top_p', 'top_k', 'max_output_tokens', 'context_length', 'seed']},
            'token_counts': [{'metric': 'displayed_unknown', 'aggregation': 'unknown', 'value': 12000}]}


class ModelContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bionic-model-synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest, self.events, self.codings, _ = fixtures()
        self.manifest['model_context'] = {'context_version': '1.0.0', 'collection_status': 'observed', 'snapshots': [snapshot()]}

    def save(self):
        for sid, events in self.events.items():
            e.write_json(self.root / (sid + '.json'), events)
        e.write_json(self.root / 'manifest.json', self.manifest)
        e.write_json(self.root / 'codings.json', self.codings)

    def derive(self):
        self.save()
        return e.derive(self.root / 'manifest.json', self.root / 'codings.json')

    def test_final_header_is_preserved_without_response_backfill(self):
        patterns, coverage = self.derive()
        self.assertEqual(coverage['model_context'], self.manifest['model_context'])
        self.assertTrue(all('model_context' not in a and 'model_id' not in a for a in patterns['actions']))
        self.assertIn('displayed_unknown(unknown)=12000', e.report(patterns, coverage))
        self.assertIsNone(coverage['model_context']['snapshots'][0]['source_timestamp'])

    def test_final_header_cannot_be_attached_to_old_response(self):
        self.manifest['model_context']['snapshots'][0]['response_ref'] = 'S-A/row-000002'
        with self.assertRaisesRegex(e.ContractError, 'final_header_cannot_attribute_response'):
            self.derive()

    def test_response_metadata_and_extraction_runtime_are_separate(self):
        task = snapshot('task_response', ref='S-A/row-000002')
        task['snapshot_id'] = 'MS-SYN-RESPONSE'
        task['parameters']['temperature'] = 0
        task['token_counts'] = [{'metric': 'output_tokens', 'aggregation': 'response', 'value': 0}]
        runtime = snapshot('extraction_runtime', sid=None)
        runtime['snapshot_id'] = 'MS-SYN-EXTRACT'
        runtime['model_id'] = 'synthetic/extraction-model'
        self.manifest['model_context']['snapshots'] += [task, runtime]
        _, coverage = self.derive()
        self.assertEqual([v['scope'] for v in coverage['model_context']['snapshots']],
                         ['task_session_header', 'task_response', 'extraction_runtime'])
        self.assertEqual(coverage['model_context']['snapshots'][1]['parameters']['temperature'], 0)

    def test_missing_or_wrong_actor_response_reference_rejected(self):
        for ref in ['S-A/row-999999', 'S-A/row-000001', 'S-B/row-000002']:
            with self.subTest(ref=ref):
                self.manifest['model_context']['snapshots'] = [snapshot('task_response', ref=ref)]
                with self.assertRaises(e.ContractError): self.derive()

    def test_extraction_model_cannot_claim_task_session(self):
        self.manifest['model_context']['snapshots'] = [snapshot('extraction_runtime')]
        with self.assertRaisesRegex(e.ContractError, 'extraction_model_not_task_session'): self.derive()

    def test_unselected_session_and_duplicate_snapshots_rejected(self):
        self.manifest['model_context']['snapshots'][0]['session_id'] = 'S-Z'
        with self.assertRaisesRegex(e.ContractError, 'session_not_selected'): self.derive()
        self.manifest['model_context']['snapshots'] = [snapshot(), snapshot()]
        with self.assertRaisesRegex(e.ContractError, 'duplicate_id'): self.derive()

    def test_unknown_or_unavailable_metadata_does_not_become_zero(self):
        for status in ['not_available', 'not_collected']:
            self.manifest['model_context'] = {'context_version': '1.0.0', 'collection_status': status, 'snapshots': []}
            _, coverage = self.derive()
            self.assertEqual(coverage['model_context']['snapshots'], [])
        self.manifest['model_context']['collection_status'] = 'observed'
        with self.assertRaisesRegex(e.ContractError, 'model_context_status'): self.derive()

    def test_legacy_model_is_not_reinterpreted_as_task_model(self):
        self.manifest.pop('model_context')
        patterns, coverage = self.derive()
        self.assertNotIn('model_context', coverage)
        self.assertIn('과제 모델/추출 모델의 구분이 미확인', e.report(patterns, coverage))

    def test_token_validation_and_explicit_output_limit(self):
        snap = self.manifest['model_context']['snapshots'][0]
        snap['parameters']['max_output_tokens'] = 4096
        snap['parameters']['top_k'] = 40
        snap['parameters']['seed'] = -1
        _, coverage = self.derive()
        self.assertEqual(coverage['model_context']['snapshots'][0]['token_counts'][0]['metric'], 'displayed_unknown')
        snap['token_counts'][0]['value'] = -1
        with self.assertRaises(e.ContractError): self.derive()
        snap['token_counts'][0]['value'] = 1
        snap['token_counts'].append(copy.deepcopy(snap['token_counts'][0]))
        with self.assertRaisesRegex(e.ContractError, 'duplicate_token_metric'): self.derive()

    def test_user_report_is_not_promoted_to_response_metadata(self):
        self.manifest['model_context']['snapshots'] = [snapshot('task_user_report', ref='S-A/row-000001')]
        _, coverage = self.derive()
        self.assertEqual(coverage['model_context']['snapshots'][0]['scope'], 'task_user_report')

    def test_only_one_latest_header_is_stored_per_session(self):
        later = snapshot()
        later.update(snapshot_id='MS-SYN-LATER', model_id='synthetic/other-model', captured_at='2026-10-03T16:00:00+09:00')
        self.manifest['model_context']['snapshots'].append(later)
        with self.assertRaisesRegex(e.ContractError, 'one_latest_header_per_session'):
            self.derive()

    def test_structure_and_submission_preserve_metadata(self):
        # Restrict the fixture to one task/participant for the individual ZIP.
        self.manifest['sessions'] = self.manifest['sessions'][:1]
        self.codings['entries'] = [r for r in self.codings['entries'] if r['source_ref'].startswith('S-A/')]
        self.save()
        run = e.build(self.root/'manifest.json', self.root/'codings.json', self.root/'runs')
        structure = s.build([run], self.root/'individual')
        bundle = m.prepare([run], structure, self.root/'bundles')
        expected = self.manifest['model_context']
        with zipfile.ZipFile(bundle/'research-patterns.zip') as z:
            self.assertEqual(json.loads(z.read('extraction-001/coverage.json'))['model_context'], expected)
            value = json.loads(z.read('individual/session-structure.json'))
            self.assertEqual(value['coverage'][0]['model_context'], expected)
            self.assertEqual(value['source_runs'][0]['model_context'], expected)
            self.assertEqual(z.testzip(), None)
        c.load_run(run, 'synthetic')


if __name__ == '__main__': unittest.main()
