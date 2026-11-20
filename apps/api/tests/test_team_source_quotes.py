from types import SimpleNamespace

import pytest
from lerny import team_engine


def test_abbreviated_citation_restores_exact_intervening_source():
    text = "합계를 0으로 초기화한다. 각 원소를 한 번씩 더한다. 초기값 0은 덧셈 결과에 영향을 주지 않는다."
    quote = "합계를 0으로 초기화한다. ... 초기값 0은 덧셈 결과에 영향을 주지 않는다."
    assert team_engine.verbatim_source_quote(quote, text) == text
    assert team_engine.verbatim_source_quote("각 원소를 한 번씩 더한다.", text) in text


def test_flattened_ocr_line_breaks_restore_exact_original_without_editing_tokens():
    source='STACK\nLIFO: Last In, First Out\npush: add to top\npop: remove from top'
    assert team_engine.verbatim_source_quote(source.replace('\n',' '),source)==source
    assert team_engine.verbatim_source_quote('LIFO: Last In, First Out',source)=='LIFO: Last In, First Out'
    assert team_engine.verbatim_source_quote('pop: add to top',source) is None
    assert team_engine.verbatim_source_quote('값은 10 입니다','값은 1\n입니다') is None
    assert team_engine.verbatim_source_quote('Stack LIFO',source) is None
    assert team_engine.verbatim_source_quote('same fact','same\nfact and same\nfact') is None


def test_narration_receives_all_authorized_retrieved_excerpts(tmp_path):
    from rag_mvp.unified_rag import UnifiedMultimodalRAG
    corpus={'chunks':[{'id':'label','course_id':'course','text':'LIFO','title':'LIFO'},
                      {'id':'explanation','course_id':'course','text':'LIFO is the stack rule.','title':'LIFO'}]}
    received=[]
    class Client:
        def generate_shorts_script(self,topic,hits,seconds):
            received.extend(hits);return {'target_seconds':seconds}
    engine=UnifiedMultimodalRAG(tmp_path,client=Client(),course_id='course',corpus=corpus,
                               retriever=lambda query,selected,limit:selected[:limit])
    engine.generate_shorts_script('LIFO',target_seconds=50,top_k=2)
    assert {row['id'] for row in received}=={'label','explanation'}


@pytest.mark.parametrize("quote,text", [
    ("first fact ... invented fact", "first fact, then actual fact"),
    ("later fact ... first fact", "first fact, then later fact"),
    ("first fact ... later fact", "first fact, first fact, later fact"),
    ("first fact ... later fact", "first fact" + "x" * 4000 + "later fact"),
])
def test_ambiguous_or_unverified_citation_remains_rejected(quote,text):
    assert team_engine.verbatim_source_quote(quote,text) is None


def test_question_adapter_saves_verbatim_expansion(monkeypatch):
    content="first source fact. intermediate context. last source fact."
    source=SimpleNamespace(id="chunk",content=content)
    class Engine:
        def generate_quiz(self, topic, difficulty, top_k=3):
            return {"source_id":"chunk","quote":"first source fact. ... last source fact.",
                "question":"Which source fact is correct for "+difficulty+"?",
                "options":["first","second","third","fourth"],"correct_index":0,"explanation":"first source fact."}
    monkeypatch.setattr(team_engine,"make_engine",lambda *args,**kwargs:Engine())
    sources={"S1":(source,"first source fact."),"S2":(source,"last source fact.")}
    def essay(*args):
        return {"kind":"essay","prompt":"Explain both source facts.","options":[],"answer_index":0,
                "explanation":"Both source facts.","criteria":["S1","S2"],"sources":[{"chunk_id":"S1"}]}
    result=team_engine.generate_questions([(source,None,None)],"course",SimpleNamespace(name="facts",description="facts"),sources,[],essay)
    assert len(result.questions)==3
    assert sources['T1'][1]==sources['T2'][1]==content


@pytest.mark.parametrize('repaired', [True, False])
def test_essay_retries_invalid_source_ids_once_without_relaxing_validation(monkeypatch, repaired):
    source=SimpleNamespace(id='chunk',content='First fact. Second fact.')
    class Engine:
        def generate_quiz(self, topic, difficulty, top_k=3):
            return {'source_id':'chunk','quote':source.content,
                    'question':'Which fact is correct for '+difficulty+'?',
                    'options':['one','two','three','four'],'correct_index':0,'explanation':'First fact.'}
    monkeypatch.setattr(team_engine,'make_engine',lambda *args,**kwargs:Engine())
    sources={'S1':(source,'First fact.'),'S2':(source,'Second fact.')}
    calls=[]
    def generate(prompt,schema):
        calls.append(prompt)
        assert schema['properties']['criteria']['items']['enum']==['S1','S2','T1']
        assert schema['$defs']['Source']['properties']['chunk_id']['enum']==list(sources)
        valid=repaired and len(calls)==2
        return {'kind':'essay','prompt':'Explain both facts.','options':[],'answer_index':0,
                'explanation':'First and second facts.','criteria':['S1','S2'] if valid else ['S1','invented'],
                'sources':[{'chunk_id':'S1'}]}
    args=([(source,None,None)],'course',SimpleNamespace(name='facts',description='facts'),sources,[],generate)
    if repaired:
        result=team_engine.generate_questions(*args)
        assert result.questions[-1].criteria==['S1','S2']
    else:
        with pytest.raises(ValueError,match='INVALID_CRITERIA'):
            team_engine.generate_questions(*args)
    assert len(calls)==2 and 'previous' in calls[1]


def test_same_criterion_text_under_distinct_ids_is_rejected(monkeypatch):
    source=SimpleNamespace(id='chunk',content='push: add to top')
    engine=SimpleNamespace(generate_quiz=lambda topic,difficulty,top_k:{'source_id':'chunk','quote':source.content,
        'question':'Question '+difficulty,'options':['one','two','three','four'],'correct_index':0,'explanation':source.content})
    monkeypatch.setattr(team_engine,'make_engine',lambda *a,**k:engine)
    sources={'S1':(source,source.content),'S2':(source,'push:  add to top')}
    calls=[]
    def generate(prompt,schema):
        calls.append(prompt)
        assert schema['properties']['criteria']['items']['enum']==['S1']
        return {'kind':'essay','prompt':'Explain push','options':[],'answer_index':0,
                'explanation':source.content,'criteria':['S1','S2'],'sources':[{'chunk_id':'S1'}]}
    with pytest.raises(ValueError,match='INVALID_CRITERIA'):
        team_engine.generate_questions([(source,None,None)],'course',SimpleNamespace(name='push',description='push'),sources,[],generate)
    assert len(calls)==2
