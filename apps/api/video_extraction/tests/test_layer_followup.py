import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

from video_extraction.shared.common import read, save, validate
from video_extraction.shared.gemini import Blocked
from video_extraction.video.layer_followup import focus_targets, review_symbols, review_visuals, merge_frame, execute_task, prepare, main


def base():
    v={'id':'v','kind':'annotation','bbox':[100,100,900,900],'description':'밑줄',
       'literal_text':'','related_block_ids':['code'],'uncertainties':[]}
    g={'layer':'visual','region_id':'visual-9','number':9,'target_id':'v','bbox':v['bbox'],
       'issues':[{'reason':'visual_verification'}],'before':copy.deepcopy(v)}
    return {'signature':'source','frame_id':'frame-00030','frame_time_seconds':0,'visuals':[v],
            'final_blocks':[{'id':'code','kind':'code','bbox':[100,100,900,900],
              'text':'total = 0\n  name = student[o]\nprint("----")\nprint("end")','uncertainties':[]},
              {'id':'output','kind':'text','bbox':[50,50,500,500],'text':'결과\n------\n학생 수: 4','uncertainties':[]}],
            'holds':[{'layer':'visual','reason':'region_budget','region':g,'target_id':'v'},
                     {'layer':'text','target_id':'code','reason':'verification_hold'}],
            'deferred_regions':[g],'status':'needs_review','text':'old','corrections':[],'changed_blocks':0}


class Client:
    def __init__(self,disagree=False,hold=False,bad_ids=False,interrupt=False):
        self.stages=[];self.disagree=disagree;self.hold=hold;self.bad_ids=bad_ids;self.interrupt=interrupt
    def call(self,stage,images,prompt,schema):
        self.stages.append(stage)
        if self.interrupt and stage=='followup_visual_verify':raise Blocked('request_budget_exhausted')
        data=json.loads(prompt.split('DATA:\n')[1]);rows=[]
        for r in data.get('targets',data.get('regions',[])):
            rid=r['region_id']
            if stage=='followup_symbol_verify':
                field='verification';value={'value_confirmed':not self.hold,'boundary_clear':True,'glyphs_clear':True,'reason':'fixture'}
            elif 'symbol' in stage:
                assert 'old_value' not in r and 'value' not in r
                field='reading';value={'value':'0' if rid=='index' else '-----','clear':True,'uncertainties':[],'evidence':'fixture'}
                if self.disagree and stage.endswith('_b') and rid=='index':value['value']='o'
            elif stage.endswith('verify'):
                field='verification';value={'decision':'hold' if self.hold else 'accept','source_clear':True,
                       'same_region':True,'all_changes_visible':True,'source_conflict':False,'reason':'fixture'}
            else:
                field='reading';value={'kind':'annotation','description':'붉은 밑줄','literal_text':'',
                    'related_block_ids':['code'],'uncertainties':[],'source_conflicts':[],'readable':True}
            rows.append({'region_id':rid,field:value})
        if self.bad_ids:rows[0]['region_id']='not-requested'
        result={'items':list(reversed(rows))};validate(result,schema);return result


