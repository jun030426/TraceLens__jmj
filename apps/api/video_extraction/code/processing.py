"""Source-bound structural chunks. Never import/execute submitted source files."""
import ast
import bisect
import hashlib
import io
import json
import re
import tokenize
import sys
from pathlib import Path

VERSION='source-code-v2'
MAX_CHUNK=16000


def python_structure(text):
    tree=ast.parse(text)  # Positions only; ast.unparse/untokenize would alter evidence.
    comments=list(tokenize.generate_tokens(io.StringIO(text.replace('\r\n','\n').replace('\r','\n')).readline))
    lines=[line for line in re.findall(r'[^\r\n]*(?:\r\n|\r|\n|$)',text) if line];offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    def pos(line,col):return offsets[line-1]+len(lines[line-1].encode('utf-8')[:col].decode('utf-8'))
    def span(n):
        start=pos(n.lineno,n.col_offset)
        decorators=getattr(n,'decorator_list',[])
        if decorators:start=offsets[min(d.lineno for d in decorators)-1]
        # Preserve method indentation and trailing inline comments.
        line=bisect.bisect_right(offsets,start)-1
        if not text[offsets[line]:start].strip():start=offsets[line]
        end=pos(n.end_lineno,n.end_col_offset)
        tail=text[end:offsets[n.end_lineno]]
        if not tail.strip() or tail.lstrip().startswith('#'):end=offsets[n.end_lineno]
        return start,end
    atomic=[];structures=[];imports=[]
    def visit(nodes,parent=None):
        example=None
        for n in nodes:
            a,b=span(n);name=getattr(n,'name',type(n).__name__)
            ident=(parent+'.' if parent else '')+name+'@'+str(n.lineno)
            if isinstance(n,ast.ClassDef):
                example=None
                structures.append(dict(id=ident,name=n.name,kind='class',start=a,end=b,parent_id=parent))
                methods=[x for x in n.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
                if methods:visit(methods,ident)
                else:atomic.append(dict(start=a,end=b,kind='class',name=n.name,parent_id=parent))
            elif isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                example=None
                atomic.append(dict(start=a,end=b,kind='method' if parent else 'function',name=n.name,parent_id=parent))
            elif isinstance(n,(ast.Import,ast.ImportFrom)):
                example=None;imports.append(dict(start=a,end=b,text=text[a:b]))
            elif parent is None:
                # Consecutive executable statements are one ordered example. Never
                # merge across a function/class/import boundary or reorder source.
                if example is None:
                    example=dict(start=a,end=b,kind='module_example',name='example@'+str(n.lineno),parent_id=None,statement_count=1)
                    atomic.append(example)
                else:example.update(end=b,statement_count=example['statement_count']+1)
    visit(tree.body)
    candidates=[]
    for typ,tag in [(ast.For,'iteration'),(ast.While,'iteration'),(ast.If,'condition'),(ast.List,'list'),(ast.Dict,'dictionary'),(ast.ClassDef,'class')]:
        if any(isinstance(n,typ) for n in ast.walk(tree)):candidates.append({'id':'programming.'+tag,'status':'candidate','basis':'syntax:'+typ.__name__})
    return atomic,structures,imports,candidates,[(offsets[t.start[0]-1]+t.start[1],offsets[t.end[0]-1]+t.end[1]) for t in comments if t.type==tokenize.COMMENT]


def java_structure(text):
    from tree_sitter import Language,Parser
    import tree_sitter_java
    data=text.encode('utf-8');tree=Parser(Language(tree_sitter_java.language())).parse(data)
    if tree.root_node.has_error:raise ValueError('java_syntax_error_or_missing_token')
    def char(b):return len(data[:b].decode('utf-8'))
    atomic=[];structures=[];imports=[];comments=[];candidates=[]
    classes={'class_declaration','interface_declaration','enum_declaration','record_declaration','annotation_type_declaration'}
    methods={'method_declaration','constructor_declaration','compact_constructor_declaration'}
    def visit(n,parent=None):
        a,b=char(n.start_byte),char(n.end_byte)
        name_node=n.child_by_field_name('name');name=name_node.text.decode() if name_node else n.type
        if n.type in ('line_comment','block_comment'):comments.append((a,b));return
        if n.type in ('import_declaration','package_declaration'):imports.append(dict(start=a,end=b,text=text[a:b]));return
        if n.type in classes:
            ident=(parent+'.' if parent else '')+name+'@'+str(n.start_point.row+1)
            structures.append(dict(id=ident,name=name,kind=n.type,start=a,end=b,parent_id=parent));parent=ident
            candidates.append({'id':'programming.class','status':'candidate','basis':'syntax:'+n.type})
        if n.type in methods or n.type=='static_initializer' or (n.type=='block' and n.parent and n.parent.type=='class_body'):
            # Body, annotations and nested/local functions/classes stay intact.
            atomic.append(dict(start=a,end=b,kind='constructor' if 'constructor' in n.type else 'method',name=name,parent_id=parent));return
        if n.type=='field_declaration':return  # Includes anonymous/lambda initializers in class context.
        for child in n.named_children:visit(child,parent)
    visit(tree.root_node)
    # Classes without methods remain whole, including enum constants/record fields.
    for c in sorted(structures,key=lambda c:c['end']-c['start']):
        if not any(c['start']<=x['start']<c['end'] for x in atomic):
            atomic.append({**c,'kind':'class'})
    return atomic,structures,imports,candidates,comments


def link_comments(text,parts,structures,comments):
    """Exact source snippets, with structural or explicit-reference associations.

    File-level fallback is labelled as shared context, never as a function's
    inferred documentation. Comments inside held code cannot enter through links.
    """
    available=[(a,b) for a,b in comments if not any(p['kind']!='context' and p['start']<=a and b<=p['end'] for p in parts)]
    def indentation(at):
        line=max(text.rfind('\n',0,at),text.rfind('\r',0,at))+1
        return len(text[line:at].expandtabs(8))
    groups=[]
    for a,b in sorted(available):
        if groups and not text[groups[-1][1]:a].strip() and indentation(groups[-1][0])==indentation(a):groups[-1][1]=b
        else:groups.append([a,b])
    for p in parts:p['comment_context']=[]
    def class_parts(c):return [p for p in parts if p['eligible'] and c['start']<=p['start'] and p['end']<=c['end']]
    for start,end in groups:
        line=max(text.rfind('\n',0,start),text.rfind('\r',0,start))+1
        if not text[line:start].strip():start=line
        snippet=text[start:end];targets=[];relation='file_context'
        containing=[c for c in structures if c['start']<=start and end<=c['end']]
        if containing:
            targets=class_parts(min(containing,key=lambda c:c['end']-c['start']));relation='class_scope'
        else:
            # An indented comment after a Python function still belongs to that
            # suite even though the AST's end position excludes trailing comments.
            previous=[p for p in parts if p['kind'] in ('function','method') and p['end']<=start and not text[p['end']:start].strip()]
            if previous:
                p=max(previous,key=lambda p:p['end']);header=text[p['start']:p['end']]
                definition=re.search(r'(?m)^([ \t]*)(?:async )?def\s',header)
                indent=len(snippet)-len(snippet.lstrip(' \t'))
                if definition and indent>len(definition[1]):targets=[p] if p['eligible'] else [];relation='indented_suite_comment'
            if relation=='file_context':
                # Reference means "mentions this symbol", not semantic approval.
                for p in parts:
                    if p['eligible'] and p['kind'] in ('function','method','constructor','class') and re.search(r'\b'+re.escape(p['name'])+r'\s*\(',snippet):targets.append(p)
                for c in structures:
                    if re.search(r'\b(?:class|interface|enum|record)\s+'+re.escape(c['name'])+r'\b',snippet):targets+=class_parts(c)
                if targets:relation='symbol_reference'
            if relation=='file_context':
                following=[c for c in structures if end<=c['start'] and not text[end:c['start']].strip()]
                if following:targets=class_parts(min(following,key=lambda c:c['start']));relation='preceding_class_comment'
            if relation=='file_context':
                following=[p for p in parts if p['kind']!='context' and end<=p['start'] and not text[end:p['start']].strip()]
                if following:
                    p=min(following,key=lambda p:p['start']);targets=[p] if p['eligible'] else [];relation='preceding_code_comment'
            if relation=='file_context':targets=[p for p in parts if p['eligible']]
        context={'id':f'comment:{start}:{end}','start':start,'end':end,
            'line_start':len(re.findall(r'\r\n|\r|\n',text[:start]))+1,
            'line_end':len(re.findall(r'\r\n|\r|\n',text[:end]))+1,
            'text':snippet,'relation':relation,'semantic_relation':'not_inferred'}
        for p in {p['start']:p for p in targets}.values():p['comment_context'].append(context)
    for p in parts:
        if p['eligible'] and len(p['text'])+sum(len(c['text']) for c in p['comment_context'])>MAX_CHUNK:
            p.update(eligible=False,status='held',reason='oversized_code_with_comments')

#언어·인코딩·문법 확인
def analyze(path,encoding=None):
    path=Path(path);raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    language={'.py':'python','.java':'java'}.get(path.suffix.lower())
    if language is None:raise ValueError('unsupported_code_language')
    codec=encoding or ('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8')
    if language=='python':
        try:codec=tokenize.detect_encoding(io.BytesIO(raw).readline)[0]
        except (SyntaxError,LookupError):codec='unknown'
    base={'version':VERSION,'source_sha256':sha,'language':language,'encoding':codec,'raw_bytes':len(raw),'executed':False,
          'python_grammar':list(sys.version_info[:2])}
    if language=='java':
        from importlib.metadata import version
        base['parser_versions']={n:version(n) for n in ('tree-sitter','tree-sitter-java')}
    try:text=raw.decode(codec)
    except (UnicodeError,LookupError):
        return {**base,'text':None,'status':'held','reason':'source_encoding_requires_review','parts':[], 'structures':[],'imports':[],'concept_candidates':[]}
    # Byte ranges are checked against the exact original, including BOM separately.
    encoding_body='utf-8' if codec.lower().replace('_','-')=='utf-8-sig' else codec
    prefix=len(raw)-len(text.encode(encoding_body))
    if prefix not in (0,3):raise ValueError('unsupported_encoding_roundtrip')
    try:
        atomic,structures,imports,candidates,comments=(python_structure if language=='python' else java_structure)(text)
        status='checked';reason=''
    except (SyntaxError,IndentationError,tokenize.TokenError,ValueError,RecursionError) as ex:
        atomic=[];structures=[];imports=[];candidates=[];comments=[]
        status='held';reason='source_syntax_requires_review'
    atomic.sort(key=lambda x:x['start'])
    def line_start(at):return max(text.rfind('\n',0,at),text.rfind('\r',0,at))+1
    # Keep a closing-line comment with its Java method, not with the next method.
    if language=='java':
        for n in atomic:
            for ca,cb in sorted(comments):
                gap=text[n['end']:ca]
                if ca>=n['end'] and not gap.strip() and '\n' not in gap and '\r' not in gap:
                    n['end']=cb
    # Attach contiguous preceding comments; no regex-only brace or function splitting.
    previous=0
    for n in atomic:
        a=n['start'];line=line_start(a)
        header=text[a:n['end']].splitlines()[0]
        code_indent=len(header)-len(header.lstrip(' \t'))
        if not text[line:a].strip():a=line
        while True:
            matches=[(ca,cb) for ca,cb in comments if ca>=previous and cb<=a and not text[cb:a].strip() and len(re.findall(r'\r\n|\r|\n',text[cb:a]))<=2
                     and (language!='python' or ca-line_start(ca)<=code_indent)]
            if not matches:break
            ca,cb=max(matches,key=lambda c:c[1]);a=ca
            line=line_start(a)
            if not text[line:a].strip():a=line
        n['start']=a
        if a<previous:raise ValueError('overlapping_code_partition')
        previous=n['end']
    parts=[];cursor=0
    #코드 조각 생성, 원문 대조
    def add(a,b,info=None):
        if a==b:return
        snippet=text[a:b];n=info or {'kind':'context','name':'file_context','parent_id':None}
        selected=info is not None and status=='checked' and len(snippet)<=MAX_CHUNK
        why=reason or ('oversized_atomic_code' if info and len(snippet)>MAX_CHUNK else '')
        parts.append({**n,'start':a,'end':b,'byte_start':prefix+len(text[:a].encode(encoding_body)),
            'byte_end':prefix+len(text[:b].encode(encoding_body)), 'text':snippet,
            'line_start':len(re.findall(r'\r\n|\r|\n',text[:a]))+1,'line_end':len(re.findall(r'\r\n|\r|\n',text[:max(a,b-1)]))+1,
            'eligible':selected,'status':'held' if why else 'checked' if selected else 'context_only','reason':why})
    for n in atomic:add(cursor,n['start']);add(n['start'],n['end'],n);cursor=n['end']
    add(cursor,len(text))
    if not parts:reason='empty_source';status='held'
    if ''.join(x['text'] for x in parts)!=text:raise ValueError('code_partition_coverage_failed')
    for part in parts:
        if raw[part['byte_start']:part['byte_end']].decode(encoding_body)!=part['text']:raise ValueError('code_bytes_changed')
    # Class context is the exact class shell (fields/docstring/header), excluding method bodies.
    #클래스 정보와 검사 결과 반환
    for c in structures:
        spans=[];at=c['start']
        for n in atomic:
            if n['start']>=c['start'] and n['end']<=c['end']:
                if n['start']>at:spans.append([at,n['start']])
                at=n['end']
        if at<c['end']:spans.append([at,c['end']])
        c['context_spans']=spans
    link_comments(text,parts,structures,comments)
    return {**base,'text':text,'bom_bytes':prefix,'status':status,'reason':reason,'parts':parts,
        'structures':structures,'imports':imports,'concept_candidates':candidates,
        'checks':{'source_partition_exact':True,'code_not_executed':True,'logical_correctness_proven':False}}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--encoding');a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(analyze(a.input,a.encoding),ensure_ascii=False,indent=2))
