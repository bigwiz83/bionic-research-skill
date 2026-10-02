"""Validate model-observed fine actions and responses. Does not classify raw text."""
import re
import extract as e
import grade_and_trace as g
import observation_axes as x

FACETS=['target','method','criterion','constraints','requested_output','trigger_condition','control_boundary','prior_result_reference']
SUBTYPES={
    'goal_specification':['specify_target','specify_condition','specify_output','information_search','other_explicit'],
    'task_decomposition':['split_work','specify_order','other_explicit'],
    'delegation_control':['delegate_work','limit_scope','require_approval','halt_work','other_explicit'],
    'verification_request':['request_evidence','supporting_reference_search','source_crosscheck','recomputation','check_duplicates','check_missing','check_exceptions','check_consistency','other_explicit'],
    'error_correction':['correct_error','restore_omission','revise_condition','other_explicit'],
    'reuse_resume':['reuse_artifact','resume_work','other_explicit'],
    'data_structure_inquiry':['inspect_structure','other_explicit']}
RESPONSE_ASPECTS=['action','method','output','limitation']
SEARCH_SUBTYPES={'information_search','supporting_reference_search'}
SEARCH_FIELDS=['search_terms','source_constraints','selection_criteria','claim_reference']

def spans(value,action,length):
    e.require(isinstance(value,list) and value,'atom_evidence_required')
    for span in value:
        g.keys(span,['ref','start','end'],'atom_span_fields')
        e.require(span['ref']==action['source_ref'] and type(span['start']) is int and type(span['end']) is int
            and type(length) is int and 0<=span['start']<span['end']<=length,'atom_own_span_bounds')

def observations(value,action,length):
    e.require(value is None or isinstance(value,list),'atom_facet_list_or_unknown')
    for item in value or []:
        g.keys(item,['value','evidence'],'atom_facet_fields')
        e.require(isinstance(item['value'],str) and 0<len(item['value'])<=800,'atom_abstraction_length')
        spans(item['evidence'],action,length)

