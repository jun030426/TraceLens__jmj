"""Common launcher → source gate → existing course registration/index, without APIs."""
import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_extraction._layout import PROJECT_ROOT
from video_extraction.shared.common import read,signature
from quiz_mvp.store import Store
from quiz_mvp.materials import install_material,active_material
from rag_mvp.providers import retrieved_excerpt
from rag_mvp.retrieval import build_index,vector_search,keyword_search
from rag_mvp.source_context import search_text
from rag_mvp.pipeline import check_answer


class CommonCodeRagTests(unittest.TestCase):
    def test_launcher_to_registration_and_complete_code_index(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'new.py';out=root/'common'
            source.write_text('import math\n# 주석전용검색어: 제곱 계산 예제\nclass Box:\n    """설명"""\n    def square(self, x):\n        # 원문 주석\n        return x * x\n')
            launcher=PROJECT_ROOT/'공통데이터_처리.command'
            env={k:v for k,v in os.environ.items() if k not in ('GEMINI_API_KEY','GOOGLE_API_KEY','OPENAI_API_KEY')}
            for args in [('prepare','--input',str(source),'--output',str(out)),
                         ('run','--output',str(out),'--local-only','--max-api-calls','0')]:
                p=subprocess.run(['zsh',str(launcher),*args],cwd=PROJECT_ROOT,env=env,
                    stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=90)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            corpus=read(read(out/'latest.json')['code_corpus'])
            store=Store(root/'test.sqlite3');oid=store.create_course('TEST','코드 테스트','TEST','01')['id']
            install_material(store,root/'rag',oid,corpus)
            folder,registered=active_material(store,root/'rag',oid)
            self.assertEqual(len(registered['chunks']),1)
            c=registered['chunks'][0];self.assertIn('        return x * x',c['code_text'])
            payload=retrieved_excerpt(c)
            self.assertEqual(payload['text'],c['text'])
            self.assertIn('import math',str(payload['source_context']))
            self.assertIn('주석전용검색어',str(payload['source_context']['comments']))
            self.assertEqual(keyword_search(registered['chunks'],'주석전용검색어')[0]['id'],c['id'])
            answer={'answerable':True,'claims':[{'source_id':c['id'],'quote':'제곱 계산 예제','text':'제곱 계산 예제입니다.'}],'reason':''}
            checked=check_answer(answer,[c]);self.assertEqual(checked['status'],'citation_checked')
            self.assertIn('주석 줄 2',checked['claims'][0]['source_locator'])
            answer['claims'][0]['quote']='없는 원문 주석'
            self.assertEqual(check_answer(answer,[c])['status'],'held')
            class LocalVectors:
                embedding_model='synthetic-test-only';dimensions=2
                def __init__(self):self.inputs=[]
                def embed(self,text,query=False,title=''):
                    self.inputs.append(text);return [1.0,0.0]
            client=LocalVectors();build_index(folder,registered,client)
            self.assertEqual(client.inputs,[search_text(c)])
            self.assertIn('주석전용검색어',client.inputs[0])
            self.assertEqual(vector_search(folder,registered,client,'square')[0]['id'],c['id'])
            forged=copy.deepcopy(corpus);forged['chunks'][0]['text']+='changed'
            forged['signature']=signature({'version':1,'chunks':forged['chunks']})
            with self.assertRaisesRegex(ValueError,'differs_from_common_selection'):
                install_material(store,root/'rag',oid,forged)
            forged=copy.deepcopy(corpus);forged['chunks'][0]['comment_context'][0]['text']='fabricated'
            forged['signature']=signature({'version':1,'chunks':forged['chunks']})
            with self.assertRaisesRegex(ValueError,'differs_from_common_selection'):
                install_material(store,root/'rag',oid,forged)


if __name__=='__main__':unittest.main()
