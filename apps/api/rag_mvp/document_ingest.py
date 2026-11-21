"""Offline PPTX/DOCX native text -> isolated code/prose -> signed RAG corpus.

XML text fidelity is checked here, not visual/factual correctness. Pictures,
ambiguous code, hidden/revision content and unsupported structures stay in review.
No inferred indentation, OCR, model calls, code execution or in-place source edits.
"""
import argparse
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from .code_regions import regions, fenced, MONO, CODE_STYLE, POLICY
from .markdown_tools import split_chunk, code_blocks
from video_extraction.shared.common import digest_file, signature, save, read

A='http://schemas.openxmlformats.org/drawingml/2006/main'
P='http://schemas.openxmlformats.org/presentationml/2006/main'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS={'a':A,'p':P,'w':W,'r':R}


def text_of(paragraph,namespace):
    out=[]
    for n in paragraph.iter():
        if n.tag=='{'+namespace+'}t':out.append(n.text or '')
        elif n.tag=='{'+namespace+'}tab':out.append('\t')
        elif n.tag in ('{'+namespace+'}br','{'+namespace+'}cr'):out.append('\n')
    return ''.join(out)


def ppt_units(package, *, validate_tables=False):
    rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(package.read('ppt/_rels/presentation.xml.rels'))
          if r.get('TargetMode')!='External'}
    root=ET.fromstring(package.read('ppt/presentation.xml'))
    units=[];issues=[]
    slides = root.findall('p:sldIdLst/p:sldId',NS)
    if not 0 < len(slides) <= 300:
        raise ValueError('SLIDE_LIMIT')
    for page,sid in enumerate(slides,1):
        target=rels[sid.attrib['{'+R+'}id']]
        part=posixpath.normpath(posixpath.join('ppt',target)) if not target.startswith('/') else target[1:]
        slide=ET.fromstring(package.read(part))
        parents={child:parent for parent in slide.iter() for child in parent}
        for node in slide.iter():
            if node.tag not in ('{'+P+'}sp','{'+P+'}graphicFrame','{'+P+'}pic','{'+P+'}cxnSp'):continue
            nv=node.find('.//p:cNvPr',NS)
            if nv is None:continue
            locator=f'slide:{page}/shape:{nv.get("id")}'
            ancestor=parents.get(node);hidden_group=False
            while ancestor is not None:
                if ancestor.tag=='{'+P+'}grpSp':
                    group_nv=ancestor.find('p:nvGrpSpPr/p:cNvPr',NS)
                    hidden_group |= group_nv is not None and group_nv.get('hidden') in ('1','true')
                ancestor=parents.get(ancestor)
            if hidden_group or nv.get('hidden') in ('1','true') or slide.get('show') in ('0','false'):
                issues.append({'locator':locator,'reason':'hidden_source_content'});continue
            bodies=[]
            if node.find('p:txBody',NS) is not None:bodies=[(locator,node.find('p:txBody',NS))]
            table=node.find('.//a:tbl',NS)
            if table is not None and validate_tables:
                from .native_tables import table_units
                table_rows,table_issues=table_units(table,locator,part,page)
                units.extend(table_rows);issues.extend(table_issues)
                continue
            if table is not None:
                # Cell boundaries are retained; table relations need the visual pipeline.
                issues.append({'locator':locator,'reason':'table_structure_requires_existing_visual_validation'})
                for row,tr in enumerate(table.findall('a:tr',NS),1):
                    for col,cell in enumerate(tr.findall('a:tc',NS),1):
                        body=cell.find('a:txBody',NS)
                        if body is not None:bodies.append((f'{locator}/cell:{row},{col}',body))
            if not bodies:
                issues.append({'locator':locator,'reason':'image_or_graphic_requires_visual_extraction'});continue
            for loc,body in bodies:
                paragraphs=body.findall('a:p',NS)
                text='\n'.join(text_of(p,A) for p in paragraphs)
                fonts=[n.get('typeface','') for n in body.findall('.//a:latin',NS)]
                indents=[p.find('a:pPr',NS).get('marL','0') if p.find('a:pPr',NS) is not None else '0' for p in paragraphs]
                units.append({'locator':loc,'source_part':part,'page':page,'text':text,
                    'explicit_code':bool(fonts) and all(MONO.search(f) for f in fonts),
                    'layout_indent_varies':len(set(indents))>1,'held_reason':'table_cell_requires_visual_validation' if table is not None else ''})
    return units,issues


