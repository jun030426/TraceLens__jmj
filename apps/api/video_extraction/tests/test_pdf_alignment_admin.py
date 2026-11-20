import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from video_extraction.pdf import workflow as pdf
from video_extraction.audio import word_alignment as alignment
from video_extraction.pipeline import runner, connected
from video_extraction.shared.common import save, read, signature, digest_file
from video_extraction.tests.test_ink_policy import text_package, audit
from video_extraction.ink.policy.ink_policy import apply_policy
from video_extraction.ink.correction.ink_recovery import evaluate
from video_extraction.ink.policy.unreadable import route


class PDFTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        im=self.root/'page.png';Image.new('RGB',(400,300),'white').save(im)
        self.t={'id':'pdf:1','source_id':'new','source_file':'source.pdf','source_kind':'pdf','image':str(im),
                'location':{'page':1},'pdf_inventory':{'route':'scan_or_graphics_render','words':[]}}
        self.result={'final_blocks':[{'id':'a','bbox':[0,0,400,400],'text':'왼쪽'},
                                     {'id':'b','bbox':[500,0,1000,400],'text':'오른쪽'}],'visuals':[]}
        self.rows=[dict(runner.base_record(self.t,x['id'],'text','text',x['text']),eligible_for_chunking=True,judgment='source_rechecked') for x in self.result['final_blocks']]
        self.answer={'complete':True,'reading_order':['a','b'],'checks':[{'id':x,'source_supported':True,
            'structure_supported':True,'order_clear':True,'reason':'original page'} for x in ['a','b']],
            'relations':[],'missing':[],'cross_page_uncertain':[]}

    def receipt(self,answer=None):
        class API:
            def call(_,name,media,prompt,schema):return answer or self.answer
        folder=self.root/signature(answer or self.answer)[:10]
        return pdf.review(self.t,self.result,folder,API())

    def test_normal_two_column_order_preserves_text(self):
        old=copy.deepcopy(self.rows)
        rows,_=pdf.apply(self.t,self.result,self.rows,self.receipt())
        self.assertTrue(all(r['eligible_for_chunking'] for r in rows))
        self.assertEqual([r['observed_text'] for r in rows],['왼쪽','오른쪽']);self.assertEqual(self.rows,old)

    def test_duplicate_order_never_published(self):
        a=copy.deepcopy(self.answer);a['reading_order']=['a','a']
        rows,_=pdf.apply(self.t,self.result,self.rows,self.receipt(a))
        self.assertFalse(any(r['eligible_for_chunking'] for r in rows))

    def test_one_ambiguous_region_does_not_block_normal_sibling(self):
        a=copy.deepcopy(self.answer);a['checks'][1]['order_clear']=False
        rows,_=pdf.apply(self.t,self.result,self.rows,self.receipt(a))
        self.assertTrue(rows[0]['eligible_for_chunking']);self.assertFalse(rows[1]['eligible_for_chunking'])

    def test_short_number_omission_not_ignored(self):
        self.t['pdf_inventory']['words']=[{'text':'0','bbox':[10,10,30,30],'valid_box':True}]
        rows,checks=pdf.apply(self.t,self.result,self.rows,self.receipt())
        self.assertEqual(checks['native_unmatched'],1);self.assertFalse(rows[0]['eligible_for_chunking'])
        self.assertTrue(rows[1]['eligible_for_chunking'])

    def test_cross_page_relationship_held_not_invented(self):
        a=copy.deepcopy(self.answer);a['cross_page_uncertain']=['표가 다음 페이지로 이어짐']
        a['relations']=[{'from_id':'a','to_id':'next-page','kind':'table_continuation','supported':True}]
        rows,_=pdf.apply(self.t,self.result,self.rows,self.receipt(a))
        self.assertFalse(rows[-1]['eligible_for_chunking']);self.assertFalse(rows[-2]['eligible_for_chunking'])

    def test_missing_structure_audit_is_not_success(self):
        rows,_=pdf.apply(self.t,self.result,self.rows,None)
        self.assertFalse(any(r['eligible_for_chunking'] for r in rows))

    def test_source_changed_rejects_receipt(self):
        receipt=self.receipt();self.result['final_blocks'][0]['text']='새 원문'
        with self.assertRaisesRegex(ValueError,'source_changed'):pdf.apply(self.t,self.result,self.rows,receipt)

    def test_native_scan_and_rotated_page_coordinates(self):
        empty=pdf.native_inventory('<doc><page width="300" height="400"/></doc>')
        self.assertEqual(empty['route'],'scan_or_graphics_render')
        one=pdf.native_inventory('<doc><page width="300" height="400"><word xMin="30" yMin="40" xMax="60" yMax="80">0</word></page></doc>')
        self.assertEqual(one['words'][0]['bbox'],[100,100,200,200])


