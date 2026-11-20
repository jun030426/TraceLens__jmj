"""New-source routing tests. Model replies are synthetic, not measured accuracy."""
import copy
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from video_extraction.pipeline import runner as m, adapters
from video_extraction.shared.common import read,save,signature,digest_file
from video_extraction.shared.gemini import Blocked
from video_extraction.tests.test_audio_primary_scope import scoped
from video_extraction.tests.test_vision_layers import Fixture


def wav(path,seconds=6,rate=22050,channels=2):
    with wave.open(str(path),'wb') as w:
        w.setnchannels(channels);w.setsampwidth(2);w.setframerate(rate)
        w.writeframes(b'\0\0'*int(seconds*rate)*channels)
    return path


def local_model(path):
    return {'path':str(path),'options':{'language':'ko'}}


class Local:
    def __init__(self,*a,text='반복 반복') :self.text=text
    def transcribe(self,path):
        with wave.open(str(path)) as w:d=w.getnframes()/w.getframerate()
        return {'text':self.text,'segments':[{'start':0,'end':d,'text':self.text,'words':[]}]}


class AudioClient:
    def __init__(self,t,before='반복 반복',after='반복 반복',disagree=False):
        target=m.task_audio(t,before,m.audio_proposal(before,after));self.b,self.r=scoped(target,text=after)
        if disagree:self.r['uncertain']=True
        self.stages=[]
    def call(self,stage,*args):
        self.stages.append(stage)
        if stage.endswith('blind-v1'):return copy.deepcopy(self.b)
        if stage.endswith('review-v1'):return copy.deepcopy(self.r)
        if stage.endswith('impact-v1'):
            return {'literal_text':self.b['text'],'target_scope':self.b['target_scope'],'target_spans':self.b['target_spans'],
                    'impact':'low','uncertain':False,'full_target_checked':True,'no_unique_concept_or_step':True,
                    'no_number_negation_or_condition_change':True,'core_instruction_preserved_without_target':True,
                    'context_preserves_relation':True,'reason':'synthetic redundant introduction'}
        raise AssertionError(stage)


class CommonPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def image_plan(self,name='a.png',color='white',out='out'):
        src=self.root/name;Image.new('RGB',(300,200),color).save(src)
        folder=self.root/out;return folder,m.prepare([src],folder,'fixture')
    def audio_plan(self,seconds=6):
        source=wav(self.root/'new.wav',seconds);folder=self.root/'out'
        with patch.object(m.whisper,'model_info',side_effect=local_model):
            p=m.prepare([source],folder,'fixture',self.root/'model',config={'audio_window_seconds':5})
        return folder,p
    def store(self,out,p,t,result):
        result.update(plan_signature=signature(p),unit_id=t['id'])
        if t['modality']=='visual':result['visual_result_sha256']=digest_file(result['evidence']['visual_result'])
        result['result_payload_sha256']=signature(result)
        save(out/'results'/(t['unit_key']+'.json'),result)
    def test_full_audio_coverage_mixed_rate_and_channels(self):
        out,p=self.audio_plan(11.125);ts=p['units']
        self.assertEqual([t['interval'] for t in ts],[[0,5],[5,10],[10,11.125]])
        for t in ts:
            with wave.open(t['target_clip']) as w:self.assertEqual((w.getframerate(),w.getnchannels()),(16000,1))
            m.audio.primary_context_bundle(out,t)
    def test_original_frame_dimensions_and_kind(self):
        out,p=self.image_plan();self.assertEqual(p['units'][0]['dimensions'],[300,200])
        self.assertEqual(read(out/'summary.json')['usable_records'],0)
    def test_same_content_alias_no_duplicate_processing(self):
        src=self.root/'a.png';other=self.root/'b.png';Image.new('RGB',(100,100)).save(src);other.write_bytes(src.read_bytes())
        p=m.prepare([src,other],self.root/'out','fixture');self.assertEqual(len(p['units']),1)
        self.assertEqual(p['sources'][0]['identical_source_aliases'],[str(other.resolve())])
    def test_different_sources_unique_ids(self):
        src=self.root/'a.png';other=self.root/'b.png';Image.new('RGB',(100,100)).save(src);Image.new('RGB',(100,100),'red').save(other)
        p=m.prepare([src,other],self.root/'out','fixture');self.assertEqual(len({t['id'] for t in p['units']}),2)
    def test_prepare_idempotent_and_changed_source_rejected(self):
        out,p=self.image_plan();self.assertEqual(m.prepare(p['request']['sources'],out,'fixture'),p)
        Image.new('RGB',(300,200),'red').save(p['request']['sources'][0])
        with self.assertRaises(ValueError):m.verify(out)
    def test_changed_config_rejected(self):
        out,p=self.image_plan()
        with self.assertRaises(ValueError):m.prepare(p['request']['sources'],out,'different-model')
    def test_unsupported_source_is_explicit_excluded(self):
        src=self.root/'x.xyz';src.write_text('unknown')
        out=self.root/'out';p=m.prepare([src],out,'fixture')
        s=m.publish(out,p);self.assertEqual(s['source_issues'],1);self.assertFalse(s['all_units_processed']);self.assertEqual(s['usable_records'],0)
    def test_missing_renderer_does_not_select_native_text(self):
        src=self.root/'x.pdf';src.write_bytes(b'%PDF-fake')
        with patch.object(adapters,'command',side_effect=ValueError('missing_local_tool:pdftoppm')):
            p=m.prepare([src],self.root/'out','fixture')
        self.assertEqual(len(p['source_issues']),1);self.assertEqual(p['units'],[])
    def test_local_only_never_calls_key_or_client(self):
        out,p=self.audio_plan()
        with patch.object(m.whisper,'model_info',side_effect=local_model),patch.object(m.whisper,'LocalWhisper',Local),patch.object(m,'api_key',side_effect=AssertionError('network')),patch.object(m,'Gemini',side_effect=AssertionError('network')):
            s=m.run(out,self.root/'.env',local_only=True)
        self.assertEqual(s['completed'],0);self.assertEqual(s['usable_records'],0)
    def test_repeated_speech_preserved_and_no_global_dedup(self):
        out,p=self.audio_plan();client=None
        for t in p['units']:
            client=AudioClient(t);r=m.process_audio(out,p,t,client,Local());self.store(out,p,t,r)
            self.assertEqual(r['records'][0]['observed_text'],'반복 반복')
        s=m.publish(out,p);self.assertEqual(s['usable_records'],2)
    def test_supported_correction_keeps_before_after(self):
        out,p=self.audio_plan();t=p['units'][0]
        r=m.process_audio(out,p,t,AudioClient(t,'이름','이름 점수'),Local(text='이름'))
        self.assertTrue(r['records'][0]['eligible_for_chunking']);self.assertEqual(r['changes'][0]['before'],'이름')
        self.assertEqual(r['records'][0]['original_word_time_basis'],'primary_clip_relative')
    def test_small_variant_does_not_rewrite_correct_baseline(self):
        out,p=self.audio_plan();t=p['units'][0]
        r=m.process_audio(out,p,t,AudioClient(t,'메서드','메소드'),Local(text='메서드'))
        self.assertEqual(r['changes'],[]);self.assertEqual(r['records'][0]['observed_text'],'메서드');self.assertTrue(r['records'][0]['eligible_for_chunking'])
    def test_low_impact_hold_excluded_not_corrected(self):
        out,p=self.audio_plan();t=p['units'][0]
        r=m.process_audio(out,p,t,AudioClient(t,disagree=True),Local())
        self.assertFalse(r['records'][0]['eligible_for_chunking']);self.assertEqual(r['records'][0]['impact_review']['route'],'administrator');self.assertFalse(r['changes'])
    def test_numeric_negation_repetition_scope_disagreements_block(self):
        for before,after,literal in [('1.5','15','1.5'),('된다','안 된다','된다'),('반복 반복','반복','반복 반복')]:
            t={'id':'new','target_id':'new','role':'repair','before':before,'after':after,'neighbors':[],'interval':[0,5],'target_clip_meta':{'duration_seconds':5}}
            b,r=scoped(t,literal=literal);self.assertFalse(m.audio_gate(t,b,r)['passed'])
        b,r=scoped(t);b['target_scope']['boundary_crossing']=True;self.assertFalse(m.audio_gate(t,b,r)['passed'])
    def test_stored_selection_cannot_override_failed_gate(self):
        out,p=self.audio_plan();t=p['units'][0];r=m.process_audio(out,p,t,AudioClient(t,disagree=True),Local());self.store(out,p,t,r)
        r['records'][0]['eligible_for_chunking']=True
        with self.assertRaises(ValueError):m.validate_result(out,p,t,r)
    def test_visual_correction_and_handwriting_preserved(self):
        out,p=self.image_plan();t=p['units'][0];r=m.process_visual(out,p,t,Fixture(new_annotation=True),[]);self.store(out,p,t,r)
        self.assertTrue(any(x['modality']=='handwriting' for x in r['records']))
        self.assertEqual(next(x for x in r['records'] if x['kind']=='table')['observed_text'],'딕셔너리(Dictionary)')
        self.assertGreater(m.publish(out,p)['usable_records'],0)
    def test_visual_failure_does_not_change_original(self):
        out,p=self.image_plan();t=p['units'][0];client=Fixture(decision='hold');original=client.call
        def call(stage,*args):
            if stage=='pipeline-visual-impact-v1':
                data=json.loads(args[1].split('DATA:\n')[1]);return {'record_id':data['record_id'],'impact':'unknown','same_region':True,'source_clear':False,'uncertain':True,'core_instruction_preserved_without_region':False,'no_unique_concept_or_step':False,'no_number_negation_condition_or_code_change':False,'reason':'unreadable'}
            return original(stage,*args)
        client.call=call;r=m.process_visual(out,p,t,client,[])
        self.assertEqual(r['changes'],[]);self.assertFalse(any(x['eligible_for_chunking'] for x in r['records']))
    def test_visual_low_impact_requires_all_guards(self):
        rec={'id':'r'};ir={'record_id':'r','impact':'low','same_region':True,'source_clear':True,'uncertain':False,'core_instruction_preserved_without_region':True,'no_unique_concept_or_step':True,'no_number_negation_condition_or_code_change':True,'reason':'redundant decoration'}
        self.assertTrue(m.visual_impact_gate(rec,ir))
        ir['no_number_negation_condition_or_code_change']=False;self.assertFalse(m.visual_impact_gate(rec,ir))
    def test_blank_rendered_words_block_publication_without_api(self):
        out,p=self.image_plan();t=p['units'][0]
        xml='<doc><page width="300" height="200"><word xMin="10" yMin="10" xMax="150" yMax="50">한글본문</word></page></doc>'
        health=adapters.render_health(t['image'],xml)
        self.assertEqual(health['status'],'suspected_missing_glyphs')
        t.update(render_health=health,preparation_holds=[health['status']])
        r=m.process_visual(out,p,t,None,[])
        self.assertFalse(r['records'][0]['eligible_for_chunking']);self.assertFalse(r['changes'])
    def test_unreadable_unit_does_not_block_other_sources(self):
        src=self.root/'a.png';other=self.root/'b.png'
        Image.new('RGB',(300,200)).save(src);Image.new('RGB',(300,200),'red').save(other)
        out=self.root/'out';p=m.prepare([src,other],out,'fixture');client=Fixture();real=m.process_visual
        def wrapped(out,p,t,cl,ctx):
            if t['id']==p['units'][0]['id']:raise ValueError('invalid_bbox')
            return real(out,p,t,client,ctx)
        with patch.object(m,'api_key',return_value='fixture'),patch.object(m,'Gemini',return_value=client),patch.object(m,'process_visual',side_effect=wrapped):
            s=m.run(out,self.root/'.env')
        self.assertEqual(s['completed'],1);self.assertEqual(s['pending'],1);self.assertGreater(s['usable_records'],0)
    def test_stop_resume_finalized_units_not_reprocessed(self):
        out,p=self.image_plan();client=Fixture();calls=[]
        def process(out,p,t,cl,ctx):
            calls.append(t['id'])
            if len(calls)==1:raise Blocked('total_request_budget_exhausted')
            return m.process_visual(out,p,t,client,ctx)
        real=m.process_visual
        def wrapped(out,p,t,cl,ctx):
            calls.append(t['id'])
            if len(calls)==1:raise Blocked('total_request_budget_exhausted')
            return real(out,p,t,client,ctx)
        with patch.object(m,'api_key',return_value='fixture'),patch.object(m,'Gemini',return_value=client),patch.object(m,'process_visual',side_effect=wrapped):
            with self.assertRaises(Blocked):m.run(out,self.root/'.env')
            self.assertEqual(read(out/'summary.json')['pending'],1)
            s=m.run(out,self.root/'.env');self.assertEqual(s['completed'],1)
            m.run(out,self.root/'.env');self.assertEqual(len(calls),2)

if __name__=='__main__':unittest.main()