class FollowupTests(unittest.TestCase):
    def setup_dir(self,d):
        p=Path(d);(p/'frames').mkdir();Image.new('RGB',(400,300),'white').save(p/'frames/frame-00030.png')
        return p

    def task(self,kind):
        r=base();return {'id':'frame-00030-'+kind,'frame_id':r['frame_id'],'kind':kind,
                         'regions':r['deferred_regions'] if kind=='visual' else focus_targets(r)}

    def receipt(self,kind,outcomes):return {'kind':kind,'outcomes':outcomes}

    def test_54_style_deferral_is_processed_without_extraction_or_audit(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_dir(d);c=Client();task=self.task('visual');r=base()
            results=review_visuals(task,p,r,c);new=merge_frame(r,[self.receipt('visual',results)],[task])
            self.assertEqual(c.stages,['followup_visual_read','followup_visual_verify'])
            self.assertEqual(new['visuals'][0]['description'],'붉은 밑줄')
            self.assertFalse(new['deferred_regions'])
            self.assertEqual(new['holds'],[r['holds'][1]])
            self.assertEqual(r,base())

    def test_failed_visual_is_reviewed_but_not_approved(self):
        for c in (Client(hold=True),Client(bad_ids=True)):
            with tempfile.TemporaryDirectory() as d:
                p=self.setup_dir(d);task=self.task('visual');r=base()
                outcomes=review_visuals(task,p,r,c);new=merge_frame(r,[self.receipt('visual',outcomes)],[task])
                self.assertEqual(new['visuals'],r['visuals']);self.assertEqual(new['followup']['visual_verified'],0)
                self.assertFalse(new['deferred_regions']);self.assertEqual(new['status'],'needs_review')

    def test_only_matching_budget_hold_is_retired(self):
        r=base();other=copy.deepcopy(r['deferred_regions'][0]);other['region_id']='visual-10'
        r['deferred_regions'].append(other)
        r['holds'].append({'reason':'region_budget','layer':'visual','target_id':'v','region':other})
        receipt=self.receipt('visual',[{'region_id':'visual-9','target_id':'v','status':'verified','after':r['visuals'][0]}])
        new=merge_frame(r,[receipt],[])
        self.assertEqual([g['region_id'] for g in new['deferred_regions']],['visual-10'])
        self.assertTrue(any(h['reason']=='region_budget' for h in new['holds']))

    def test_symbol_changes_preserve_whitespace_and_unrelated_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_dir(d);c=Client();task=self.task('symbols');r=base()
            outcomes=review_symbols(task,p,r,c);new=merge_frame(r,[self.receipt('symbols',outcomes)],[task])
            self.assertEqual(new['final_blocks'][0]['text'],'total = 0\n  name = student[0]\nprint("-----")\nprint("end")')
            self.assertEqual(new['final_blocks'][1]['text'],'결과\n-----\n학생 수: 4')
            self.assertIn(r['holds'][1],new['holds'])
            self.assertEqual(len(c.stages),3)

    def test_disagreeing_symbols_stay_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_dir(d);task=self.task('symbols');r=base()
            outcomes=review_symbols(task,p,r,Client(disagree=True));new=merge_frame(r,[self.receipt('symbols',outcomes)],[task])
            self.assertIn('student[o]',new['text'])
            self.assertEqual(outcomes[0]['status'],'needs_review')
            self.assertEqual(new['status'],'needs_review')

    def test_unclear_confirmation_or_bad_mapping_preserves_all_symbols(self):
        for c in (Client(hold=True),Client(bad_ids=True)):
            with tempfile.TemporaryDirectory() as d:
                p=self.setup_dir(d);task=self.task('symbols');r=base()
                outcomes=review_symbols(task,p,r,c);new=merge_frame(r,[self.receipt('symbols',outcomes)],[task])
                self.assertEqual(new['final_blocks'],r['final_blocks'])

    def test_focus_anchors_reject_multiple_matching_lines(self):
        r=base();r['final_blocks'][0]['text']+='\nname = student[0]'
        with self.assertRaisesRegex(ValueError,'ambiguous_focus_anchor'):focus_targets(r)

    def test_partial_execution_does_not_write_completion_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.setup_dir(d);src=p/'source';save(src/'vision/frame-00030/result.json',base())
            config={'source':str(src)};task=self.task('visual')
            with self.assertRaises(Blocked):execute_task(task,p,config,Client(interrupt=True))
            self.assertFalse((p/'receipts'/f'{task["id"]}.json').exists())
            c=Client();first=execute_task(task,p,config,c);count=len(c.stages)
            self.assertEqual(execute_task(task,p,config,c),first);self.assertEqual(len(c.stages),count)

    def test_unprocessed_focus_is_explicitly_pending(self):
        new=merge_frame(base(),[],[self.task('symbols')])
        self.assertEqual(sum(h['reason']=='symbol_check_pending' for h in new['holds']),3)

    def test_offline_prepare_never_constructs_api_client_and_binds_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';out=root/'out';hashes={};fids=[]
            from video_extraction.shared.common import digest_file
            for n in (30,31,32):
                fid=f'frame-{n:05}';fids.append(fid);r=base();r['frame_id']=fid
                save(source/'vision'/fid/'result.json',r)
                (source/'frames').mkdir(exist_ok=True);img=source/'frames'/f'{fid}.png'
                Image.new('RGB',(400,300),'white').save(img);hashes[fid]=digest_file(img)
            save(source/'validation-config.json',{'model':'fixture','selected_ids':fids,'frame_sha256':hashes})
            save(source/'run-state.json',{'state':'complete'})
            with patch('video_extraction.video.layer_followup.Gemini',side_effect=AssertionError('API forbidden')):
                with patch('video_extraction.video.layer_followup.FOCUS_IMAGE_HASHES',hashes), patch('sys.argv',['followup','prepare','--source',str(source),'--output',str(out)]):
                    self.assertEqual(main(),0)
            self.assertEqual(read(out/'summary.json')['visual_reviewed'],0)
            r=read(source/'vision/frame-00030/result.json');r['final_blocks'][0]['text']+='\nextra'
            save(source/'vision/frame-00030/result.json',r)
            with patch('video_extraction.video.layer_followup.FOCUS_IMAGE_HASHES',hashes):
                with self.assertRaisesRegex(ValueError,'followup_inputs_changed'):prepare(source,out)


if __name__=='__main__':unittest.main()