def aligned(text='가 가'):
    return {'word_segments':[{'word':w,'start':i+.1,'end':i+.9,'score':.9} for i,w in enumerate(text.split())],
            'segments':[{'chars':[{'char':c,'start':i+.1,'end':i+.9,'score':.9} for i,c in enumerate(text.replace(' ',''))]}]}


class AlignmentTests(unittest.TestCase):
    def test_real_repetition_kept(self):
        self.assertTrue(alignment.inspect_alignment('가 가',[0,2],aligned(),{'가'})['passed'])

    def test_missing_word_and_unsupported_number_fail(self):
        self.assertFalse(alignment.inspect_alignment('가 가',[0,2],aligned('가'),{'가'})['passed'])
        self.assertFalse(alignment.inspect_alignment('0',[0,2],aligned('0'),{'가'})['passed'])

    def test_timing_overlap_boundary_and_nan_fail(self):
        for start,end in [(0,3),(.2,.3),(float('nan'),2)]:
            raw=aligned();raw['word_segments'][1].update(start=start,end=end)
            self.assertFalse(alignment.inspect_alignment('가 가',[0,2],raw,{'가'})['passed'])

    def test_partial_chars_not_hidden_by_word_interpolation(self):
        raw=aligned();raw['segments'][0]['chars'][1].pop('start')
        self.assertFalse(alignment.inspect_alignment('가 가',[0,2],raw,{'가'})['passed'])

    def test_publishing_only_changes_word_times_and_keeps_text_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);records=root/'input.jsonl'
            row={'id':'a','observed_text':'가 가','eligible_for_chunking':True,'word_alignment_required':True,'words':[]}
            records.write_text(json.dumps(row)+'\n')
            job={'id':'a','text':'가 가','interval':[10,12],'offset':3}
            plan={'records':str(records),'jobs':[job],'excluded':[]}
            raw=aligned();gate=alignment.inspect_alignment(job['text'],[0,2],raw,{'가'})
            save(root/'results'/(signature('a')[:24]+'.json'),{'binding':signature({'plan':plan,'job':job}),'raw':raw,'gate':gate,'supported_chars':['가']})
            alignment.publish(root,plan)
            out=json.loads(Path(read(root/'latest.json')['records']).read_text())
            self.assertEqual(out['observed_text'],row['observed_text']);self.assertTrue(out['eligible_for_chunking'])
            self.assertAlmostEqual(out['words'][0]['start_seconds'],13.1)
            self.assertFalse(out['word_timestamps_verified']);self.assertFalse(out['word_alignment_required'])


class UnreadableInkTests(unittest.TestCase):
    def test_unreadable_to_admin_without_guessing_low_impact(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=text_package(Path(tmp),'?');p['candidate']['items'][0]['kind']='handwriting';p['base']=copy.deepcopy(p['candidate'])
            a=audit(p['candidate']);a['checks'][0].update(content='uncertain',full_text='',lexical_complete=False)
            r=route(p,evaluate(p,p['candidate'],a))
            self.assertEqual(r['decisions'][0]['status'],'administrator_review');self.assertFalse(r['changes'])
            self.assertEqual(r['administrator_queue'][0]['impact'],'unknown');self.assertFalse(r['records'])

    def test_absent_audit_and_ocr_do_not_mean_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=text_package(Path(tmp),'정상');p['candidate']['items'][0]['kind']='handwriting';p['base']=copy.deepcopy(p['candidate'])
            a=audit(p['candidate']);a['checks']=[]
            r=route(p,evaluate(p,p['candidate'],a))
            self.assertEqual(r['decisions'][0]['status'],'held');self.assertFalse(r['administrator_queue'])


if __name__=='__main__':unittest.main()
