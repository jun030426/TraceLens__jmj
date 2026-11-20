"""Lossless source slices, complete-code checks and safe Markdown presentation.

Parsing/rendering never replaces stored source text. Character offsets refer to
the original string (including CRLF, tabs and blank lines), not rendered HTML.
"""
import copy
import bisect
import html
import re
from pathlib import Path
from markdown_it import MarkdownIt


def parser():
    # No raw HTML, images, typographic substitutions or automatic linkification.
    return MarkdownIt('js-default', {'html':False,'linkify':False,'typographer':False}).disable('image')


def parse(text):
    if not isinstance(text,str):raise ValueError('markdown_text_required')
    tokens=parser().parse(text)
    lines=source_lines(text)
    for token in tokens:
        if token.type!='fence':continue
        start,end=token.map
        closing=lines[end-1].rstrip('\r\n') if end>start+1 else ''
        # Container indentation/blockquote markers are syntax, not code indent.
        pattern=r'^[ \t]*(?:>[ \t]*)*'+re.escape(token.markup[0])+'{'+str(len(token.markup))+r',}[ \t]*$'
        if not re.fullmatch(pattern,closing):raise ValueError('unclosed_code_fence')
    return tokens


def code_blocks(text):
    return [t.content for t in parse(text) if t.type in ('fence','code_block')]


def source_lines(text):
    return [line for line in re.findall(r'[^\r\n]*(?:\r\n|\r|\n|$)',text) if line]


def slices(text,limit=1800,independent_code=False):
    """Split only between top-level Markdown blocks; soft limit, no truncation."""
    if limit<1:raise ValueError('positive_chunk_limit_required')
    tokens=parse(text);lines=source_lines(text);offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    # Reference definitions may live outside the block using them. Keep together.
    env={};parser().parse(text,env)
    ends=sorted({offsets[t.map[1]] for t in tokens if t.map and t.level==0})
    if env.get('references'):ends=[len(text)]
    if not ends or ends[-1]!=len(text):ends.append(len(text))
    forced=set()
    if independent_code:
        for t in tokens:
            if t.map and t.level==0 and t.type in ('fence','code_block'):
                forced.update((offsets[t.map[0]],offsets[t.map[1]]))
        ends=sorted(set(ends)|forced)
    pieces=[];start=0;end=0
    for boundary in ends:
        if boundary==start:continue
        if boundary-start>limit and end>start:
            pieces.append((start,end));start=end
        end=boundary
        if boundary in forced and end>start:
            pieces.append((start,end));start=end
    if end>start:pieces.append((start,end))
    if len(pieces)>1 and not text[pieces[-1][0]:pieces[-1][1]].strip():
        pieces[-2:]=[(pieces[-2][0],pieces[-1][1])]
    result=[{'text':text[a:b],'source_char_start':a,'source_char_end':b,
             'source_line_start':bisect.bisect_right(offsets,a),'oversized_block':b-a>limit}
            for a,b in pieces]
    if ''.join(p['text'] for p in result)!=text:raise ValueError('chunk_source_coverage_changed')
    for part in result:parse(part['text'])
    return result


def split_chunk(chunk,limit=1800):
    # Bare code is indivisible. Markdown wrappers are presentation only.
    if chunk.get('kind')=='code':
        parts=[{'text':chunk['text'],'source_char_start':0,'source_char_end':len(chunk['text']),
                'source_line_start':1,'oversized_block':len(chunk['text'])>limit}]
    else:parts=slices(chunk['text'],limit,independent_code=True)
    if len(parts)<=1:
        item=copy.deepcopy(chunk)
        if parts and parts[0]['oversized_block']:
            item['oversized_block']=True
            # Native ranges point into pre-fence source text, not the wrapper.
            for key,value in parts[0].items():item.setdefault(key,value)
        result=[item]
    else:result=[{**copy.deepcopy(chunk),**part,'id':chunk['id']+':part-'+str(i),
             'parent_chunk_id':chunk['id'],'chunking_policy':'markdown_blocks_lossless_v1'}
            for i,part in enumerate(parts,1)]
    for item in result:
        if item.get('kind')=='code':continue
        tokens=parse(item['text'])
        if len(tokens)==1 and tokens[0].type=='fence':
            token=tokens[0]
            item.update(kind='code',code_format='fenced',code_text=token.content,
                        source_text=item['text'],source_already_fenced=True,
                        language=token.info.split()[0] if token.info.strip() else '')
    return result


def memory_excerpt(text,limit):
    """Omit a whole oversized block from model memory, never cut its contents."""
    if len(text)<=limit:return text
    try:parts=slices(text,limit)
    except ValueError:return '[완전한 코드 블록을 확인할 수 없어 대화 요약에서 제외했습니다.]'
    kept=''
    for part in parts:
        if len(kept)+len(part['text'])>limit:break
        kept+=part['text']
    return kept+'\n[이후 내용은 길이 제한으로 대화 기억에서 제외했습니다. 원문은 저장돼 있습니다.]'


def supported_code(answer,source):
    """Complete retrieved code only: indentation, blank lines and operators matter."""
    codes=code_blocks(answer)
    if not codes:return True
    if source.get('code_format')=='fenced':
        originals=code_blocks(source['text'])
    elif source.get('kind')=='code':
        original=source['text'].replace('\r\n','\n').replace('\r','\n')
        originals=[original if original.endswith('\n') else original+'\n']
    else:originals=code_blocks(source['text'])
    return all(code in originals for code in codes)


def render(text,kind=None):
    if kind=='code':return code_html(text,'')
    md=parser()
    try:parse(text)
    except ValueError:
        return '<p class="markdown-warning">닫히지 않은 코드 블록이 있어 원문 그대로 표시합니다.</p><pre class="source-literal">'+html.escape(text)+'</pre>'
    def fenced(tokens,index,options,env):
        token=tokens[index];language=token.info.split()[0] if token.info.strip() else ''
        return code_html(token.content,language)
    md.renderer.rules['fence']=fenced
    md.renderer.rules['code_block']=lambda ts,i,o,e:code_html(ts[i].content,'')
    return md.render(text)


def code_html(code,language):
    language=language if re.fullmatch(r'[\w.+#-]{1,32}',language) else ''
    return ('<div class="code-block"><div class="code-toolbar"><span>'+html.escape(language or 'code')+
            '</span><button type="button" data-copy-code="true">코드 복사</button></div>'+
            '<pre tabindex="0" aria-label="코드"><code>'+html.escape(code)+'</code></pre></div>\n')


def present_turn(turn):
    """Re-render stored answers, including older rows; never trust stored HTML."""
    turn=copy.deepcopy(turn)
    for claim in (turn.get('result') or {}).get('claims',[]):
        claim['markdown_html']=render(claim['text'])
    return turn


def asset(name):
    if name not in ('markdown.css','markdown.js'):raise ValueError('unknown_markdown_asset')
    return Path(__file__).with_name(name).read_text(encoding='utf-8')
