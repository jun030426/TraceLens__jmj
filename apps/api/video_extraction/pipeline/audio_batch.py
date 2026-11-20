"""Batch transport only: keep each original primary/context and V4 verdict gate.

Two independent requests inspect the same ordered audio pairs. No text from the
reference or the first response enters the blind request. Global attachment
indices are checked before conversion to the existing per-pair contract.
"""
import copy
import json
from pathlib import Path

from video_extraction.audio import audio_finalize as final
from video_extraction.shared.common import read, save, signature, validate

POLICY = 'independent_primary_pairs_v1'
MAX_TASKS = 8
MAX_SPAN = 60
MAX_MEDIA_BYTES = 12 * 1024 * 1024


def groups(tasks):
    pending = []
    size = 0
    for task in tasks:
        amount = sum(Path(task[k]).stat().st_size for k in ('target_clip', 'context_clip'))
        if pending and (len(pending) >= MAX_TASKS or
                        task['interval'][1] - pending[0]['interval'][0] > MAX_SPAN or
                        size + amount > MAX_MEDIA_BYTES):
            yield pending
            pending = []
            size = 0
        pending.append(task)
        size += amount
    if pending:
        yield pending


def schema(kind, count):
    item = copy.deepcopy(final.BLIND_V4 if kind == 'blind' else final.REVIEW_V4)
    item['properties']['target_scope']['properties']['audio_index']['enum'] = list(range(0, count * 2, 2))
    entry = final.obj({'task_id': final.TEXT, 'reading': item})
    return final.obj({'items': {'type': 'array', 'items': entry, 'minItems': count, 'maxItems': count}})


def bundle(tasks, folder):
    media, bindings, blind, review = [], {}, [], []
    for i, task in enumerate(tasks):
        if task['role'] != 'control' or task.get('followup_reason'):
            raise ValueError('audio_batch_initial_controls_only')
        pair, binding, data, neighbors = final.primary_context_bundle(folder, task)
        media.extend(pair)
        bindings[task['id']] = binding
        data = {**data, 'task_id': task['id'], 'primary_audio_index': 2*i,
                'context_audio_index': 2*i+1, 'audio_count': len(tasks)*2}
        blind.append(data)
        review.append({**data, 'current_text': task['before'], 'proposed_text': task['after'],
                       'neighboring_transcripts_text_only': neighbors, 'added_fragments': []})
    return media, bindings, blind, review


def prompt(kind, data):
    # V4's file 0/file 1 references are explicitly local to each pair. Responses
    # use the actual global attachment index, not an inferred time slice.
    rules = final.V4_BLIND_PROMPT if kind == 'blind' else final.V4_REVIEW_PROMPT
    # Remove single-pair numbering from the shared wording: a later hard-coded
    # audio_index=0 instruction can otherwise contradict the batch mapping.
    rules = rules.replace('Two audio files are attached IN ORDER:\n0 = PRIMARY target only. 1 = CONTEXT for understanding, not for extra transcript content.',
        "This task has two attachments: primary_audio_index is PRIMARY target only; context_audio_index is CONTEXT for understanding, never extra transcript content.")
    rules = rules.replace('audio_index=0', 'audio_index equal to this task\'s primary_audio_index')
    rules = rules.replace('file 0', "this task's PRIMARY attachment").replace('file 1', "this task's CONTEXT attachment")
    return ("Inspect independent tasks, with a separate PRIMARY/CONTEXT audio pair for each. "
            "In the per-task rules below, file 0 means that task's primary_audio_index and "
            "file 1 means that task's context_audio_index. Never borrow text from another "
            "task or score the whole batch as one recording. Return exactly one item per "
            "task_id, preserving that ID. In each reading.target_scope.audio_index return "
            "the actual GLOBAL primary_audio_index from DATA. All timestamps remain local "
            "to that primary file starting at zero. Every original flag is required for "
            "every task; uncertain tasks stay uncertain. The following per-pair rules apply "
            "independently, with the global index substitution just described.\n" + rules +
            json.dumps({'tasks': data}, ensure_ascii=False))


