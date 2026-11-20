"""Modality-independent routing, NOT a classifier of semantic importance.

Caller must assess the defect's effect on QA/quiz/script meaning from evidence.
Low-impact defects remain excluded until administrator review; low priority is
not correctness, deletion, or permission to publish.
"""
import copy

POLICY='low_impact_error_admin_hold_v1'
CONSUMERS=('chatbot','quiz','shorts_script')


def hold_for_administrator(record,reason,evidence):
    if not reason.strip() or not evidence:raise ValueError('impact_assessment_evidence_required')
    result=copy.deepcopy(record)
    reasons=sorted(set(result.get('selection_reasons',result.get('reasons',[]))+['low_impact_error_administrator_review']))
    result.update(eligible_for_chunking=False,approved_for_rag=False,
        eligible_for_generation={consumer:False for consumer in CONSUMERS},
        judgment='held',selection_reasons=reasons,reasons=reasons,
        impact_review={'policy':POLICY,'impact':'low','status':'pending_administrator',
                       'route':'administrator','reason':reason,'evidence':copy.deepcopy(evidence),
                       'original_preserved':True})
    return result