def validate(path,participant_id,actions):
    users=[a for a in actions if a['actor']=='user']
    responses=[a for a in actions if a['actor'] in {'assistant','tool'}]
    if path is None:
        return {'atom_schema_version':'1.2.0','participant_id':participant_id,
            'entries':[{'event_id':a['event_id'],'observed_text_length':None,'atoms':None,'relations':None,
                'observation_axes':x.unknown()} for a in users],
            'responses':[{'event_id':a['event_id'],'observed_text_length':None,'observations':None} for a in responses]}
    doc=e.read_json(path)
    g.keys(doc,['atom_schema_version','participant_id','entries','responses'],'atom_header_fields')
    e.require(doc['atom_schema_version'] in {'1.0.0','1.1.0','1.2.0'} and doc['participant_id']==participant_id,'atom_header')
    by_id={a['event_id']:a for a in actions}
    for name,expected in [('entries',users),('responses',responses)]:
        rows=doc[name]
        e.require(isinstance(rows,list) and all(isinstance(row,dict) for row in rows),'atom_entries_objects')
        e.require({row.get('event_id') for row in rows}=={a['event_id'] for a in expected} and len(rows)==len(expected),'atom_exact_event_scope')
    source_actions={a['source_ref']:a for a in actions}
    source_lengths={by_id[row['event_id']]['source_ref']:row.get('observed_text_length')
        for row in doc['entries']+doc['responses']}
    all_ids=set()
    for row in doc['entries']:
        g.keys(row,['event_id','observed_text_length','atoms','relations']+
            (['observation_axes'] if doc['atom_schema_version']=='1.2.0' else []),'atom_entry_fields')
        action=by_id[row['event_id']]
        length=row['observed_text_length']
        e.require(length is None or type(length) is int and length>=0,'atom_observed_length')
        if doc['atom_schema_version']=='1.2.0':
            x.validate(row,action,source_actions,source_lengths,spans)
        e.require(row['atoms'] is None or isinstance(row['atoms'],list),'atom_list_or_unknown')
        if row['atoms'] is None:
            e.require(row['relations'] is None,'unknown_atoms_cannot_have_relations')
            continue
        e.require(type(length) is int and isinstance(row['relations'],list),'observed_atoms_need_length_and_relations')
        local_ids=set()
        for atom in row['atoms']:
            g.keys(atom,['atom_id','category','subtype','facets','evidence']+
                (['search_details'] if 'search_details' in atom else []),'atom_fields')
            aid=atom['atom_id']
            e.require(isinstance(aid,str) and re.fullmatch(r'A-[A-Za-z0-9_-]{1,100}',aid) and aid not in all_ids,'atom_unique_id')
            local_ids.add(aid); all_ids.add(aid)
            cat=atom['category']
            e.require(isinstance(cat,str) and cat in SUBTYPES or cat is None,'atom_category')
            e.require(atom['subtype'] in (SUBTYPES[cat] if cat else ['other_explicit']),'atom_subtype')
            if atom['subtype'] in SEARCH_SUBTYPES:
                e.require(doc['atom_schema_version'] in {'1.1.0','1.2.0'} and 'search_details' in atom,'search_contract_required')
                g.keys(atom['search_details'],SEARCH_FIELDS,'search_detail_fields')
                for values in atom['search_details'].values():observations(values,action,length)
            else:e.require('search_details' not in atom,'search_details_only_for_search_actions')
            spans(atom['evidence'],action,length)
            g.keys(atom['facets'],FACETS,'atom_facet_set')
            for values in atom['facets'].values():
                observations(values,action,length)
        graph={aid:set() for aid in local_ids}
        parallel=set()
        for relation in row['relations']:
            g.keys(relation,['from_atom','to_atom','kind','evidence'],'atom_relation_fields')
            left,right=relation['from_atom'],relation['to_atom']
            e.require(left in local_ids and right in local_ids and left!=right,'atom_relation_same_utterance')
            e.require(relation['kind'] in {'explicit_before','explicit_parallel'},'atom_relation_kind')
            spans(relation['evidence'],action,length)
            if relation['kind']=='explicit_before': graph[left].add(right)
            else: parallel.add(frozenset([left,right]))
        visiting,done=set(),set()
        def visit(node):
            e.require(node not in visiting,'atom_order_cycle')
            if node in done:return
            visiting.add(node)
            for other in graph[node]:visit(other)
            visiting.remove(node);done.add(node)
        for node in graph:visit(node)
        def reaches(node,target):
            return any(other==target or reaches(other,target) for other in graph[node])
        for pair in parallel:
            left,right=tuple(pair)
            e.require(not reaches(left,right) and not reaches(right,left),'atom_parallel_order_conflict')
    for row in doc['responses']:
        g.keys(row,['event_id','observed_text_length','observations'],'response_entry_fields')
        action=by_id[row['event_id']]
        length=row['observed_text_length']
        e.require(length is None or type(length) is int and length>=0,'response_observed_length')
        e.require(row['observations'] is None or isinstance(row['observations'],list),'response_list_or_unknown')
        if row['observations'] is not None:e.require(type(length) is int,'response_observed_length_required')
        for obs in row['observations'] or []:
            g.keys(obs,['aspect','value','evidence'],'response_observation_fields')
            e.require(obs['aspect'] in RESPONSE_ASPECTS,'response_aspect')
            observations([{'value':obs['value'],'evidence':obs['evidence']}],action,length)
    return doc

def enrich(doc,processes,actions):
    by_event={row['event_id']:row for row in doc['entries']}
    response_by_event={row['event_id']:row for row in doc['responses']}
    source_by_event={a['event_id']:a for a in actions}
    mismatches=[]
    for proc in processes:
        for module in proc['modules']:
            row=by_event[module['user_event_id']]
            module['fine_action_ids']=None if row['atoms'] is None else [atom['atom_id'] for atom in row['atoms']]
            module['observation_axes']=x.from_row(row)
            module['explicit_within_utterance_relations']=row['relations']
            module['response_observation_event_ids']=[eid for eid in module['following_event_ids'] if eid in response_by_event]
            module['response_link_basis']='observation_window_not_proven_request_fulfillment'
            cats={atom['category'] for atom in row['atoms'] or [] if atom['category'] is not None}
            missing=cats-set(source_by_event[row['event_id']]['categories'])
            if missing:mismatches.append({'event_id':row['event_id'],'fine_categories_missing_from_source_coding':sorted(missing),'status':'review_required_source_not_overwritten'})
    return mismatches

def csv_rows(doc):
    return [{'event_id':row['event_id'],'atom_id':atom['atom_id'],'category':atom['category'],'subtype':atom['subtype'],
        **{name:e.canonical(values) for name,values in atom['facets'].items()},
        'search_details':e.canonical(atom.get('search_details')),'evidence':atom['evidence']}
        for row in doc['entries'] for atom in row['atoms'] or []]