def normalize(raw, tasks, kind):
    validate(raw, schema(kind, len(tasks)))
    items = raw['items']
    if len({item['task_id'] for item in items}) != len(tasks):
        raise ValueError('audio_batch_duplicate_or_missing_task')
    by_id = {item['task_id']: item['reading'] for item in items}
    if set(by_id) != {task['id'] for task in tasks}:
        raise ValueError('audio_batch_wrong_task_ids')
    result = {}
    for i, task in enumerate(tasks):
        value = copy.deepcopy(by_id[task['id']])
        if value['target_scope']['audio_index'] != 2*i:
            raise ValueError('audio_batch_wrong_primary_attachment')
        value['target_scope']['audio_index'] = 0
        validate(value, final.BLIND_V4 if kind == 'blind' else final.REVIEW_V4)
        result[task['id']] = value
    return result


def validate_outcome(task, outcome, folder):
    """Replay the mapping from the preserved raw batch; never trust copied flags."""
    receipt_path = Path(folder)/'review-batches'/(outcome['batch_id']+'.json')
    receipt = read(receipt_path)
    tasks = receipt['tasks']
    if receipt['policy'] != POLICY or receipt['batch_id'] != signature({'policy': POLICY, 'tasks': tasks}):
        raise ValueError('audio_batch_binding_changed')
    if task not in tasks:
        raise ValueError('audio_batch_task_changed')
    _, bindings, _, _ = bundle(tasks, folder)
    if bindings != receipt['input_bindings']:
        raise ValueError('audio_batch_source_changed')
    for kind in ('blind', 'review'):
        values = normalize(receipt[kind], tasks, kind)
        if values[task['id']] != outcome[kind] or bindings[task['id']] != outcome['input_bindings'][kind]:
            raise ValueError('audio_batch_reading_changed')
    if outcome['task_signature'] != signature(task) or final.decision(task, outcome['blind'], outcome['review']) != outcome['gate']:
        raise ValueError('audio_batch_verdict_changed')


def run(tasks, folder, client):
    folder = Path(folder)
    batch_id = signature({'policy': POLICY, 'tasks': tasks})
    receipt_path = folder/'review-batches'/(batch_id+'.json')
    media, bindings, blind_data, review_data = bundle(tasks, folder)
    split_path = folder/'review-batch-splits'/(batch_id+'.json')
    def smaller():
        midpoint=len(tasks)//2
        return {**run(tasks[:midpoint],folder,client),**run(tasks[midpoint:],folder,client)}
    if split_path.exists():
        split=read(split_path)
        if split['tasks']!=tasks or split['input_bindings']!=bindings or split['policy']!=POLICY:
            raise ValueError('audio_batch_split_binding_changed')
        if len(tasks)<2:raise ValueError('audio_batch_singleton_cannot_split')
        return smaller()
    if receipt_path.exists():
        receipt = read(receipt_path)
        if receipt['tasks'] != tasks or receipt['input_bindings'] != bindings or receipt['policy'] != POLICY or receipt['batch_id'] != batch_id:
            raise ValueError('audio_batch_binding_changed')
    else:
        raw = {}
        for kind,data in [('blind',blind_data),('review',review_data)]:
            raw[kind] = client.call('connected-audio-batch-'+kind+'-v1',media,prompt(kind,data),schema(kind,len(tasks)))
            try:
                normalize(raw[kind],tasks,kind)
            except ValueError as exc:
                if len(tasks)<2 or str(exc) not in ('audio_batch_wrong_primary_attachment',
                        'audio_batch_duplicate_or_missing_task','audio_batch_wrong_task_ids'):
                    raise
                # Reject the entire ambiguous envelope. Smaller independent pairs
                # get BOTH fresh readings; never repair indices or copy verdicts.
                save(split_path,{'policy':POLICY,'tasks':tasks,'input_bindings':bindings,
                    'reason':str(exc),'rejected_kind':kind,'rejected_responses':raw})
                return smaller()
        blind,review=raw['blind'],raw['review']
        if bundle(tasks, folder)[1] != bindings:
            raise ValueError('audio_changed_during_batch_review')
        receipt = {'policy': POLICY, 'batch_id': batch_id, 'tasks': tasks,
                   'input_bindings': bindings, 'blind': blind, 'review': review}
        save(receipt_path, receipt)
    blind = normalize(receipt['blind'], tasks, 'blind')
    review = normalize(receipt['review'], tasks, 'review')
    outcomes = {}
    for task in tasks:
        key = task['id']
        outcome = {'task_id': key, 'task_signature': signature(task), 'batch_id': batch_id,
                   'blind': blind[key], 'review': review[key],
                   'input_bindings': {'blind': bindings[key], 'review': bindings[key]},
                   'gate': final.decision(task, blind[key], review[key])}
        save(folder/'reviews'/(key+'.json'), outcome)
        outcomes[key] = outcome
    return outcomes
