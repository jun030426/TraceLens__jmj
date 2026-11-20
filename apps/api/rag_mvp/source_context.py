"""Search and cite exact linked comments without rewriting the code block."""


def linked_comments(source):
    if source.get('quality')!='source_code_structure_checked':return []
    return source.get('comment_context',[])


def search_text(source):
    comments=linked_comments(source)
    if not comments:return source['text']
    return source['text']+'\n\n[연결된 원본 주석 — 실행 코드가 아님]\n'+'\n\n'.join(c['text'] for c in comments)


def citation_texts(source):
    # Separate spans: do not permit a quote fabricated across two comment blocks.
    return [source['text']]+[c['text'] for c in linked_comments(source)]
