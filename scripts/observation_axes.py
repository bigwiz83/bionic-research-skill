"""Validate orthogonal utterance observations; never infer cognition or classify text."""
from collections import Counter
import extract as e
import grade_and_trace as g

AXES = {
    'input_transformation': ['verbatim', 'edited_summary', 'mixed', 'other_explicit'],
    'query_mode': ['factual', 'explanation', 'hypothesis_probe', 'counterfactual_probe',
        'alternative_comparison', 'task_requirement_aligned', 'other_explicit'],
    'role_assignment': ['assigned_role'],
    'reasoning_target': ['problem_definition', 'priority_setting', 'hypothesis_generation',
        'hypothesis_evaluation', 'judgement', 'planning', 'self_reflection', 'other_explicit']}
BASES = {'explicit_statement', 'observable_expression', 'observed_comparison'}


def unknown():
    return {axis: None for axis in AXES}


def validate(row, action, actions, lengths, own_spans):
    axes = row['observation_axes']
    g.keys(axes, list(AXES), 'axis_set')
    for axis, items in axes.items():
        e.require(items is None or isinstance(items, list), 'axis_list_or_unknown')
        if items is not None:
            e.require(type(row['observed_text_length']) is int, 'axis_observed_length_required')
        for item in items or []:
            g.keys(item, ['code', 'value', 'basis', 'evidence', 'comparison_evidence'], 'axis_item_fields')
            e.require(isinstance(item['code'], str) and item['code'] in AXES[axis], 'axis_code')
            e.require(isinstance(item['value'], str) and 0 < len(item['value']) <= 800, 'axis_abstraction_length')
            e.require(isinstance(item['basis'], str) and item['basis'] in BASES, 'axis_basis')
            own_spans(item['evidence'], action, row['observed_text_length'])
            comparisons = item['comparison_evidence']
            e.require(isinstance(comparisons, list), 'axis_comparison_list')
            if item['basis'] == 'observed_comparison':
                e.require(comparisons, 'axis_comparison_required')
            else:
                e.require(not comparisons, 'axis_comparison_basis_required')
            if axis == 'input_transformation':
                e.require(item['basis'] != 'observable_expression', 'axis_input_needs_statement_or_comparison')
            if item['code'] == 'task_requirement_aligned':
                e.require(item['basis'] != 'observable_expression', 'axis_alignment_needs_statement_or_comparison')
            for span in comparisons:
                g.keys(span, ['ref', 'start', 'end'], 'axis_comparison_span_fields')
                other = actions.get(span['ref'])
                length = lengths.get(span['ref'])
                e.require(other is not None and other['source_ref'] != action['source_ref']
                    and other['session_id'] == action['session_id']
                    and other['task_id'] == action['task_id']
                    and other['source_index'] < action['source_index']
                    and type(length) is int and type(span['start']) is int and type(span['end']) is int
                    and 0 <= span['start'] < span['end'] <= length, 'axis_comparison_read_prior_scope_bounds')


def from_row(row):
    return row.get('observation_axes', unknown())


def summarize(doc):
    result = {}
    for axis in AXES:
        values = [from_row(row)[axis] for row in doc['entries']]
        counts = Counter(code for items in values if items is not None
            for code in {item['code'] for item in items})
        result[axis] = {'total_user_events': len(values),
            'unknown_events': sum(items is None for items in values),
            'observed_absent_events': sum(items == [] for items in values),
            'events_with_observations': sum(bool(items) for items in values),
            'events_by_code': dict(sorted(counts.items())),
            'meaning': 'observed_utterance_codes_not_trait_score_or_causal_effect'}
    return result


def csv_rows(doc):
    return [{'event_id': row['event_id'],
        'axis_contract': '1.0.0' if 'observation_axes' in row else 'not_collected_legacy',
        **{axis: e.canonical(items) for axis, items in from_row(row).items()}}
        for row in doc['entries']]
