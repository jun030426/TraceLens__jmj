"""Portable source rules and negative controls. All model calls are local fakes."""
import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from video_extraction.video import general_pixels as pixels
from video_extraction.pipeline import generalized_visual as visual,visual_gate,runner,ink_workflow
from video_extraction.ink.correction import generalized_review as ink
from video_extraction.ink.selection.usable_selection import select_result
from video_extraction.shared.common import signature,digest_file,read
from video_extraction.tests.test_correction_gate import block,result
from video_extraction.tests.test_ink_discrepancy import case,RECEIPTS


def answer(proposal):
    return dict(target_id=proposal['target_id'],text=proposal['text'],same_target=True,
                all_target_visible=True,no_neighbor_content=True,source_clear=True,
                geometry_supported=True,original_boundary_cuts_target=True,uncertainties=[])


def ink_answer(item,glyphs,kind=None,text=None):
    return dict(target_id=item['id'],literal_text=item['text'] if text is None else text,
        kind=kind or item['kind'],glyphs=glyphs,same_target=True,source_clear=True,
        not_cancelled=True,not_arrow=True,uncertainties=[])


class PortableVisualTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.image=self.root/'source.png'
        self.addCleanup(patch.stopall)
        patch('video_extraction.shared.gemini.Gemini.call',side_effect=AssertionError('external API forbidden')).start()

    def dashed(self,count=7,x=30,y=50,size=(400,200)):
        im=Image.new('RGB',size,'white');d=ImageDraw.Draw(im)
        for n in range(count):d.rectangle((x+n*10,y,x+n*10+5,y+1),fill='black')
        im.save(self.image);return im

    def guarded(self,b,a=None):
        v=result(b,a or copy.deepcopy(b));v.update(signature='fixture',image_sha256=digest_file(self.image),audit={})
        return visual_gate.enforce(v,self.image)

    def glyph(self):
        im=Image.new('RGB',(100,70),'white');ImageDraw.Draw(im).rectangle((20,20,30,36),outline='black',width=2)
        im.save(self.image);return im

    def test_count_and_position_are_discovered_on_new_sources(self):
        for count,x,y,size in [(7,30,50,(400,200)),(13,120,110,(600,300)),(19,200,240,(800,600))]:
            im=self.dashed(count,x,y,size)
            d=pixels.separator(im,block('----------'))
            self.assertEqual(d['count'],count);self.assertEqual(d['status'],'supported')
            self.assertGreaterEqual(d['roi'][0],x-2)
            guarded=self.guarded(block('----------'),block('-------------'))
            corrected=visual.run(guarded,self.image,self.root/str(count),None)
            self.assertEqual(corrected['text'],'-'*count);self.assertFalse(corrected['holds'])
            visual.verify(corrected,self.image)

    def test_normal_count_is_not_rewritten(self):
        self.dashed(7);g=self.guarded(block('-------'))
        fixed=visual.run(g,self.image,self.root/'r',None)
        self.assertEqual(fixed['corrections'],[]);self.assertFalse(fixed['holds'])

    def test_blank_solid_competing_rows_and_color_are_not_answers(self):
        for kind in ['blank','solid','two_runs','two_lines','red']:
            im=Image.new('RGB',(400,200),'white');d=ImageDraw.Draw(im)
            if kind=='solid':d.rectangle((20,50,150,52),fill='black')
            if kind in ('two_runs','two_lines','red'):
                for n in range(7):d.rectangle((20+n*10,50,25+n*10,51),fill='red' if kind=='red' else 'black')
            if kind=='two_runs':
                for n in range(7):d.rectangle((200+n*10,50,205+n*10,51),fill='black')
            if kind=='two_lines':d.rectangle((20,90,28,99),fill='black')
            self.assertNotEqual(pixels.separator(im,block('----------'))['status'],'supported',kind)

    def test_bbox_candidate_requires_two_target_reads_and_preserves_other_holds(self):
        im=self.glyph();b=block('x','text',[250,142,500,715]);g=self.guarded(b)
        e=visual.discover(g,self.image);p=next(p for p in e['proposals'] if p['field']=='bbox')
        no=visual.apply(g,self.image,e,{})
        self.assertEqual(no['final_blocks'][0]['bbox'],b['bbox']);self.assertTrue(no['holds'])
        yes=visual.apply(g,self.image,e,{signature(p):[answer(p),answer(p)]})
        self.assertNotEqual(yes['final_blocks'][0]['bbox'],b['bbox']);self.assertFalse(yes['holds'])
        visual.verify(yes,self.image)
        g['holds'].append({'target_id':'b','reason':'content_unresolved'})
        # Rebuild guard instead of manufacturing an approved receipt.
        v=result(b,b);v.update(signature='fixture',image_sha256=digest_file(self.image),audit={},holds=[{'target_id':'b','reason':'content_unresolved'}])
        g=visual_gate.enforce(v,self.image);e=visual.discover(g,self.image);p=e['proposals'][0]
        yes=visual.apply(g,self.image,e,{signature(p):[answer(p),answer(p)]})
        self.assertIn({'target_id':'b','reason':'content_unresolved'},yes['holds'])

    def test_wrong_text_target_indentation_or_neighbor_rejects_bbox(self):
        p={'target_id':'new','text':'    f(x)'}
        for field,val in [('text','f(x)'),('text','    g(x)'),('same_target',False),('original_boundary_cuts_target',False),('no_neighbor_content',False),('target_id','elsewhere')]:
            a=answer(p);a[field]=val
            self.assertFalse(visual.review_ok(p,[answer(p),a]))
        self.assertFalse(visual.review_ok(p,[answer(p)]))

    def test_confirmed_false_positive_retains_original_without_edit(self):
        self.glyph();b=block('x','text',[250,142,500,715]);g=self.guarded(b)
        e=visual.discover(g,self.image);p=e['proposals'][0];a=answer(p);a['original_boundary_cuts_target']=False
        out=visual.apply(g,self.image,e,{signature(p):[a,a]})
        self.assertFalse(out['holds']);self.assertFalse(out['corrections']);self.assertEqual(out['final_blocks'][0]['bbox'],b['bbox'])
        self.assertTrue(out['generalized_source_repair']['decisions'][0]['retained_original'])
        visual.verify(out,self.image)

    def test_normal_tight_region_and_table_rule_not_expanded(self):
        im=self.glyph()
        self.assertEqual(pixels.bounds(im,block('x','text',[200,285,310,529]),[])['status'],'not_applicable')
        d=ImageDraw.Draw(im);d.line((0,40,99,40),fill='black',width=2)
        self.assertEqual(pixels.bounds(im,block('x','text',[100,100,810,586]),[])['status'],'not_applicable')

    def test_neighbor_intersection_is_held(self):
        im=self.glyph();b=block('x','text',[250,142,500,715]);n=block('neighbor','text',[170,200,220,600]);n['id']='n'
        self.assertEqual(pixels.bounds(im,b,[b,n])['reason'],'expansion_intersects_neighbor')

    def test_source_and_result_tampering_rejected(self):
        self.dashed();g=self.guarded(block('----------'));r=visual.run(g,self.image,self.root/'r',None)
        r['final_blocks'][0]['text']='invented'
        with self.assertRaises(ValueError):visual.verify(r,self.image)
        r=visual.run(g,self.image,self.root/'r2',None);self.dashed(8)
        with self.assertRaises(ValueError):visual.verify(r,self.image)

    def test_common_entrypoint_uses_portable_rules_for_all_visual_types(self):
        self.dashed()
        v=result(block('----------'),block('-------------'));v.update(signature='fixture',image_sha256=digest_file(self.image),audit={})
        for kind in ('ppt','pdf','image','video'):
            t=dict(id='new:'+kind,unit_key=kind,source_id='new-source',source_file=str(self.image),source_kind=kind,
                   modality='visual',image=str(self.image),time_seconds=0,dimensions=[400,200],location={'page':1})
            r=runner.process_visual(self.root,{'config':{'region_budget':20}},t,None,[],candidate=copy.deepcopy(v))
            self.assertEqual(r['records'][0]['observed_text'],'-------');self.assertTrue(r['records'][0]['eligible_for_chunking'])

    def test_actual_separator_errors_and_62_coordinate_cases_are_evaluated_without_reusing_answers(self):
        from video_extraction._layout import PROJECT_ROOT
        supported=[]
        for fid in ('frame-00030','frame-00031','frame-00032'):
            old=read(PROJECT_ROOT/'outputs/vision-layer-followup/before-pixel-review/vision'/fid/'result.json')
            with Image.open(PROJECT_ROOT/'outputs/vision-layer-followup/frames'/(fid+'.png')) as im:
                for b in old['final_blocks']:
                    d=pixels.separator(im,b)
                    if d['status']=='supported':supported.append(d['count'])
        self.assertEqual(supported,[16]*4)
        cases=read(PROJECT_ROOT/'outputs/cutoff-source-review/decisions.json')
        false_positives=0;candidates=0
        for c in cases:
            original=read(c['result']);blocks=original['final_blocks']+original.get('visuals',[])
            b=copy.deepcopy(next(x for x in blocks if x['id']==c['target_id']));b['bbox']=c['before']
            frozen=copy.deepcopy(b)
            if c['kind'] in ('text','heading','code','output'):
                with Image.open(c['image']) as im:d=pixels.bounds(im,b,blocks)
                if d['status']=='candidate':
                    candidates+=1
                    proposal=dict(target_id=b['id'],text=b['text'])
                    self.assertFalse(visual.review_ok(proposal,[]))
                    if c['decision']=='false_positive':
                        no=answer(proposal);no['original_boundary_cuts_target']=False
                        self.assertFalse(visual.review_ok(proposal,[no,no]))
            false_positives+=c['decision']=='false_positive'
            self.assertEqual(b,frozen)
        self.assertEqual(len(cases),62);self.assertEqual(false_positives,9);self.assertGreater(candidates,0)

    def test_interrupted_recheck_reuses_first_answer(self):
        self.glyph();g=self.guarded(block('x','text',[250,142,500,715]));p=visual.discover(g,self.image)['proposals'][0]
        class Client:
            calls=0
            def call(self,*args):
                self.calls+=1
                if self.calls==2:raise RuntimeError('budget exhausted')
                return answer(p)
        c=Client()
        with self.assertRaisesRegex(RuntimeError,'budget'):visual.run(g,self.image,self.root/'cache',c)
        r=visual.run(g,self.image,self.root/'cache',c)
        self.assertEqual(c.calls,3);self.assertFalse(r['holds'])
        self.assertEqual(visual.run(g,self.image,self.root/'cache',c),r);self.assertEqual(c.calls,3)


class PortableInkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch('video_extraction.shared.gemini.Gemini.call',side_effect=AssertionError('API forbidden')).start()

    def colon(self):
        p,r,_=case('frame-00094-ink-001');t=ink.tasks(p,r)[0];item=t['item']
        a=ink_answer(item,[dict(kind='colon',start=5,end=6,bbox=[586,214,590,233])])
        return p,r,t,a

    def test_actual_colon_pixels_can_release_only_ocr_conflict_without_text_change(self):
        p,r,t,a=self.colon();self.assertEqual(ink.decision(p,r,t,[a,a])['action'],'ocr_punctuation_false_positive')
        receipt={'binding':ink.binding(p,r),'answers':{t['id']:[a,a]}}
        updated=ink.apply(p,r,receipt)
        self.assertEqual(updated['candidate'],r['candidate'])
        self.assertEqual(next(d for d in updated['decisions'] if d['id']==t['id'])['status'],'source_review_checked')
        good,bad=select_result(updated,self.root/'result.json')
        self.assertTrue({t['id'],'link_5'}<={x['local_id'] for x in good},[(x['local_id'],x['reasons']) for x in bad])

    def test_colon_release_replayed_through_common_ink_entrypoint(self):
        p,r,t,a=self.colon()
        # The fixture is an old source audit; common replay recomputes calculations.
        baseline=ink_workflow.replay(p,r)
        baseline.pop('generalized_ink_evidence',None)
        receipt={'binding':ink.binding(p,baseline),'answers':{t['id']:[a,a]}}
        got=ink_workflow.replay(p,{**r,'generalized_ink_evidence':receipt})
        self.assertEqual(next(d for d in got['decisions'] if d['id']==t['id'])['status'],'source_review_checked')

    def test_mismatched_readings_source_or_other_error_never_released(self):
        p,r,t,a=self.colon();b=copy.deepcopy(a);b['literal_text']='다른 단어'
        self.assertIsNone(ink.decision(p,r,t,[a,b]));self.assertIsNone(ink.decision(p,r,t,[]))
        t['reasons'].append('missing_word');self.assertIsNone(ink.decision(p,r,t,[a,a]));self.assertFalse(ink.tasks(p,r))
        with self.assertRaisesRegex(ValueError,'source_changed'):ink.apply(p,r,{'binding':'old','answers':{}})

    def test_new_source_resized_moved_colon_and_normal_control(self):
        p,r,t,a=self.colon();im=Image.new('RGB',(1000,1000),'white');d=ImageDraw.Draw(im)
        d.rectangle((802,504,804,506),fill='black');d.rectangle((802,510,804,512),fill='black')
        image=self.root/'new.png';im.save(image)
        p['view']=dict(path=str(image),size=[1000,1000],crop_in_source=[0,0,1,1]);p['task']['evidence']['selected_frame']=str(image)
        t['item']['box']=dict(left=600,top=490,right=820,bottom=530)
        p['ocr']['words']=[dict(text='"김민수".',bbox_pixels=[610,499,806,520],score=.99)]
        a['glyphs'][0]['bbox']=[800,500,808,516]
        self.assertIsNotNone(ink.decision(p,r,t,[a,a]))
        r['decisions'][next(i for i,x in enumerate(r['decisions']) if x['id']==t['id'])]['status']='source_review_checked'
        self.assertFalse(ink.tasks(p,r))

    def test_period_zero_o_and_lexical_mismatch_not_silently_corrected(self):
        p,r,t,a=self.colon();im=Image.open(p['view']['path']).copy();ImageDraw.Draw(im).rectangle((750,154,756,161),fill='white')
        image=self.root/'period.png';im.save(image);p['view']['path']=str(image)
        self.assertIsNone(ink.decision(p,r,t,[a,a]))
        p,r,t,a=self.colon()
        for text in ['"김민서".','"김민수0".','"김민수o".']:
            p['ocr']['words']=[dict(text=text,bbox_pixels=[675,152,755,168],score=.99)]
            self.assertIsNone(ink.decision(p,r,t,[a,a]))

    def test_all_legacy_discrepancies_get_new_source_tasks_without_manual_approvals(self):
        total=0
        for tid in read(RECEIPTS):
            p,r,rec=case(tid);ts=ink.tasks(p,r);total+=len(ts)
            self.assertEqual({t['id'] for t in ts},{e['id'] for e in rec['entries']})
            receipt=ink.review(p,r,self.root/tid,None)
            self.assertFalse(receipt['historical_manual_approvals_used'])
            unchanged=ink.apply(p,r,receipt)
            self.assertEqual(unchanged['candidate'],r['candidate'])
            self.assertEqual([(d['id'],d['status'],d['reasons']) for d in unchanged['decisions']],[(d['id'],d['status'],d['reasons']) for d in r['decisions']])
        self.assertEqual(total,3) # Three source items plus their two dependent links = old five cases.

    def test_real_bracket_is_observation_only_with_new_source_readings(self):
        p,r,_=case('frame-00007-ink-001');t=ink.tasks(p,r)[0]
        a=ink_answer(t['item'],[dict(kind='bracket',start=0,end=0,bbox=[390,420,610,590])],kind='bracket',text='')
        d=ink.decision(p,r,t,[a,a])
        self.assertEqual(d['action'],'bracket_shape_admin');self.assertIsNone(d['meaning'])

    def test_each_punctuation_difference_requires_its_own_pixel_evidence(self):
        p,r,t,a=self.colon();im=Image.new('RGB',(1000,200),'white');d=ImageDraw.Draw(im)
        for x in (100,200):
            d.arc((x,40,x+9,65),90,270,fill='black',width=2)
            d.arc((x+10,40,x+19,65),270,90,fill='black',width=2)
        image=self.root/'two-pairs.png';im.save(image)
        p['view']=dict(path=str(image),size=[1000,200],crop_in_source=[0,0,1,1])
        t['item'].update(text='f(), g()',box=dict(left=50,top=100,right=300,bottom=500))
        p['ocr']['words']=[dict(text='fO, gO',bbox_pixels=[60,30,250,80],score=.99)]
        glyphs=[dict(kind='parentheses_pair',start=1,end=3,bbox=[98,190,122,340]),
                dict(kind='parentheses_pair',start=6,end=8,bbox=[198,190,222,340])]
        a=ink_answer(t['item'],glyphs)
        self.assertIsNotNone(ink.decision(p,r,t,[a,a]))
        b=copy.deepcopy(a);b['glyphs']=b['glyphs'][:1]
        self.assertIsNone(ink.decision(p,r,t,[b,b]))
        b=copy.deepcopy(a);b['glyphs'][1]['bbox']=b['glyphs'][0]['bbox']
        self.assertIsNone(ink.decision(p,r,t,[b,b]))

    def test_bracket_shape_admin_keeps_uncertain_meaning_and_blocks_links(self):
        p,r,_=case('frame-00007-ink-001');t=ink.tasks(p,r)[0]
        a=ink_answer(t['item'],[dict(kind='bracket',start=0,end=0,bbox=[405,420,610,580])],kind='bracket',text='')
        # New clear source fixture; geometry is current-source, never old approval.
        im=Image.new('RGB',(1000,1000),'white');d=ImageDraw.Draw(im)
        d.line([(590,450),(430,450),(430,550),(590,550)],fill='red',width=4)
        image=self.root/'bracket.png';im.save(image);p['view']=dict(path=str(image),size=[1000,1000],crop_in_source=[0,0,1,1])
        t['item']['box']=dict(left=400,top=400,right=620,bottom=590)
        receipt=dict(binding=ink.binding(p,r),answers={t['id']:[a,a]})
        updated=ink.apply(p,r,receipt)
        self.assertEqual(updated['candidate']['items'][0]['kind'],'bracket')
        self.assertEqual(updated['candidate']['items'][0]['text'],'')
        self.assertEqual(updated['administrator_queue'][-1]['impact'],'unknown')
        self.assertIsNone(updated['administrator_queue'][-1]['meaning'])
        good,_=select_result(updated,self.root/'r.json',{t['id']});self.assertNotIn(t['id'],[x['local_id'] for x in good])
        d.ellipse((430,450,590,550),outline='red',width=5);im.save(image)
        self.assertFalse(ink.bracket_pixels(image,[405,420,610,580]))


if __name__=='__main__':unittest.main()
