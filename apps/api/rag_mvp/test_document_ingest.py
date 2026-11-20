"""Offline OOXML -> code chunks -> course registration -> real LlamaIndex tests."""
import copy
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
from unittest.mock import patch
from .document_ingest import prepare_documents, extract, chunks_for_document, A,P,W,R
from .code_regions import regions, validate_code_chunk
from .markdown_tools import split_chunk, code_blocks
from .corpus import load_corpus
from .retrieval import build_index, vector_search
from .pipeline import check_answer
from video_extraction.shared.common import read, signature
from quiz_mvp.materials import install_material, active_material
from quiz_mvp.store import Store
from quiz_mvp.courses import DEFAULT_OFFERING as OID

CODE='def double(value):\n\t# 한글 주석과 공백  \n\treturn value * 2\n\nprint(double(3))'


def ppt(path, text=CODE, image=False):
    # Split a line across XML runs to exercise literal joining; split line via a:br.
    body=''.join('<a:p><a:r><a:rPr><a:latin typeface="Consolas"/></a:rPr><a:t xml:space="preserve">'+escape(line[:3])+'</a:t></a:r><a:r><a:t xml:space="preserve">'+escape(line[3:])+'</a:t></a:r></a:p>' for line in text.split('\n'))
    shape='<p:sp><p:nvSpPr><p:cNvPr id="2" name="Code"/></p:nvSpPr><p:txBody>'+body+'</p:txBody></p:sp>'
    image_xml='<p:pic><p:nvPicPr><p:cNvPr id="3" name="Image"/></p:nvPicPr></p:pic>' if image else ''
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst><p:sldId id="256" r:id="r2"/></p:sldIdLst></p:presentation>')
        z.writestr('ppt/_rels/presentation.xml.rels','<Relationships><Relationship Id="r2" Target="slides/custom.xml"/></Relationships>')
        z.writestr('ppt/slides/custom.xml',f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>'+shape+image_xml+'</p:spTree></p:cSld></p:sld>')


def docx(path, code=CODE, styled=True):
    def para(text,style=False):
        prop='<w:pPr><w:pStyle w:val="SourceExample"/></w:pPr>' if style else ''
        runs=''
        for i,segment in enumerate(text.split('\t')):
            if i:runs+='<w:r><w:tab/></w:r>'
            runs+='<w:r><w:t xml:space="preserve">'+escape(segment)+'</w:t></w:r>'
        return '<w:p>'+prop+runs+'</w:p>'
    body=para('함수는 값을 두 배로 만듭니다.')+''.join(para(line,styled) for line in code.split('\n'))+para('설명 끝. 코드의 공백은 그대로 둡니다.')
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('word/document.xml',f'<w:document xmlns:w="{W}"><w:body>'+body+'</w:body></w:document>')
        z.writestr('word/styles.xml',f'<w:styles xmlns:w="{W}"><w:style w:styleId="SourceExample"><w:name w:val="Python Code"/></w:style></w:styles>')


class NativeCodeTests(unittest.TestCase):
    def test_ppt_xml_runs_tabs_blank_lines_and_real_slide_order(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'new.pptx';ppt(p,image=True)
            native=extract(p);self.assertEqual(native['units'][0]['text'],CODE)
            c,h,e=chunks_for_document(native)
            self.assertEqual(len(c),1);self.assertEqual(c[0]['code_text'],CODE)
            self.assertEqual(code_blocks(c[0]['text']),[CODE+'\n'])
            self.assertEqual(c[0]['source_part'],'ppt/slides/custom.xml')
            self.assertTrue(any(x['reason']=='image_or_graphic_requires_visual_extraction' for x in h))
            validate_code_chunk(c[0])

    def test_word_paragraph_styles_and_unstyled_syntax_both_split_code(self):
        for styled in (True,False):
            with self.subTest(styled=styled),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'lecture.docx';docx(p,styled=styled)
                c,h,e=chunks_for_document(extract(p));self.assertFalse(h)
                code=[x for x in c if x['kind']=='code'];self.assertEqual(len(code),1)
                self.assertEqual(code[0]['code_text'].rstrip('\n'),CODE)
                self.assertEqual(len([x for x in c if x['kind']=='text']),2)
                for unit in e:
                    self.assertEqual(''.join(unit['original_text'][r['start']:r['end']] for r in unit['spans']),unit['original_text'])

    def test_normal_prose_not_falsely_classified(self):
        for text in ['이 함수는 값을 반환합니다.\n다음은 설명입니다.','Python is a programming language.\nA list has elements.','튜플(tuple)은 변경할 수 없습니다.']:
            self.assertTrue(all(r['kind']=='text' for r in regions(text)))

    def test_missing_indent_and_truncation_stay_held_without_repair(self):
        for text in ['def broken(x):\nreturn x','def broken(x):\n    return (x +','```python\nx=1']:
            with self.subTest(text=text),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'bad.pptx';ppt(p,text)
                c,h,e=chunks_for_document(extract(p))
                self.assertFalse(c);self.assertEqual(h[0]['source_text'],text)
                self.assertFalse(h[0]['eligible_for_chunking'])

    def test_unstyled_missing_indent_not_released_as_normal_prose(self):
        text='설명\ndef broken(x):\nreturn x\n끝 설명'
        spans=regions(text)
        bad=next(r for r in spans if r['kind']=='code')
        self.assertEqual(bad['status'],'held');self.assertIn('return x',text[bad['start']:bad['end']])

    def test_legacy_prepare_uses_native_indent_and_retains_eligibility_gate(self):
        from .corpus import prepare
        from video_extraction.shared.common import digest_file,save
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'lecture.pptx';ppt(p)
            native=root/'outputs/extraction-compare/native';native.mkdir(parents=True)
            save(native/'manifest.json',[{'source_id':'chapter6','original_path':str(p),'sha256':digest_file(p),'filename':p.name}])
            row={'id':'chapter6-s001','slide_number':1,'title':'코드','role':'lecture','assets':[],'review_flags':[],
                 'text':CODE.replace('\t','')}
            import json
            (native/'slides.jsonl').write_text(json.dumps(row)+'\n')
            with patch('rag_mvp.corpus.ROOT',root),patch('rag_mvp.corpus.SLIDES',(1,)):
                c=prepare(root/'out')
                self.assertEqual(c['chunks'][0]['code_text'],CODE)
                row['review_flags']=['unresolved']
                (native/'slides.jsonl').write_text(json.dumps(row)+'\n')
                with self.assertRaisesRegex(ValueError,'ineligible_source'):prepare(root/'blocked')

    def test_fences_independent_even_when_below_chunk_limit(self):
        text='설명\n\n```python\nx=1\n```\n\n마무리'
        parts=split_chunk({'id':'x','text':text})
        self.assertEqual(len(parts),3);self.assertEqual(''.join(c['text'] for c in parts),text)
        self.assertEqual(parts[1]['kind'],'code');validate_code_chunk(parts[1])

    def test_oversized_native_code_keeps_origin_offsets_through_registration(self):
        text='설명\n\n'+('x = 1\n'*400)
        document={'source_file':'a.docx','source_sha256':'a'*64,'issues':[],
                  'units':[{'text':text,'locator':'body:1','source_part':'word/document.xml','page':1}]}
        chunks,held,_=chunks_for_document(document)
        code=next(c for c in chunks if c['kind']=='code')
        self.assertFalse(held);self.assertEqual(code['source_char_start'],len('설명\n\n'))
        self.assertEqual(code['source_text'],text[code['source_char_start']:code['source_char_end']])
        again=split_chunk(code)[0]
        self.assertEqual(again['source_char_start'],code['source_char_start'])
        self.assertEqual(again['source_char_end'],code['source_char_end']);validate_code_chunk(again)

    def test_nested_backticks_no_wrapper_damage_and_no_execution(self):
        text='value = "```"\nraise RuntimeError("must never execute")'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.pptx';ppt(p,text)
            c,h,_=chunks_for_document(extract(p));self.assertFalse(h)
            self.assertTrue(c[0]['text'].startswith('````python'))
            self.assertEqual(code_blocks(c[0]['text']),[text+'\n'])

    def test_actual_registration_and_embedding_receives_whole_code(self):
        class Synthetic:
            embedding_model='offline-code-test';dimensions=2
            def __init__(self):self.inputs=[]
            def embed(self,text,query=False,title=''):
                if not query:self.inputs.append(text)
                return [1.,0.] if 'def double' in text else [0.,1.]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'fresh.docx';docx(source)
            out=root/'prepared';corpus=prepare_documents([source,source],out)
            self.assertEqual(corpus['signature'],load_corpus(out)['signature'])
            self.assertEqual(len(corpus['sources']),1)
            store=Store(root/'app'/'learning.sqlite3');install_material(store,root/'app',OID,corpus)
            folder,registered=active_material(store,root/'app',OID)
            client=Synthetic()
            build_index(folder,registered,client)
            code=next(c for c in registered['chunks'] if c['kind']=='code')
            self.assertIn(code['text'],client.inputs)
            self.assertEqual(sum('def double' in t for t in client.inputs),1)
            found=vector_search(folder,registered,client,'def double',1)
            self.assertEqual(found[0]['id'],code['id'])
            candidate={'answerable':True,'claims':[{'text':code['text'],'source_id':code['id'],'quote':'def double(value):'}],'reason':''}
            self.assertEqual(check_answer(candidate,[code])['status'],'citation_checked')
            candidate['claims'][0]['text']=code['text'].replace('\treturn','return')
            self.assertEqual(check_answer(candidate,[code])['status'],'held')
            tampered=copy.deepcopy(corpus);x=next(c for c in tampered['chunks'] if c['kind']=='code');x['text']=x['text'].replace('* 2','* 3')
            tampered['signature']=signature({'version':1,'chunks':tampered['chunks']})
            with self.assertRaisesRegex(ValueError,'code_source_changed'):install_material(store,root/'app',OID,tampered)
            with self.assertRaisesRegex(ValueError,'code_source_changed'):build_index(folder,tampered,client)

    def test_cli_prepare_calls_no_provider(self):
        from .__main__ import main
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fresh.pptx';ppt(p);out=Path(d)/'result'
            with patch('sys.argv',['rag_mvp','prepare','--input',str(p),'--output',str(out)]),patch('rag_mvp.__main__.Google',side_effect=AssertionError('API client forbidden')):
                main()
            self.assertEqual(read(out/'summary.json')['code_chunks'],1)
            self.assertEqual(read(out/'summary.json')['api_calls'],0)


if __name__=='__main__':unittest.main()
