import test from 'node:test';
import assert from 'node:assert/strict';
import {heldReason,sourceTime} from '../src/extractionReview.ts';
import {materialProgress,type Processing} from '../src/materialProcessing.ts';
import type {Material} from '../src/api.ts';
test('held evidence explains uncertainty without claiming a confirmed content error',()=>{
  assert.match(heldReason('speech_without_transcript'),/실제 누락인지는 원음을/);
  assert.equal(sourceTime(1915.8),'31:55');assert.equal(sourceTime(null),'');assert.equal(sourceTime(NaN),'');
});
test('partial publication remains searchable while making held content visible',()=>{
  const material:Material={id:'m',title:'영상',kind:'lecture',week:2,visibility:'public',internal_use:'none',revision:1,
    content_generation_mode:'weekly',version:{id:'v',filename:'lecture.mp4',status:'ready',error_code:null}};
  const processing:Processing={material_id:'m',version_id:'v',source_status:'ready',jobs:[],held_count:3,extraction_pipeline:'local-media-basic-v1'};
  const result=materialProgress(material,processing);
  assert.equal(result.tone,'held');assert.match(result.text,/정상 구간 준비.*3건 보류/);
  assert.equal(result.stages[0].tone,'ready');assert.equal(result.stages[1].tone,'ready');
});
