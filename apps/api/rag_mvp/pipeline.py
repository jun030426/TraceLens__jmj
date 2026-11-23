"""Single-turn grounded QA. Quote validation is not semantic fact verification."""
#검색부터 답변까지 연결. 검색 자료를 Gemini에 전달하고 답변의 출처·인용을 검사해. 결과와 처리시간을 JSON·HTML로 저장
import html
import re
import time
import unicodedata

from video_extraction.shared.common import now, save, signature, validate
from .corpus import canonical
from .providers import ANSWER_SCHEMA
from .evidence import retrieve_evidence
from .markdown_tools import supported_code, render as render_markdown, asset
from .source_context import citation_texts,linked_comments


def insufficient_evidence_message(question):
    # Do not publish unverified model-generated causes/fixes through the reason field.
    message='현재 검색된 자료만으로는 확답하기 어렵습니다. '
    if re.search(r'코드|오류|에러|버그|실행|디버깅|파이썬|자바|\b(?:python|javascript|java|typescript|error|exception|traceback|debug)\b',question,re.I):
        return message+'관련 코드의 최소 예제와 기대한 결과·실제 결과를 알려주세요. 오류 메시지나 실행 환경·버전이 있다면 함께 확인하겠습니다. 이미 제공했다면 추가로 관련 자료가 필요합니다.'
    return message+'질문과 관련된 자료의 해당 부분이나 구체적인 상황을 더 알려주시면 그 근거로 다시 확인하겠습니다.'


def _quote_in_text(quote, text):
    if not quote:
        return False
    canon_text = canonical(text)
    if quote in canon_text:
        return True
    # 코드 블록·인라인 코드가 아닌 일반 자연어 문장은 줄바꿈·연속 공백만 단일 공백으로 정규화해 비교한다.
    if '`' in quote or re.search(r'(?m)^\s*~{3,}', quote):
        return False
    norm_quote = re.sub(r'\s+', ' ', unicodedata.normalize('NFC', quote)).strip()
    norm_text = re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text))
    return len(norm_quote) >= 4 and norm_quote in norm_text


def check_answer(candidate, hits, question=''):
    validate(candidate, ANSWER_SCHEMA)
    byid={h['id']:h for h in hits}
    if not candidate['answerable']:
        return {'status':'abstained','claims':[], 'reason':insufficient_evidence_message(question)}
    if not candidate['claims']:
        return {'status':'held','claims':[], 'reason':'답변의 근거 인용이 없습니다.'}
    checked=[]
    for claim in candidate['claims']:
        source=byid.get(claim['source_id'])
        quote=canonical(claim['quote']).strip()
        if source is None or len(quote)<4 or not any(_quote_in_text(quote, t) for t in citation_texts(source)) or not claim['text'].strip():
            return {'status':'held','claims':[], 'reason':'출처 또는 원문 인용 검증에 실패해 답변을 보류했습니다.'}
        try:
            if not supported_code(claim['text'],source):
                return {'status':'held','claims':[], 'reason':'코드의 내용·들여쓰기·전체 범위가 검색 원문과 일치하지 않아 답변을 보류했습니다.'}
        except ValueError:
            return {'status':'held','claims':[], 'reason':'코드 블록이 닫히지 않았거나 불완전해 답변을 보류했습니다.'}
        locator=source.get('source_locator',f"슬라이드 {source['slide_number']}")
        if not _quote_in_text(quote, source['text']):
            c=next(c for c in linked_comments(source) if _quote_in_text(quote, c['text']))
            locator=f"주석 줄 {c['line_start']}–{c['line_end']} (관련 코드 {locator})"
        checked.append({**claim,'source_file':source['source_file'],'slide_number':source['slide_number'],
                        'source_locator':locator})
    return {'status':'citation_checked','claims':checked,'reason':'인용문 존재 여부 확인 완료. 답변 의미의 정확성을 보증하는 검사는 아닙니다.'}


def ask(out, corpus, client, question):
    if not isinstance(question,str) or not question.strip() or len(question)>2000:raise ValueError('질문은 1~2000자로 입력하세요.')
    start=time.monotonic();before=dict(client.stats)
    hits=retrieve_evidence(out,corpus,client,question)['sources']
    retrieval_seconds=time.monotonic()-start
    candidate=client.answer(question,hits) if hits else {'answerable':False,'claims':[],'reason':'no sources'}
    result={'at':now(),'question':question,'corpus_signature':corpus['signature'],
        'embedding_model':client.embedding_model,'answer_model':client.answer_model,
        'hits':hits,'candidate':candidate,**check_answer(candidate,hits,question),
        'timing':{'retrieval_seconds':retrieval_seconds,'total_seconds':time.monotonic()-start},
        'api_stats':{k:client.stats[k]-before[k] for k in before}}
    key=signature({'question':question,'at':result['at']})
    save(out/'answers'/(key+'.json'),result)
    save(out/'latest-answer.json',result)
    render(out,result)
    return result


def display(result):
    print('\n질문: '+result['question'])
    if not result['claims']:print(result['reason'])
    for c in result['claims']:
        print(f"\n{c['text']}\n  출처: {c['source_file']} · {c.get('source_locator',str(c['slide_number']))}\n  원문: {c['quote']}")
    print(f"\n상태: {result['status']} | 소요 {result['timing']['total_seconds']:.1f}초")


def render(out,result):
    esc=html.escape
    body=''.join(f"<article><div class='markdown-body'>{render_markdown(c['text'])}</div><small>{esc(c['source_file'])} · {esc(c.get('source_locator','슬라이드 '+str(c['slide_number'])))}</small><pre class='source-literal'>{esc(c['quote'])}</pre></article>" for c in result['claims'])
    content=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>최소 RAG 답변</title>
    <style>body{{max-width:850px;margin:48px auto;padding:0 24px;font:17px/1.7 system-ui;background:#f4f6fa;color:#182238}}article{{background:white;padding:20px;margin:16px 0;border-radius:12px}}blockquote{{white-space:pre-wrap;border-left:3px solid #678;padding-left:16px}}small{{color:#526}}</style>
    <h1>강의자료 RAG · 로컬 MVP</h1><p>{esc(result['question'])}</p>{body}
    <p>상태: {esc(result['status'])} — {esc(result['reason'])}</p>
    <p>실제 소요 {result['timing']['total_seconds']:.1f}초 · API 호출 {result['api_stats']['requests']} · 캐시 {result['api_stats']['cache_hits']}</p>
    <p>등록된 자료의 검색 결과를 사용합니다. 원문 인용·코드 보존 검사는 답변 의미의 정확성을 보증하지 않습니다.</p></html>'''
    content=content.replace('</style>','</style><style>'+asset('markdown.css')+'</style>',1)
    content=content.replace('</html>','<script>'+asset('markdown.js')+'</script></html>')
    (out/'최소RAG_답변.html').write_text(content,encoding='utf-8')