def docx_units(package):
    root=ET.fromstring(package.read('word/document.xml'));body=root.find('w:body',NS)
    styles={}
    if 'word/styles.xml' in package.namelist():
        styles={s.get('{'+W+'}styleId'):s for s in ET.fromstring(package.read('word/styles.xml')).findall('w:style',NS)}
    def style_chain(p):
        s=p.find('w:pPr/w:pStyle',NS);key=s.get('{'+W+'}val') if s is not None else None
        chain=[];seen=set()
        while key and key in styles and key not in seen:
            seen.add(key);s=styles[key];chain.append(s);base=s.find('w:basedOn',NS);key=base.get('{'+W+'}val') if base is not None else None
        return chain
    units=[];issues=[];pending=None
    for index,node in enumerate(body,1):
        locator=f'body:{index}'
        if node.tag!='{'+W+'}p':
            if node.tag!='{'+W+'}sectPr':issues.append({'locator':locator,'reason':'table_or_structure_requires_review','original_xml':ET.tostring(node,encoding='unicode')})
            pending=None;continue
        if any(n.tag in ('{'+W+'}ins','{'+W+'}del','{'+W+'}moveFrom','{'+W+'}moveTo','{'+W+'}fldChar','{'+W+'}instrText') for n in node.iter()):
            issues.append({'locator':locator,'reason':'revision_or_field_requires_review','original_xml':ET.tostring(node,encoding='unicode')});pending=None;continue
        if node.find('.//w:drawing',NS) is not None or node.find('.//w:pict',NS) is not None:
            issues.append({'locator':locator,'reason':'image_requires_visual_extraction','original_xml':ET.tostring(node,encoding='unicode')});pending=None;continue
        if any(n.tag in ('{'+W+'}sym','{'+W+'}object','{'+W+'}altChunk') for n in node.iter()):
            issues.append({'locator':locator,'reason':'embedded_content_requires_review','original_xml':ET.tostring(node,encoding='unicode')});pending=None;continue
        chain=style_chain(node)
        if any(el.find('.//w:vanish',NS) is not None for el in [node,*chain]):
            issues.append({'locator':locator,'reason':'hidden_source_content','original_xml':ET.tostring(node,encoding='unicode')});pending=None;continue
        fonts=[f.get('{'+W+'}ascii','') for element in [node,*chain] for f in element.findall('.//w:rFonts',NS)]
        names=' '.join(s.get('{'+W+'}styleId','')+' '+(s.find('w:name',NS).get('{'+W+'}val','') if s.find('w:name',NS) is not None else '') for s in chain)
        explicit=bool(CODE_STYLE.search(names) or (fonts and all(MONO.search(f) for f in fonts)))
        text=text_of(node,W)
        indent=node.find('w:pPr/w:ind',NS)
        indent_key=ET.tostring(indent,encoding='unicode') if indent is not None else ''
        # Adjacent paragraphs are one source run; detect boundaries after preserving newlines.
        # A code-style transition is an explicit block boundary, never a forced split within code.
        if pending is not None and pending['explicit_code']==explicit:
            pending['text']+='\n'+text;pending['paragraphs'].append(index)
            pending['layout_indent_varies'] |= pending['_indent']!=indent_key
        else:
            pending={'locator':locator,'source_part':'word/document.xml','page':index,'text':text,
                'paragraphs':[index],'explicit_code':explicit,'layout_indent_varies':False,'_indent':indent_key}
            units.append(pending)
    # Header/footer/notes text is not silently declared processed.
    for part in package.namelist():
        if re.fullmatch(r'word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml',part):
            issues.append({'locator':part,'reason':'auxiliary_document_part_requires_review'})
    return units,issues


def extract(path, *, validate_tables=False):
    path=Path(path).resolve()
    if path.suffix.lower() not in ('.pptx','.docx'):raise ValueError('native_ingest_requires_pptx_or_docx')
    before=digest_file(path)
    with zipfile.ZipFile(path) as package:
        units,issues=ppt_units(package,validate_tables=validate_tables) if path.suffix.lower()=='.pptx' else docx_units(package)
    if digest_file(path)!=before:raise ValueError('source_changed_during_read')
    return {'source_file':path.name,'source_path':str(path),'source_sha256':before,'units':units,'issues':issues}


