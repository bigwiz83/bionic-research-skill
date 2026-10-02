"""Synthetic scope, uncertainty, legacy and complete export checks for observation axes."""
import copy
import csv
import io
import json
import unittest
from unittest.mock import patch
import zipfile
import test_atoms_submission as t
import observation_axes as x
import behavior_atoms as b
import extract as e
import structure_session as s
import submission as m


class AxisTests(unittest.TestCase):
    setUpClass = classmethod(t.AtomTests.setUpClass.__func__)
    tearDownClass = classmethod(t.AtomTests.tearDownClass.__func__)
    doc = t.AtomTests.doc
    use = t.AtomTests.use

    def new_doc(self):
        doc, value = self.doc()
        doc['atom_schema_version'] = '1.2.0'
        for row in doc['entries']:
            row['observation_axes'] = x.unknown()
        return doc, value

    def item(self, row, code='explanation', basis='observable_expression'):
        return {'code': code, 'value': '새로 만든 합성 요청의 관찰 추상화', 'basis': basis,
            'evidence': copy.deepcopy(row['atoms'][0]['evidence']), 'comparison_evidence': []}

    def test_axes_orthogonal_multiple_codes_no_new_modules_or_grading(self):
        doc, old = self.new_doc()
        row = doc['entries'][0]
        row['observation_axes']['query_mode'] = [self.item(row), self.item(row, 'alternative_comparison')]
        row['observation_axes']['role_assignment'] = [self.item(row, 'assigned_role')]
        row['observation_axes']['reasoning_target'] = [self.item(row, 'hypothesis_evaluation')]
        value = self.use(doc)
        self.assertEqual(value['observed_actions'], old['observed_actions'])
        self.assertEqual(len(value['processes'][0]['modules']), 5)
        self.assertEqual(value['processes'][0]['modules'][0]['observation_axes'], row['observation_axes'])
        self.assertEqual(value['processes'][0]['modules'][0]['explicit_within_utterance_relations'], [])
        self.assertFalse(value['grading_performed'])
        self.assertFalse(value['grouping_performed'])

    def test_no_atom_input_still_exported_one_row_per_user(self):
        doc, _ = self.new_doc()
        row = doc['entries'][0]
        item = self.item(row, 'edited_summary', 'explicit_statement')
        row['atoms'] = []
        row['observation_axes']['input_transformation'] = [item]
        result = self.use(doc)
        exported = x.csv_rows(result['behavior_atoms'])
        self.assertEqual(len(exported), 5)
        self.assertEqual(json.loads(exported[0]['input_transformation']), [item])

    def test_absent_unknown_and_repeated_code_denominators_separate(self):
        doc, _ = self.new_doc()
        doc['entries'][0]['observation_axes']['query_mode'] = []
        row = doc['entries'][1]
        row['observation_axes']['query_mode'] = [self.item(row), self.item(row)]
        counts = self.use(doc)['observation_axis_summary']['query_mode']
        self.assertEqual((counts['unknown_events'], counts['observed_absent_events'], counts['events_with_observations']), (3, 1, 1))
        self.assertEqual(counts['events_by_code'], {'explanation': 1})

    def test_legacy_and_omitted_axes_are_unknown_not_absent(self):
        for version in ['1.0.0', '1.1.0']:
            doc, _ = self.doc()
            doc['atom_schema_version'] = version
            value = self.use(doc)
            self.assertEqual(value['observation_axis_summary']['query_mode']['unknown_events'], 5)
            self.assertEqual(value['processes'][0]['modules'][0]['observation_axes'], x.unknown())
        value = s.analyze([self.runs[0]])
        self.assertEqual(value['observation_axis_summary']['query_mode']['unknown_events'], 5)

    def test_complete_axis_keys_typed_codes_and_own_evidence_required(self):
        doc, _ = self.new_doc()
        del doc['entries'][0]['observation_axes']['role_assignment']
        with self.assertRaisesRegex(e.ContractError, 'axis_set'): self.use(doc)
        for field, bad, error in [('code', 'understands_well', 'axis_code'),
                                  ('basis', 'inferred_psychology', 'axis_basis')]:
            doc, _ = self.new_doc()
            row = doc['entries'][0]
            item = self.item(row)
            item[field] = bad
            row['observation_axes']['query_mode'] = [item]
            with self.assertRaisesRegex(e.ContractError, error): self.use(doc)
        doc, _ = self.new_doc()
        row = doc['entries'][0]
        item = self.item(row)
        item['evidence'][0]['ref'] = 'UNREAD/row-000001'
        row['observation_axes']['query_mode'] = [item]
        with self.assertRaisesRegex(e.ContractError, 'own_span'): self.use(doc)

    def test_input_and_rubric_cannot_be_inferred_from_form(self):
        for axis, code in [('input_transformation', 'verbatim'), ('query_mode', 'task_requirement_aligned')]:
            doc, _ = self.new_doc()
            row = doc['entries'][0]
            row['observation_axes'][axis] = [self.item(row, code)]
            with self.assertRaisesRegex(e.ContractError, 'needs_statement_or_comparison'): self.use(doc)
            row['observation_axes'][axis][0]['basis'] = 'explicit_statement'
            self.use(doc)

    def test_read_prior_context_comparison_and_reject_unread_future_cross_session(self):
        doc, value = self.new_doc()
        row = doc['entries'][1]
        item = self.item(row, 'edited_summary', 'observed_comparison')
        item['comparison_evidence'] = copy.deepcopy(doc['entries'][0]['atoms'][0]['evidence'])
        row['observation_axes']['input_transformation'] = [item]
        self.use(doc)
        saved = copy.deepcopy(item['comparison_evidence'])
        item['comparison_evidence'] = []
        with self.assertRaisesRegex(e.ContractError, 'comparison_required'): self.use(doc)
        for span in [{'ref': 'UNREAD/row-000001', 'start': 0, 'end': 1},
                     doc['entries'][2]['atoms'][0]['evidence'][0],
                     {**saved[0], 'end': 10000}]:
            item['comparison_evidence'] = [span]
            with self.assertRaisesRegex(e.ContractError, 'prior_scope_bounds'): self.use(doc)
        item['comparison_evidence'] = saved
        action = next(a for a in value['observed_actions'] if a['event_id'] == doc['entries'][0]['event_id'])
        changed = copy.deepcopy(value['observed_actions'])
        next(a for a in changed if a['event_id'] == action['event_id'])['session_id'] = 'OTHER'
        e.write_json(self.path, doc)
        with self.assertRaisesRegex(e.ContractError, 'prior_scope_bounds'):
            b.validate(self.path, doc['participant_id'], changed)

    def test_ai_context_length_required_and_user_axis_not_backfilled(self):
        doc, value = self.new_doc()
        row = doc['entries'][1]
        response = doc['responses'][0]
        action = next(a for a in value['observed_actions'] if a['event_id'] == response['event_id'])
        item = self.item(row, 'edited_summary', 'observed_comparison')
        item['comparison_evidence'] = [{'ref': action['source_ref'], 'start': 0, 'end': 2}]
        row['observation_axes']['input_transformation'] = [item]
        with self.assertRaisesRegex(e.ContractError, 'prior_scope_bounds'): self.use(doc)
        response['observed_text_length'] = 20
        result = self.use(doc)
        self.assertIsNone(result['behavior_atoms']['entries'][0]['observation_axes']['role_assignment'])

    def test_axes_with_unknown_atoms_require_actual_length(self):
        doc, _ = self.new_doc()
        row = doc['entries'][0]
        item = self.item(row)
        row['atoms'] = row['relations'] = None
        row['observation_axes']['query_mode'] = [item]
        self.use(doc)
        row['observed_text_length'] = None
        with self.assertRaisesRegex(e.ContractError, 'axis_observed_length_required'): self.use(doc)

    def test_json_csv_report_zip_preserve_axes_no_mail_and_legacy_bundle(self):
        doc, _ = self.new_doc()
        row = doc['entries'][0]
        row['observation_axes']['query_mode'] = [self.item(row)]
        e.write_json(self.path, doc)
        folder = s.build([self.runs[0]], self.root/'axis-output', atom_path=self.path)
        with patch.object(m.smtplib, 'SMTP', side_effect=AssertionError('must not send')):
            bundle = m.prepare([self.runs[0]], folder, self.root/'axis-bundles')
        with zipfile.ZipFile(bundle/'research-patterns.zip') as z:
            rows = list(csv.DictReader(io.StringIO(z.read('individual/observation-axes.csv').decode('utf-8-sig'))))
            self.assertEqual(len(rows), 5)
            self.assertEqual(json.loads(rows[0]['query_mode']), row['observation_axes']['query_mode'])
            self.assertEqual(json.loads(z.read('individual/behavior-atoms.json'))['entries'][0]['observation_axes'], row['observation_axes'])
            self.assertIn('explanation (observable_expression)', z.read('individual/report.md').decode('utf-8'))
        self.assertEqual(e.read_json(bundle/'delivery-state.json')['status'], 'prepared_not_sent')
        # Reconstruct an older package without the additive CSV or contract marker.
        structure = e.read_json(folder/'session-structure.json')
        structure.pop('observation_axis_contract')
        e.write_json(folder/'session-structure.json', structure)
        integrity = e.read_json(folder/'integrity.json')
        integrity['files'].pop('observation-axes.csv')
        integrity['files']['session-structure.json'] = m.digest((folder/'session-structure.json').read_bytes())
        e.write_json(folder/'integrity.json', integrity)
        legacy = m.prepare([self.runs[0]], folder, self.root/'legacy-bundles')
        with zipfile.ZipFile(legacy/'research-patterns.zip') as z:
            self.assertNotIn('individual/observation-axes.csv', z.namelist())


if __name__ == '__main__': unittest.main()
