"""Staff-only presentation of held source evidence, without runtime paths or raw XML."""
import math


def normalized(item, index):
    def number(value):return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None
    interval=item.get('time_interval') or {}
    location=item.get('location') or {}
    if not isinstance(interval,dict):interval={}
    if not isinstance(location,dict):location={}
    a=number(item.get('start_seconds',interval.get('start_seconds',location.get('start_seconds'))))
    b=number(item.get('end_seconds',interval.get('end_seconds',location.get('end_seconds'))))
    reasons=item.get('reasons') or [item.get('reason') or 'source_review_required']
    if not isinstance(reasons,list):reasons=[str(reasons)]
    text=next((item.get(k) for k in ('text','observed_text','source_text','original_text') if isinstance(item.get(k),str) and item.get(k).strip()),'')
    modality=item.get('modality')
    if modality not in ('audio','visual'):modality='document'
    locator=item.get('source_locator') or item.get('locator') or ''
    if not isinstance(locator,str):locator=''
    return {'id':str(item.get('id') or index),'modality':modality,'text':text[:8000],
            'context':str(item.get('source_context') or '')[:2000],
            'text_truncated':len(text)>8000,'source_locator':locator[:400],
            'start_seconds':a,'end_seconds':b,'reasons':[str(r)[:160] for r in reasons]}