def chunks_for_document(document, pages=None):
    chunks=[];held=[];evidence=[]
    sha=document['source_sha256']
    for unit in document['units']:
        if pages is not None and unit['page'] not in pages:continue
        text=unit['text'];base={'title':document['source_file']+' · '+unit['locator'],'source_file':document['source_file'],
            'source_sha256':sha,'slide_number':unit['page'],'source_locator':unit['locator'],'source_part':unit['source_part'],
            'document_type':Path(document['source_file']).suffix[1:],'quality':'native_xml_text_coverage_checked',
            'chunking_policy':POLICY,'parent_unit_id':sha[:16]+':'+unit['locator'],
            'scope':'native_text_fidelity_not_visual_or_factual_accuracy'}
        if unit.get('native_table'):
            from .native_tables import table_chunk
            chunk,proof=table_chunk(unit,base);evidence.append(proof)
            (chunks if chunk['eligible_for_chunking'] else held).append(chunk)
            continue
        spans=regions(text,unit.get('explicit_code',False))
        evidence.append({'locator':unit['locator'],'original_text':text,'spans':spans})
        for i,span in enumerate(spans,1):
            raw=text[span['start']:span['end']]
            if not raw.strip():continue
            c={**base,'id':sha[:16]+':'+unit['locator']+':'+str(i),'source_text':raw,
               'source_char_start':span['start'],'source_char_end':span['end'],'kind':span['kind']}
            reason=span.get('reason','') or unit.get('held_reason','')
            if span['kind']=='code':
                code=span.get('code_text',raw);language=span.get('language','')
                if unit.get('layout_indent_varies') and not language:reason=reason or 'layout_only_indentation_requires_review'
                c.update(text=raw if span.get('already_fenced') else fenced(code,language),code_text=code,
                    code_format='fenced',language=language,source_already_fenced=span.get('already_fenced',False))
                # Verify the Markdown wrapper didn't consume any code characters.
                expected=code.replace('\r\n','\n').replace('\r','\n')
                if not expected.endswith('\n'):expected+='\n'
                if not reason and code_blocks(c['text'])!=[expected]:reason='code_fence_roundtrip_failed'
            else:c['text']=raw
            c['eligible_for_chunking']=not bool(reason)
            if reason:held.append({**c,'status':'held','reasons':[reason]})
            else:
                parts=split_chunk(c)
                if len(parts)>1:
                    for part in parts:
                        a=part['source_char_start'];b=part['source_char_end']
                        part.update(source_text=raw[a:b],source_char_start=span['start']+a,source_char_end=span['start']+b)
                chunks.extend(parts)
    held.extend({'source_file':document['source_file'],'source_sha256':sha,'status':'held','eligible_for_chunking':False,**i}
                for i in document['issues'] if pages is None or any(i['locator'].startswith(f'slide:{page}/') for page in pages))
    return chunks,held,evidence


def prepare_documents(paths,out):
    out=Path(out);chunks=[];held=[];evidence=[];sources=[];seen=set()
    for path in paths:
        d=extract(path)
        if d['source_sha256'] in seen:continue
        seen.add(d['source_sha256']);c,h,e=chunks_for_document(d);chunks+=c;held+=h
        evidence.append({'source_sha256':d['source_sha256'],'units':e});sources.append({k:v for k,v in d.items() if k not in ('units','issues')})
    corpus={'version':1,'chunks':chunks,'sources':sources,'policy':POLICY,'api_calls':0}
    corpus['signature']=signature({'version':1,'chunks':chunks})
    if (out/'corpus.json').exists() and read(out/'corpus.json')['signature']!=corpus['signature']:
        raise ValueError('frozen_corpus_changed_use_new_output')
    save(out/'corpus.json',corpus);save(out/'native-evidence.json',evidence);save(out/'review-queue.json',held)
    save(out/'summary.json',{'sources':len(sources),'usable_chunks':len(chunks),'code_chunks':sum(c['kind']=='code' for c in chunks),
        'held':len(held),'api_calls':0,'policy':POLICY,'limit':'Native text fidelity only; image/layout/factual review remains separate.'})
    return corpus


if __name__=='__main__':
    p=argparse.ArgumentParser(description='PPTX·DOCX 코드 독립 청킹 (API 없음)')
    p.add_argument('--input',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();c=prepare_documents(args.input,args.output)
    print(f"준비 완료: {len(c['chunks'])}개 청크. 보류 내역: {args.output/'review-queue.json'} · API 0회")
