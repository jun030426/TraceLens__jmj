"""New-source followups through real deterministic gates; fake model replies only."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from video_extraction.pipeline import source_followup as sf, visual_gate as vg, document_links as dl
from video_extraction.pipeline import audio_followup as af, audio_workflow as aw, runtime_setup as setup
from video_extraction.pipeline import video_followup as vf
from video_extraction.shared.common import read,save,signature,digest_file
from video_extraction.shared.records import base_record
from video_extraction.tests.test_correction_gate import block,result
from video_extraction.tests.test_audio_primary_scope import scoped
from video_extraction.tests.test_audio_batch import batch_fixture
from video_extraction.tests.test_audio_target_window import raw_file

class VisualClient:
    model='synthetic'
    def __init__(self,missing=False,annotation=False):self.missing=missing;self.annotation=annotation;self.calls=[]
    def call(self,name,media,prompt,schema):
        self.calls.append(name);data=json.loads(prompt.split('DATA:\n',1)[1])
        if name=='pdf-source-structure-v1':
            ids=[r['id'] for r in data['regions']]
            return {'complete':True,'reading_order':ids,'checks':[{'id':i,'source_supported':True,
                'structure_supported':True,'order_clear':True,'reason':'synthetic structure'} for i in ids],
                'relations':[],'missing':[],'cross_page_uncertain':[]}
        if name.startswith('source-followup-'):
            restored=any(r.get('text')=='missing lesson sentence' or r.get('kind')=='annotation' for r in data['regions'])
            regions=[]
            if self.missing and not restored:
                regions=[{'target_id':'NEW','bbox':[500,500,900,900],'reason':'visible missing region','issue':'omission',
                    'layer':'visual' if self.annotation else 'text','issue_ids':[i['id'] for i in data['issues']]}]
            return {'complete_scan':True,'regions':regions,'checks':[{'id':i['id'],'decision':'repair_needed' if regions else 'existing_supported',
                        'source_clear':True,'reason':'synthetic independent image evidence'} for i in data['issues']]}
        if name.endswith('_read'):
            if self.annotation:r={'kind':'annotation','description':'visible bracket','literal_text':'','related_block_ids':['b'],
                'readable':True,'uncertainties':[],'source_conflicts':[]}
            else:r={'kind':'text','text':'missing lesson sentence','readable':True,'uncertainties':[],'source_conflicts':[]}
            return {'items':[{'region_id':i['region_id'],'reading':copy.deepcopy(r)} for i in data['regions']]}
        if name.endswith('_verify'):
            r={'decision':'accept','source_clear':True,'all_changes_visible':True,'same_region':True,'source_conflict':False,'reason':'synthetic pixels'}
            return {'items':[{'region_id':i['region_id'],'verification':r} for i in data['regions']]}
        raise AssertionError(name)

class FollowupVisualTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.image=self.root/'page.png';Image.new('RGB',(400,300),'white').save(self.image)
        self.t={'id':'new:1','unit_key':'page','source_id':'new','source_file':'new.pdf','source_kind':'pdf',
            'image':str(self.image),'dimensions':[400,300],'location':{'page':1},'time_seconds':0,'pdf_inventory':{'words':[]}}
        b=block('normal lesson sentence','text',[0,0,400,400]);raw=result(b,b);raw.update(image_sha256=digest_file(self.image),audit={})
        self.base=vg.enforce(raw,self.image);self.plan={'ocr_available':False};self.native={}
    def run_case(self,client,baseline=None):
        with patch.object(sf.generalized_visual,'run',side_effect=lambda r,*a:r):
            return sf.run(self.t,baseline or self.base,self.native,self.plan,self.root/'followup',client)
    def test_missing_native_sentence_restored_existing_text_untouched_and_replayed(self):
        self.t['native_text']='normal lesson sentence\nmissing lesson sentence';api=VisualClient(True)
        final,receipt,changes=self.run_case(api)
        self.assertEqual(final['final_blocks'][0],self.base['final_blocks'][0])
        self.assertIn('missing lesson sentence',final['text']);self.assertEqual(len(changes),1)
        self.assertTrue(receipt['settled_issue_ids']);self.assertFalse(receipt['state']['regions'])
        n=len(api.calls)
        replay=sf.run(self.t,self.base,self.native,self.plan,self.root/'followup',None,True)
        self.assertEqual(replay,(final,receipt,changes));self.assertEqual(len(api.calls),n)
        rows=sf.records(self.t,self.base,final,vg.records(self.t,self.base,base_record))
        self.assertTrue(all(r['eligible_for_chunking'] for r in rows))
    def test_normal_source_never_rewritten(self):
        api=VisualClient();final,receipt,changes=self.run_case(api)
        self.assertEqual(final,self.base);self.assertEqual(changes,[])
        self.assertEqual(api.calls,['pdf-source-structure-v1','source-followup-audit','source-followup-confirm'])
        self.assertEqual(sf.add_unresolved(self.t,[],receipt),[])

    def test_complementary_ppt_confirm_keeps_its_proof_and_independent_audit(self):
        class ComplementaryConfirm(VisualClient):
            def call(self, name, *args):
                answer = super().call(name, *args)
                if name == 'source-followup-confirm':
                    answer['checks'] = answer['checks'][:1]
                    answer['checks'][0]['source_clear'] = False
                elif name == 'source-followup-confirm-document-issue-mapping-v1':
                    answer['checks'] = answer['checks'][1:]
                return answer

        self.t['source_kind'] = 'ppt'
        issues = [{'id': f'issue-{i}', 'kind': 'native_ppt'} for i in range(57)]
        client = ComplementaryConfirm()
        with patch.object(sf, 'native_issues', return_value=issues):
            result = self.run_case(client)
            folder = self.root / 'followup'
            receipt = read(folder / 'receipt.json')
            self.assertEqual(receipt['state']['unresolved_issue_ids'], ['issue-0'])
            proof, = receipt['combined_checks']
            self.assertEqual((proof['round'], proof['stage']), (0, 'confirm'))
            self.assertEqual(proof['original_sha256'], digest_file(folder / '0/confirm.json'))
            self.assertEqual(proof['repair_sha256'], digest_file(folder / '0/confirm-issue-mapping-v1.json'))
            self.assertEqual(sf.run(self.t, self.base, self.native, self.plan, folder, None, read_only=True), result)

    def test_document_wrong_issue_ids_retry_once_preserves_original_and_replays(self):
        class WrongIds(VisualClient):
            def call(self,*args):
                value=super().call(*args)
                if args[0]=='source-followup-audit':
                    value['checks']=[{'id':'b','decision':'existing_supported','source_clear':True,'reason':'wrong namespace'}]
                return value
        client=WrongIds();final,receipt,changes=self.run_case(client)
        self.assertEqual(final,self.base);self.assertFalse(changes)
        folder=self.root/'followup/0'
        rejected=(folder/'audit.json').read_bytes()
        self.assertEqual(read(folder/'audit.json')['answer']['checks'][0]['id'],'b')
        self.assertTrue((folder/'audit-issue-mapping-v1.json').exists())
        self.assertEqual(client.calls.count('source-followup-audit-document-issue-mapping-v1'),1)
        self.assertEqual(sf.run(self.t,self.base,{},self.plan,self.root/'followup',None,True),(final,receipt,changes))
        self.assertEqual((folder/'audit.json').read_bytes(),rejected)
        modified=read(folder/'audit-issue-mapping-v1.json');modified['binding']='tampered'
        save(folder/'audit-issue-mapping-v1.json',modified)
        with self.assertRaisesRegex(ValueError,'mapping_repair_changed'):
            sf.run(self.t,self.base,{},self.plan,self.root/'followup',None,True)

    def test_document_repeated_wrong_ids_stays_rejected_and_video_does_not_retry(self):
        class AlwaysWrong(VisualClient):
            def call(self,*args):
                value=super().call(*args)
                if args[0].startswith('source-followup-'):
                    value['checks']=[{'id':'b','decision':'existing_supported','source_clear':True,'reason':'wrong namespace'}]
                return value
        client=AlwaysWrong()
        with self.assertRaisesRegex(ValueError,'source_followup_issue_mapping'):self.run_case(client)
        self.assertEqual(client.calls.count('source-followup-audit-document-issue-mapping-v1'),1)
        with self.assertRaisesRegex(ValueError,'source_followup_issue_mapping'):self.run_case(client)
        self.assertEqual(client.calls.count('source-followup-audit-document-issue-mapping-v1'),1)
        video={**self.t,'source_kind':'video'};client=AlwaysWrong()
        with self.assertRaisesRegex(ValueError,'source_followup_issue_mapping'):
            sf.inspect(video,self.base,[],self.root/'video',client,'audit')
        self.assertEqual(client.calls,['source-followup-audit'])
    def test_missing_mark_discovered_but_not_approved_without_ink_specialist(self):
        final,receipt,changes=self.run_case(VisualClient(True,True))
        self.assertEqual(final['visuals'][0]['kind'],'annotation')
        rows=sf.records(self.t,self.base,final,vg.records(self.t,self.base,base_record))
        ink=next(r for r in rows if r['kind']=='annotation')
        self.assertFalse(ink['eligible_for_chunking']);self.assertIn('specialized_ink_verification_required',ink['safety_findings'])
    def test_saved_source_change_rejected(self):
        self.run_case(VisualClient());Image.new('RGB',(400,300),'red').save(self.image)
        with self.assertRaises(ValueError):sf.run(self.t,self.base,{},self.plan,self.root/'followup',None,True)
    def test_unrelated_edit_rejected(self):
        raw=copy.deepcopy(self.base);raw['original']={'blocks':self.base['final_blocks'],'visuals':[]}
        raw['final_blocks'][0]['text']='changed normal sentence'
        with self.assertRaisesRegex(ValueError,'unrequested_region'):sf.apply_round(self.base,raw,[{'target_id':'NEW'}],self.image)
    def test_deferred_new_region_cleared_only_after_matching_verified_addition(self):
        raw=copy.deepcopy(self.base);raw.pop('common_gate');box=[500,500,900,900]
        raw['deferred_regions']=[{'target_id':'NEW','bbox':box,'layer':'text'}]
        raw['holds']=[{'reason':'region_budget','target_id':'NEW','layer':'text','region':{'bbox':box}}]
        baseline=vg.enforce(raw,self.image)
        final,receipt,_=self.run_case(VisualClient(True),baseline)
        self.assertFalse(final['deferred_regions']);self.assertFalse(final['holds'])
    def test_calculation_hold_cannot_be_cleared_by_positive_model(self):
        raw=copy.deepcopy(self.base);raw.pop('common_gate');raw['holds']=[{'target_id':'b','layer':'text','reason':'calculation_gate'}]
        baseline=vg.enforce(raw,self.image);final,_,_=self.run_case(VisualClient(),baseline)
        self.assertEqual(final['holds'],baseline['holds'])
    def test_repeated_native_hints_coalesce_without_id_collision(self):
        self.t['native_text']='missing lesson sentence\nmissing lesson sentence'
        self.assertEqual(len(sf.native_issues(self.t,self.base,{})),1)
    def test_incomplete_scan_remains_visible_hold(self):
        class Incomplete(VisualClient):
            def call(self,*args):
                r=super().call(*args)
                if args[0].startswith('source-followup-'):r['complete_scan']=False
                return r
        _,receipt,_=self.run_case(Incomplete())
        self.assertEqual(sf.add_unresolved(self.t,[],receipt)[0]['reasons'],['source_followup_requires_review'])

    def test_conflicting_positive_findings_do_not_release_issue(self):
        self.t['native_text']='hidden native claim'
        class Disagree(VisualClient):
            def call(self,*args):
                r=super().call(*args)
                if args[0]=='source-followup-confirm':
                    for c in r['checks']:c['decision']='not_visible'
                return r
        final,receipt,changes=self.run_case(Disagree())
        self.assertEqual(final,self.base);self.assertFalse(changes)
        self.assertFalse(receipt['settled_issue_ids']);self.assertTrue(receipt['state']['unresolved_issue_ids'])

    def test_structure_missing_enters_same_repair_path(self):
        class MissingStructure(VisualClient):
            def call(self,*args):
                r=super().call(*args)
                if args[0]=='pdf-source-structure-v1' and len(r['reading_order'])==1:r['missing']=['missing lesson sentence']
                return r
        final,receipt,_=self.run_case(MissingStructure(True))
        self.assertEqual(len(final['final_blocks']),2)
        self.assertTrue(any(i.startswith('structure-missing:') for i in receipt['settled_issue_ids']))

class PageLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.image=self.root/'p.png';Image.new('RGB',(10,10),'white').save(self.image)
        self.pages=[{'id':f'p{i}','source_id':'s','source_file':'s.pdf','source_kind':'pdf','modality':'visual',
            'image':str(self.image),'location':{'page':i}} for i in (1,2)]
        self.task=dl.tasks(self.pages)[0]
        self.rows=[dict(base_record(p,'b','document','text',f'page {i}'),eligible_for_chunking=True) for i,p in enumerate(self.pages)]
        self.issue=base_record(self.pages[0],'gap','review','coverage_issue','');self.issue['reasons']=['pdf_cross_page_connection_requires_review']
        self.data={'source_id':'s','records':self.rows,'issues':[self.issue],'pages':[1,2]}
        self.answer={'links':[{'from_id':self.rows[0]['id'],'to_id':self.rows[1]['id'],'kind':'continuation',
            'source_supported':True,'reason':'original continuation'}],'checks':[{'id':self.issue['id'],'decision':'linked',
            'record_ids':[r['id'] for r in self.rows],'source_clear':True,'reason':'visible continuation'}]}
    def test_only_adjacent_same_document(self):
        self.assertEqual(len(dl.tasks(self.pages)),1)
        self.pages[1]['location']['page']=3;self.assertEqual(dl.tasks(self.pages),[])
        self.pages[1]['location']['page']=2;self.pages[1]['source_id']='other';self.assertEqual(dl.tasks(self.pages),[])
    def test_link_without_rewriting_and_saved_replay(self):
        class API:
            def call(_,name,media,prompt,schema):return copy.deepcopy(self.answer)
        results={p['id']:{'records':[r]+([self.issue] if i==0 else [])} for i,(p,r) in enumerate(zip(self.pages,self.rows))}
        got=dl.run(self.task,results,self.root,API())
        self.assertTrue(got['records'][0]['eligible_for_chunking']);self.assertEqual(got['changes'],[])
        dl.verify(self.task,self.root,got,[self.rows[0],self.issue,self.rows[1]])
        changed=copy.deepcopy(self.rows);changed[0]['observed_text']='fabricated'
        with self.assertRaisesRegex(ValueError,'page_results_changed'):dl.verify(self.task,self.root,got,changed+[self.issue])
    def test_large_evidence_is_bound_locally_and_both_reads_get_the_source_index(self):
        self.rows[0]['native_document_text_reference'] = 'evidence' * 50000
        self.rows[1]['bbox'] = [20, 30, 80, 90]
        self.issue['raw_payload'] = {'page': 1, 'description': 'Does this table continue?'}
        calls = []

        class Client:
            def call(_, stage, images, prompt, schema):
                calls.append((stage, images, json.loads(prompt.split('DATA:\n', 1)[1])))
                self.assertLess(len(prompt.encode()), 5000)
                return copy.deepcopy(self.answer)

        results = {self.pages[0]['id']: {'records': [self.rows[0], self.issue]},
                   self.pages[1]['id']: {'records': [self.rows[1]]}}
        output = dl.run(self.task, results, self.root, Client())
        self.assertEqual([stage for stage, _, _ in calls], ['document-adjacent-read', 'document-adjacent-verify'])
        for _, images, data in calls:
            self.assertEqual(images, [self.image, self.image])
            self.assertEqual([r['page'] for r in data['records']], [1, 2])
            self.assertEqual(data['records'][1]['bbox'], self.rows[1]['bbox'])
            self.assertEqual(data['issues'][0]['description'], self.issue['raw_payload']['description'])
        self.assertTrue(output['records'][0]['eligible_for_chunking'])
        self.assertEqual(dl.run(self.task, results, self.root, None), output)
        rows = [self.rows[0], self.issue, self.rows[1]]
        dl.verify(self.task, self.root, output, rows)
        self.rows[0]['native_document_text_reference'] = 'changed after extraction'
        with self.assertRaisesRegex(ValueError, 'page_results_changed'):
            dl.verify(self.task, self.root, output, rows)

    def test_disagreement_is_preserved_not_dropped(self):
        other=copy.deepcopy(self.answer);other['links']=[];other['checks'][0]['decision']='uncertain'
        got=dl.selection(self.task,self.data,[self.answer,other]);self.assertFalse(got['records'][0]['eligible_for_chunking'])
        self.assertEqual(got['resolved_coverage_ids'],[])
    def test_held_target_or_different_table_columns_cannot_be_selected(self):
        self.rows[0]['eligible_for_chunking']=False
        self.assertFalse(dl.selection(self.task,self.data,[self.answer]*2)['records'][0]['eligible_for_chunking'])
        self.rows[0]['eligible_for_chunking']=True;self.rows[0]['observed_text']='| a | b |';self.rows[1]['observed_text']='| c | d | e |'
        self.answer['links'][0]['kind']='table_continuation'
        self.assertFalse(dl.selection(self.task,self.data,[self.answer]*2)['records'][0]['eligible_for_chunking'])
    def test_wrong_scope_rejected(self):
        self.answer['links'][0]['to_id']=self.rows[0]['id']
        with self.assertRaisesRegex(ValueError,'wrong_scope'):dl.selection(self.task,self.data,[self.answer]*2)

class AudioFollowupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.source=raw_file(self.root)
        self.unit={'id':'a','source_id':'s','source_file':str(self.source),'source_audio':str(self.source),'location':{'audio_offset_seconds':10}}
        self.rows=[{'id':'s1','text':'그런데','start_seconds':1,'end_seconds':2}]
        self.rec=dict(base_record(self.unit,'new-prefix','audio','coverage_issue',''),start_seconds=11,end_seconds=12,reasons=['excluded_prefix_needs_own_review'])
    def api(self,impact='low',disagree=False):
        class API:
            def call(_,name,media,prompt,schema):
                data=json.loads(prompt.split('DATA:\n',1)[1]);task={'after':'그런데','role':'control','target_clip_meta':{'duration_seconds':data['target_seconds'][1]}}
                b,_=scoped(task)
                if 'blind' in name:return b
                return {'literal_text':'아니다' if disagree else b['text'],'target_scope':b['target_scope'],'target_spans':b['target_spans'],
                    'impact':impact,'uncertain':False,'full_target_checked':True,'no_unique_concept_or_step':True,
                    'no_number_negation_or_condition_change':True,'core_instruction_preserved_without_target':True,
                    'context_preserves_relation':True,'reason':'synthetic routing evidence'}
        return API()
    def test_new_prefix_and_offset_routed_without_approving_or_rewriting(self):
        got,decisions=af.route(self.unit,[self.rec],self.rows,self.source,30,self.root/'f',self.api())
        self.assertEqual(got[0]['impact_review']['route'],'administrator');self.assertFalse(got[0]['eligible_for_chunking'])
        self.assertEqual(got[0]['observed_text'],'');self.assertEqual(got[0]['start_seconds'],11)
        self.assertEqual(af.route(self.unit,[self.rec],self.rows,self.source,30,self.root/'f',None,True),(got,decisions))
    def test_high_unknown_and_disagreement_keep_ordinary_hold(self):
        for impact,disagree in [('high',False),('unknown',False),('low',True)]:
            got,d=af.route(self.unit,[self.rec],self.rows,self.source,30,self.root/(impact+str(disagree)),self.api(impact,disagree))
            self.assertEqual(d[0]['route'],'ordinary_hold');self.assertEqual(got,[self.rec])
    def test_normal_repetition_is_not_sent_to_impact_model(self):
        rec={**self.rec,'eligible_for_chunking':True,'observed_text':'반복 반복'}
        got,d=af.route(self.unit,[rec],self.rows,self.source,30,self.root/'f',None)
        self.assertEqual(got,[rec]);self.assertEqual(d,[])
    def test_missing_interval_is_not_low_impact(self):
        rec={**self.rec,'end_seconds':100}
        got,d=af.route(self.unit,[rec],self.rows,self.source,30,self.root/'f',None)
        self.assertEqual(got,[rec]);self.assertEqual(d[0]['reason'],'source_interval_unresolved')

class RuntimeVideoTests(unittest.TestCase):
    def test_unknown_language_does_not_pass_none_into_subprocess_or_load_model(self):
        with patch.object(setup.rt,'imports',return_value={'ok':True}),patch.object(setup.subprocess,'run',side_effect=AssertionError('no model')):
            r=setup.ensure_alignment(sys.executable,None)
        self.assertEqual(r['state'],'awaiting_source_language');self.assertFalse(r['model_cache_ready'])
    def test_video_missing_scenes_become_frames_and_repeated_content_keeps_times(self):
        import av
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'video';source.write_bytes(b'synthetic video');frames=[{'id':'f','path':'f.png','time_seconds':0}]
            metadata={'video_origin_seconds':0,'fps':25};event={'reason':'possibly_unrepresented_scene_change','start_seconds':1,'end_seconds':2}
            class Container:
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def decode(self,**kw):return iter([SimpleNamespace(time=t,to_image=lambda:Image.new('RGB',(20,20),'red')) for t in (0,1,2)])
            with patch.object(vf.multimodal_checks,'scan_video',return_value=([event],{})),patch.object(av,'open',return_value=Container()):
                out=vf.expand(source,frames,metadata,root,{'scan_fps':2})
            self.assertEqual([f['time_seconds'] for f in out],[0,1,2])
            with patch.object(av,'open',side_effect=AssertionError('must reuse')):
                self.assertEqual(vf.expand(source,frames,metadata,root,{'scan_fps':2}),out)
            Path(root/out[1]['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'image_changed'):vf.expand(source,frames,metadata,root,{'scan_fps':2})

class AudioWorkflowFollowupTests(unittest.TestCase):
    def test_neighbor_gets_own_clip_and_normal_repetition_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=raw_file(root)
            u={'id':'new:audio:0','source_id':'new','source_kind':'audio','modality':'audio','source_audio':str(source),
               'source_file':str(source),'interval':[0,30],'review_interval':[0,30],'location':{'audio_offset_seconds':0}}
            u['context_clip']=str(root/'window.wav');u['context_clip_meta']=aw.final.clip(source,Path(u['context_clip']),0,30)
            u.update(target_clip=u['context_clip'],target_clip_meta=u['context_clip_meta'])
            class ASR:
                def transcribe(self,path):return {'text':'첫 설명 두 번째 반복 반복','language':'ko','segments':[
                    {'start':1,'end':3,'text':'첫 설명'},{'start':4,'end':5,'text':'두 번째'},
                    {'start':10,'end':13,'text':'반복 반복'}]}
            class API:
                @batch_fixture
                def call(self,name,media,prompt,schema):
                    if 'coverage' in name:return {'checked_full_core':True,'speech_unresolved':False,'findings':[]}
                    data=json.loads(prompt.split('DATA:\n',1)[1]);duration=data['target_seconds'][1]
                    text={1:'두 번째',2:'첫 설명',3:'반복 반복'}[duration]
                    if duration==1 and 'prior_discrepancy_not_truth' not in data:text='다른 내용'
                    issues=[{'neighbor_id':'new:speech:1','kind':'content','observed_text':'두 번째','reason':'fixture clue'}] if duration==2 else []
                    task={'role':'control','before':text,'after':text,'target_clip_meta':{'duration_seconds':duration}}
                    b,r=scoped(task,issues=issues);return b if 'blind' in name else r
            with patch.object(aw.core,'detect_speech',return_value=[[1,3],[4,5],[10,13]]):
                got=aw.run(u,[u],root/'run',{'followup_policy':sf.POLICY},API(),ASR())
            self.assertEqual(got['neighbor_followup'][0]['target_id'],'new:speech:1')
            self.assertTrue(got['neighbor_followup'][0]['passed'])
            self.assertTrue(all(r['eligible_for_chunking'] for r in got['records']))
            self.assertIn('반복 반복',[r['observed_text'] for r in got['records']]);self.assertEqual(got['changes'],[])
            self.assertTrue(all(r['detected_language']=='ko' for r in got['records']))
            aw.validate_saved(u,root/'run',got)

class AdditionalGateTests(unittest.TestCase):
    setUp=FollowupVisualTests.setUp
    run_case=FollowupVisualTests.run_case
    def test_hidden_native_ocr_false_alarm_requires_two_source_readings(self):
        from video_extraction.pipeline import document_workflow as dw
        self.t['native_text']='hidden incorrect line'
        self.t['pdf_inventory']['words']=[{'text':'WRONG','bbox':[50,50,100,100],'valid_box':True}]
        class Hidden(VisualClient):
            def call(self,*args):
                r=super().call(*args)
                if args[0].startswith('source-followup-'):
                    for c in r['checks']:c['decision']='not_visible'
                return r
        final,receipt,_=self.run_case(Hidden())
        initial=vg.records(self.t,final,base_record);structure=read(receipt['structure_review'])
        before,_=dw.apply(self.t,final,initial,{},structure)
        after,_=dw.apply(self.t,final,initial,{},structure,receipt)
        self.assertFalse(before[0]['eligible_for_chunking']);self.assertTrue(after[0]['eligible_for_chunking'])
        self.assertEqual(after[0]['observed_text'],initial[0]['observed_text'])
    def test_unverified_edit_is_rejected_even_for_requested_target(self):
        raw=copy.deepcopy(self.base);raw['original']={'blocks':copy.deepcopy(self.base['final_blocks']),'visuals':[]}
        raw['final_blocks'][0]['text']='different';raw['corrections']=[]
        with self.assertRaisesRegex(ValueError,'without_region_verification'):
            sf.apply_round(self.base,raw,[{'target_id':'b','layer':'text','bbox':[0,0,400,400]}],self.image)
    def test_final_change_log_does_not_count_undone_intermediate_edits(self):
        self.assertEqual(sf.effective_changes(self.base,self.base),[])

class LanguageAlignmentTests(unittest.TestCase):
    def test_detected_language_attached_per_job_without_loading_models(self):
        import wave
        from video_extraction.audio import word_alignment as wa
        from video_extraction.shared.common import jsonl
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'source.wav'
            with wave.open(str(audio),'wb') as f:
                f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*32000)
            rows=[{'id':language,'modality':'audio','kind':'speech','eligible_for_chunking':True,
                'word_alignment_required':True,'source_audio':str(audio),'audio_offset_seconds':10,
                'start_seconds':10,'end_seconds':12,'observed_text':'가 가','detected_language':language} for language in ('ko','en',None)]
            jsonl(root/'records.jsonl',rows)
            p=wa.prepare(root/'records.jsonl',root/'alignment',language=None)
            self.assertEqual([j['language'] for j in p['jobs']],['ko','en'])
            self.assertEqual(p['jobs'][0]['interval'],[0,2])
            self.assertEqual(p['excluded'][0]['reason'],'alignment_language_unresolved')

if __name__=='__main__':unittest.main()
