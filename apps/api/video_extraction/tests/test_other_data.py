import copy
import io
import json
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

from video_extraction.shared.common import read, save, digest_file
from video_extraction.shared.gemini import Blocked
from video_extraction.ppt.other_data import OUTPUT, PREPROCESS, ppt_native, native_documents, prepare, check_plan, ScopedClient, screen_records, execute, fair_queue, run


class OtherDataTests(unittest.TestCase):
    def test_all_real_ppt_text_tables_match_original_and_answers_excluded(self):
        sources=read(PREPROCESS/'source-registry.json')['sources']
        old=[json.loads(l) for l in (PREPROCESS/'records.jsonl').read_text().splitlines()]
        records,changes,assets,pending=native_documents(sources,old)
        self.assertEqual(len(records),338);self.assertEqual(changes,[]);self.assertEqual(len(assets),9)
        self.assertEqual(sum(r['eligible_for_chunking'] for r in records),317)
        self.assertTrue(all(not r['eligible_for_chunking'] for r in records if r['educational_role']=='evaluation_reference'))
        self.assertEqual(len(pending),4)

    def test_xml_order_breaks_blank_cells_and_code_not_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'test.pptx'
            p='http://schemas.openxmlformats.org/presentationml/2006/main'
            a='http://schemas.openxmlformats.org/drawingml/2006/main'
            r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
            rel='http://schemas.openxmlformats.org/package/2006/relationships'
            with zipfile.ZipFile(file,'w') as z:
                z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId id="2" r:id="r2"/><p:sldId id="1" r:id="r1"/></p:sldIdLst></p:presentation>')
                z.writestr('ppt/_rels/presentation.xml.rels',f'<Relationships xmlns="{rel}"><Relationship Id="r1" Target="slides/slide1.xml"/><Relationship Id="r2" Target="slides/slide2.xml"/></Relationships>')
                z.writestr('ppt/slides/slide2.xml',f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="4"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>  x = 0</a:t></a:r><a:br/><a:r><a:t>o</a:t></a:r></a:p><a:p><a:r><a:t>001</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
                z.writestr('ppt/slides/slide1.xml',f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree><p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5"/></p:nvGraphicFramePr><a:graphic><a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>0</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p/></a:txBody></a:tc></a:tr></a:tbl></a:graphic></p:graphicFrame></p:spTree></p:cSld></p:sld>')
            rows,_,_=ppt_native(file)
            self.assertEqual(rows[0]['text'],'  x = 0\vo\n001');self.assertEqual(rows[0]['slide_number'],1)
            self.assertEqual(rows[1]['rows'],[['0','']]);self.assertEqual(rows[1]['slide_number'],2)

    def test_native_source_changes_not_inferred_from_old_text(self):
        sources=read(PREPROCESS/'source-registry.json')['sources']
        old=[json.loads(l) for l in (PREPROCESS/'records.jsonl').read_text().splitlines()]
        row=next(r for r in old if r['modality']=='document' and r['kind']=='unclassified')
        row['observed_text']='wrong text'
        records,changes,_,_=native_documents(sources,old)
        self.assertTrue(any(c['before']=='wrong text' for c in changes))
        self.assertFalse(any(r['observed_text']=='wrong text' for r in records))

    def test_prepare_covers_all_modalities_without_api(self):
        with tempfile.TemporaryDirectory() as tmp,patch('video_extraction.ppt.other_data.Gemini',side_effect=AssertionError('no API')):
            out=Path(tmp)/'out';p=prepare(out)
            self.assertEqual(len(p['tasks']),723)
            self.assertEqual(sum(t['kind']=='screen' and t['baseline'] is None for t in p['tasks']),83)
            self.assertEqual(sum(t['kind']=='audio' and t['priority'] for t in p['tasks']),75)
            self.assertEqual(check_plan(out),p)
            self.assertFalse(read(out/'summary.json')['all_content_verified'])

    def test_seeded_baseline_preserves_content_and_never_calls_extract(self):
        task=next(t for t in read(OUTPUT/'plan.json')['tasks'] if t['kind']=='screen' and t['baseline'])
        class Client:
            model='fake'
            def call(self,*args):raise AssertionError('unexpected API')
        client=ScopedClient(Client(),task['baseline']);old=copy.deepcopy(task['baseline'])
        result=client.call('layers_extract',[Path(task['media'])],'',{})
        self.assertEqual(result,old);result['blocks'][0]['text']='changed'
        self.assertEqual(task['baseline'],old)

    def test_protected_uncertainties_and_missing_references_cannot_be_selected(self):
        task=dict(id='t',source_sha256='s',media='/tmp/image',protected=[{'raw_payload':{'id':'b'}}])
        b=dict(id='b',kind='text',bbox=[0,0,100,100],text='0/o',uncertainties=[])
        v=dict(id='v',kind='diagram',bbox=[0,0,100,100],literal_text='',description='diagram',uncertainties=[],related_block_ids=['b'])
        result=dict(holds=[],deferred_regions=[],final_blocks=[b],visuals=[v])
        rows=screen_records(task,result)
        self.assertFalse(any(r['eligible_for_chunking'] for r in rows))
        self.assertIn('prior_source_hold_preserved',rows[0]['reasons'])
        self.assertIn('unusable_related_text',rows[1]['reasons'])

    def test_no_handwriting_selected_by_other_pipeline(self):
        task=dict(id='t',source_sha256='s',media='/tmp/image',protected=[])
        result=dict(holds=[],deferred_regions=[],final_blocks=[],visuals=[dict(id='v',kind='annotation')])
        self.assertEqual(screen_records(task,result),[])

    def test_audio_changes_remove_old_word_alignment_and_overlap_remains_held(self):
        class Client:
            model='fake'
            def call(self,stage,media,prompt,schema):
                self_exists=all(Path(p).exists() for p in media)
                assert self_exists
                if stage=='audio_reread':return dict(text='changed',readable=True,uncertainties=[],source_conflicts=[])
                return dict(decision='accept',source_clear=True,all_changes_visible=True,same_region=True,source_conflict=False,reason='test')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);wav=out/'test.wav'
            with wave.open(str(wav),'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*32000)
            seg=dict(id='a',start_seconds=0,end_seconds=1,text='old',review_reasons=[],words=[{'word':'old'}])
            task=dict(id='audio-a',kind='audio',segment=seg,source_sha256='s',audio=str(wav),offset=0,local_issues=[])
            r=execute(task,out,{},Client());row=r['records'][0]
            self.assertTrue(row['eligible_for_chunking']);self.assertEqual(row['words'],[])
            self.assertTrue(row['word_alignment_required']);self.assertEqual(row['original_text'],'old')
            task['local_issues']=['overlapping_transcript_intervals']
            r=execute(task,out,{},Client());self.assertFalse(r['records'][0]['eligible_for_chunking'])

    def test_round_robin_prevents_audio_or_images_starvation(self):
        self.assertEqual(fair_queue([[1,2,3],[4,5],[6]]),[1,4,6,2,5,3])

    def test_shared_budget_and_resume_do_not_repeat_completed_tasks(self):
        class Client:
            def __init__(self,*args,**kw):self.stats={'requests':0};self.max_calls=kw['max_calls']
        def fake_execute(task,out,plan,client):
            for stage in ['read','verify']:
                p=out/(task['id']+'-'+stage)
                if p.exists():continue
                if client.stats['requests']>=client.max_calls:raise Blocked('request_budget_exhausted')
                client.stats['requests']+=1;p.write_text('saved')
            return dict(task_id=task['id'],kind=task['kind'],status='checked',records=[])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out';out.mkdir();(root/'outputs/ink-continuation-v2').mkdir(parents=True)
            for name in ['native-documents.jsonl','native-changes.jsonl','native-pending.jsonl']:(out/name).write_text('')
            plan={'model':'fake','tasks':[dict(id='a',kind='screen'),dict(id='b',kind='audio')]}
            with patch('video_extraction.ppt.other_data.ROOT',root),patch('video_extraction.ppt.other_data.check_plan',return_value=plan),patch('video_extraction.ppt.other_data.Gemini',Client),patch('video_extraction.ppt.other_data.execute',side_effect=fake_execute):
                s=run(out,root/'env',3);self.assertEqual(s['stop_reason'],'request_budget_exhausted');self.assertEqual(s['completed_this_run'],['a'])
                self.assertFalse((out/'results/b.json').exists());first=digest_file(out/'results/a.json')
                s=run(out,root/'env',3);self.assertEqual(s['stop_reason'],'all_tasks_processed')
                self.assertEqual(s['completed_this_run'],['b']);self.assertEqual(s['api_stats']['requests'],1)
                self.assertEqual(first,digest_file(out/'results/a.json'))


if __name__=='__main__':unittest.main()
