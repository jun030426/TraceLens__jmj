"""Conservative native-text code detection; never execute or rewrite source code."""
import ast
import re
from .markdown_tools import parse, source_lines

POLICY = 'native-code-regions-v1'
MONO = re.compile(r'consolas|courier|monaco|menlo|source code|fira code|cascadia', re.I)
CODE_STYLE = re.compile(r'code|source|program|소스|코드', re.I)
START = re.compile(r'^(?:async\s+def\s|def\s|class\s|from\s+\w+\s+import\s|import\s|(?:for|while|if|with|try)\b.*:|[\w.\[\], ]+\s*(?::[^=]+)?=(?!=)|[A-Za-z_][A-Za-z_0-9.]*\s*\(|@\w|#\s*include|(?:const|let|var|function|public|private|void)\s)')


def python_code(text):
    try: tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError): return False
    return any(isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Import, ast.ImportFrom,
        ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.For, ast.While, ast.If, ast.With,
        ast.Try, ast.Call)) for n in ast.walk(tree))


def fenced(text, language=''):
    # A longer delimiter safely contains triple-backticks inside a string.
    marker = '`' * max(3, 1 + max((len(x) for x in re.findall(r'`+', text)), default=0))
    return marker + language + '\n' + text + ('' if text.endswith('\n') else '\n') + marker + '\n'


def regions(text, explicit=False):
    """Exact, exhaustive source slices. Uncertain code remains held, never prose."""
    lines = source_lines(text); offsets = [0]
    for line in lines: offsets.append(offsets[-1] + len(line))
    try: tokens = parse(text)
    except ValueError:
        return [dict(start=0,end=len(text),kind='code',status='held',reason='unclosed_code_fence',language='')]
    fences = {t.map[0]:t for t in tokens if t.type=='fence' and t.level==0}
    if explicit and not fences:
        language = 'python' if python_code(text) else ''
        return [dict(start=0,end=len(text),kind='code',language=language,status='ready' if language else 'held',
                     reason='' if language else 'code_language_or_syntax_requires_review')]
    result=[];i=0
    def add(a,b,kind,**extra):
        if b>a:result.append(dict(start=offsets[a],end=offsets[b],kind=kind,**extra))
    while i < len(lines):
        if i in fences:
            token=fences[i];language=token.info.split()[0] if token.info.strip() else ''
            reason=''
            if language.lower() in ('py','python','python3') and not python_code(token.content):reason='python_syntax_requires_review'
            add(i,token.map[1],'code',language=language,status='held' if reason else 'ready',reason=reason,
                already_fenced=True,code_text=token.content)
            i=token.map[1];continue
        stripped=lines[i].lstrip(' \t').rstrip('\r\n')
        if not START.match(stripped):add(i,i+1,'text',status='ready');i+=1;continue
        # Find the first prose boundary; retain blank lines, comments and indented continuations.
        end=i+1
        while end<len(lines) and end not in fences:
            value=lines[end].strip()
            if not value or lines[end].startswith((' ','\t')) or START.match(value) or value.startswith(('#',')',']','}','else:', 'elif ', 'except', 'finally:', 'return ', 'raise ', 'yield ', 'pass', 'break', 'continue')):
                end+=1
            else:break
        raw=text[offsets[i]:offsets[end]]
        ok=python_code(raw)
        add(i,end,'code',language='python' if ok else '',status='ready' if ok else 'held',
            reason='' if ok else 'code_boundary_or_syntax_requires_review')
        i=end
    # Merge adjacent prose, never merge code with prose or another independent block.
    merged=[]
    for item in result:
        if merged and item['kind']=='text' and merged[-1]['kind']=='text':merged[-1]['end']=item['end']
        else:merged.append(item)
    assert ''.join(text[x['start']:x['end']] for x in merged)==text
    return merged


def validate_code_chunk(chunk):
    """Validate prepared representation before registration/embedding, not just parsing."""
    if chunk.get('eligible_for_chunking') is False or chunk.get('status')=='held':
        raise ValueError('held_chunk_cannot_be_embedded')
    if chunk.get('code_format')!='fenced':return
    from .markdown_tools import code_blocks
    code=chunk.get('code_text')
    if not isinstance(code,str):raise ValueError('code_source_missing')
    expected=code.replace('\r\n','\n').replace('\r','\n')
    if not expected.endswith('\n'):expected+='\n'
    if code_blocks(chunk['text'])!=[expected]:raise ValueError('code_source_changed')
    if chunk.get('source_already_fenced'):
        if chunk.get('source_text')!=chunk['text']:raise ValueError('code_source_changed')
    elif chunk.get('source_text')!=code:raise ValueError('code_source_changed')
