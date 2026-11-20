"""Build a source-bound assistant reference draft, never an automatic gold label.

Only reads the blank sampling manifest, manually authored labels and original
pixels. Deliberately does not load predictions.json or existing transcriptions.
"""
from video_extraction._layout import source_path
import argparse
import copy
import html
import json
import re
from pathlib import Path

from PIL import Image

from video_extraction.shared.common import digest_file, now, read, save
from video_extraction.shared.preprocessing import checked
from video_extraction.video.separator_pixels import count_dashes


def region(rid, kind, box, text, size=(1280, 720), **extra):
    x1, y1, x2, y2 = box
    w, h = size
    if not 0 <= x1 < x2 <= w or not 0 <= y1 < y2 <= h:
        raise ValueError('invalid_reference_box:' + rid)
    return {'id': rid, 'kind': kind, 'bbox_pixels': box,
            'bbox': [round(x1/w*1000), round(y1/h*1000), round(x2/w*1000), round(y2/h*1000)],
            'coordinate_system': 'xyxy_0_1000', 'geometry_status': 'coarse_manual_not_gold',
            'literal_text': text, 'status': 'assistant_draft', **extra}


def validate_draft(draft):
    ids = [f['id'] for f in draft['frames']]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate_frame')
    for f in draft['frames']:
        regions = {r['id']: r for r in f['reference_regions']}
        if len(regions) != len(f['reference_regions']):
            raise ValueError('duplicate_reference_region')
        ambiguities = {(a['region_id'], a['id']) for a in f['ambiguous_regions']}
        for r in regions.values():
            markers = re.findall(r'⟦([^⟧]+)⟧', r['literal_text'] or '')
            if any((r['id'], m) not in ambiguities for m in markers):
                raise ValueError('untracked_ambiguity_marker')
        if f['gold_approved'] or f['annotation_status'] != 'assistant_source_reviewed_pending_adjudication':
            raise ValueError('draft_cannot_be_gold')
    for clip in draft['audio']:
        if clip['reference_text_verbatim'] is not None or clip['reviewer'] is not None:
            raise ValueError('unheard_audio_cannot_be_labeled')


def render(draft):
    cards = []
    for f in draft['frames']:
        cards.append('<article><h2>%s · %.1f초</h2><p>화면 원본 검토 초안 · 2차 검토 전</p><img src="%s" alt="원본 화면">' %
                     (html.escape(f['id']), f['time_seconds'], html.escape(Path(f['image_path']).as_uri(), quote=True)))
        for r in f['reference_regions']:
            cards.append('<details><summary>%s · %s</summary><pre>%s</pre></details>' %
                         (html.escape(r['id']), html.escape(r['kind']),
                          html.escape(r.get('literal_text') if r.get('literal_text') is not None else '문자 판독 보류')))
            if r.get('description'):
                cards.append('<p class="note">'+html.escape(r['description'])+'</p>')
        if f['ambiguous_regions']:
            cards.append('<p class="hold">보류: '+html.escape('; '.join(a['id']+': '+a['reason'] for a in f['ambiguous_regions']))+'</p>')
        cards.append('</article>')
    audio_cards = []
    for i, clip in enumerate(draft['audio']):
        audio_cards.append('<article><h2>%s · %.2f–%.2f초</h2><audio controls preload="none" src="%s"></audio>'
                           '<p>원음을 듣고 그대로 작성하세요. 모호한 부분은 [불명료]로 남기세요.</p>'
                           '<textarea data-audio="%d" placeholder="아직 청취·전사되지 않았습니다"></textarea></article>' %
                           (html.escape(clip['id']), clip['start_seconds'], clip['end_seconds'],
                            html.escape(Path(clip['audio_path']).as_uri(), quote=True), i))
    # Embed only this reference draft, never machine predictions.
    data = json.dumps(draft, ensure_ascii=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>원본 대조 정답 초안</title>
<style>body{font-family:system-ui;max-width:1120px;margin:28px auto;padding:0 18px;background:#f4f6f8;color:#152135}
article{background:white;border-radius:12px;padding:20px;margin:22px 0}img{max-width:100%}pre{white-space:pre-wrap;line-height:1.6}
summary{cursor:pointer;padding:8px}audio,textarea{width:100%}textarea{min-height:160px;font-size:16px}button{padding:12px;cursor:pointer}
.hold{color:#8b4b00}.note{color:#526174;font-size:14px}.banner{background:#fff0cf;padding:18px;border-radius:10px}</style>
<h1>원본 대조 정답 초안</h1><div class="banner">화면 24개는 Codex가 원본을 보고 작성한 초안입니다.
독립적인 사람의 2차 검토 전이므로 최종 정답이나 정확도 인증이 아닙니다.
⟦표시⟧는 읽기 불확실한 구간입니다. 코드의 들여쓰기·공백은 화면 판독용 표기이고 원본 코드 파일의 바이트 정답이 아닙니다.
필기 위치는 대략적인 영역이며 좌표 정확도 평가에는 사용할 수 없습니다.</div>
<h2>음성 6구간 · 원음 청취 필요</h2><p>Codex가 직접 듣지 못한 음성은 정답을 비워 두었습니다.
아래에 전사를 작성한 뒤 저장 버튼을 누르면 작성한 구간만 사람 검토 초안으로 내려받습니다. 자동 저장되지 않습니다.</p>
<label>검토자 이름 <input id="reviewer" autocomplete="off"></label><button id="save">작성한 음성 전사 내려받기</button><p id="message"></p>
''' + ''.join(audio_cards) + '<h2>화면 24개 · 원본과 작성 초안</h2>' + ''.join(cards) + '''
<script type="application/json" id="data">''' + data + '''</script>
<script>
document.getElementById('save').addEventListener('click',()=>{
 const value=JSON.parse(document.getElementById('data').textContent);
 const reviewer=document.getElementById('reviewer').value.trim();
 if(!reviewer){document.getElementById('message').textContent='검토자 이름을 입력하세요.';return;}
 let changed=0;
 document.querySelectorAll('textarea[data-audio]').forEach(el=>{
   if(!el.value.trim())return;
   const c=value.audio[Number(el.dataset.audio)];
   c.reference_text_verbatim=el.value;c.reviewer=reviewer;c.reviewed_at=new Date().toISOString();
   c.annotation_status='human_transcribed_pending_adjudication';c.blocking_reason=null;changed++;
 });
 if(!changed){document.getElementById('message').textContent='전사를 작성한 구간이 없습니다.';return;}
 const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
 const a=document.createElement('a');a.href=url;a.download='references.with-audio-draft.json';a.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
 document.getElementById('message').textContent=changed+'개 구간을 포함한 검토 초안을 내려받았습니다.';
});
</script></html>'''


def build(sample_root, labels_path, output):
    sample_root, labels_path, output = map(lambda p: Path(p).resolve(), (sample_root, labels_path, output))
    if output.exists():
        raise ValueError('output_exists_choose_new_directory')
    sample_manifest = read(sample_root/'manifest.json')
    checked(sample_root/'references.blank.json', sample_manifest['output_sha256']['references.blank.json'])
    frozen_manifest_path = Path(sample_manifest['preprocessing_manifest'])
    checked(frozen_manifest_path, sample_manifest['preprocessing_manifest_sha256'])
    frozen = read(frozen_manifest_path)
    label_hash = digest_file(labels_path)
    labels = read(labels_path)
    draft = copy.deepcopy(read(sample_root/'references.blank.json'))
    frame_groups = {}
    for group in labels['groups']:
        for number in group['frames']:
            fid = 'frame-%05d' % number
            if fid in frame_groups:
                raise ValueError('duplicate_label_assignment')
            frame_groups[fid] = group
    if set(frame_groups) != {f['id'] for f in draft['frames']}:
        raise ValueError('sample_coverage_mismatch')
    created = now()
    pixel_results = []
    for f in draft['frames']:
        checked(f['image_path'], frozen['input_sha256'][f['image_path']])
        group = frame_groups[f['id']]
        f.update(annotation_status='assistant_source_reviewed_pending_adjudication',
                 reviewer=labels['author'], reviewed_at=created, gold_approved=False, is_blank=False,
                 reference_regions=[], ambiguous_regions=[], image_sha256=digest_file(f['image_path']),
                 notes=group.get('notes'), second_reviewer=None,
                 visual_elements_status='coarse_inventory_not_exhaustive_stroke_segmentation')
        with Image.open(f['image_path']) as im:
            if im.size != (1280, 720):
                raise ValueError('reference_layout_changed')
            for rid, kind, box, text in group['regions']:
                f['reference_regions'].append(region(rid, kind, box, text))
            by_id = {r['id']: r for r in f['reference_regions']}
            for rid, rows in group.get('tables', {}).items():
                by_id[rid]['rows'] = rows
            for rid, box, description in group.get('figures', []):
                f['reference_regions'].append(region(rid, 'figure', box, None, description=description,
                    literal_text_status='labels_transcribed_in_separate_text_region'))
            for aid, rid, box, candidates, reason in group.get('ambiguities', []):
                f['ambiguous_regions'].append({'id':aid, 'region_id':rid, 'bbox_pixels':box,
                    'candidates':candidates, 'reason':reason, 'status':'held', 'excluded_from_scoring':True,
                    'context_candidate':'0' if candidates==['0','o'] else None, 'candidate_applied':False})
            for aid, rid, box, thresholds in group.get('pixel_separators', []):
                check = count_dashes(im, box, thresholds)
                pixel_results.append({'frame_id':f['id'], 'region_id':rid, 'marker_id':aid,
                                      'image_sha256':f['image_sha256'], **check})
                if check['status']=='verified':
                    by_id[rid]['literal_text'] = by_id[rid]['literal_text'].replace('⟦'+aid+'⟧', check['value'])
                    f['ambiguous_regions'] = [a for a in f['ambiguous_regions']
                        if (a['id'], a['region_id']) != (aid, rid)]
                else:
                    f['ambiguous_regions'] = [a for a in f['ambiguous_regions']
                        if (a['id'], a['region_id']) != (aid, rid)]
                    f['ambiguous_regions'].append({'id':aid, 'region_id':rid, 'bbox_pixels':box,
                        'candidates':[], 'reason':'pixel_count_not_stable', 'status':'held', 'excluded_from_scoring':True})
        for rid, box, description, text in group['annotations'][str(int(f['id'].split('-')[1]))]:
            f['reference_regions'].append(region(rid, 'annotation', box, text, description=description,
                literal_text_status='held' if text is None else 'non_text_marking'))
            if text is None:
                f['ambiguous_regions'].append({'id':rid, 'region_id':rid, 'bbox_pixels':box,
                    'candidates':[], 'reason':'handwriting_unresolved', 'status':'held', 'excluded_from_scoring':True})
        f['reference_text_verbatim'] = '\n\n'.join(r['literal_text'] for r in f['reference_regions']
            if r['literal_text'] is not None and r['kind'] not in ('annotation', 'figure'))
    for clip in draft['audio']:
        relative = str(Path(clip['audio_path']).relative_to(sample_root))
        checked(clip['audio_path'], sample_manifest['output_sha256'][relative])
        clip.update(annotation_status='requires_source_listening',
                    blocking_reason='No direct audio listening/transcription input available to this assistant.',
                    gold_approved=False)
    draft.update(reference_status='assistant_draft_not_gold', created_at=created,
                 scope=labels['scope'], text_policy=labels['text_policy'], geometry_policy=labels['geometry_policy'],
                 annotation_method=labels['method'],
                 independence='Development lecture already used for prior fixes; not an independent holdout.',
                 accuracy=None, api_requests=0)
    validate_draft(draft)
    output.mkdir(parents=True, exist_ok=False)
    save(output/'references.draft.json', draft)
    save(output/'pixel-evidence.json', pixel_results)
    summary = {'created_at':created, 'frames_source_reviewed':len(draft['frames']),
        'reference_regions':sum(len(f['reference_regions']) for f in draft['frames']),
        'frames_with_ambiguities':sum(bool(f['ambiguous_regions']) for f in draft['frames']),
        'held_regions_or_spans':sum(len(f['ambiguous_regions']) for f in draft['frames']),
        'pixel_separator_checks':len(pixel_results),
        'pixel_separators_verified':sum(p['status']=='verified' for p in pixel_results),
        'audio_samples_transcribed':0, 'audio_samples_pending':len(draft['audio']),
        'audio_seconds_pending':sum(c['end_seconds']-c['start_seconds'] for c in draft['audio']),
        'gold_approved_frames':0, 'accuracy':None, 'api_requests':0,
        'next_steps':['Independent source review of assistant text drafts and ambiguous spans.',
                      'Listen to six audio clips and write references; model retranscription alone is not gold.',
                      'Finalize text/region scoring policy before computing accuracy.']}
    save(output/'summary.json', summary)
    (output/'정답초안_검토.html').write_text(render(draft), encoding='utf-8')
    checked(labels_path, label_hash)
    checked(sample_root/'references.blank.json', sample_manifest['output_sha256']['references.blank.json'])
    for f in draft['frames']:
        checked(f['image_path'], f['image_sha256'])
    save(output/'manifest.json', {'created_at':created, 'sample_manifest_sha256':digest_file(sample_root/'manifest.json'),
        'labels_path':str(labels_path), 'labels_sha256':label_hash, 'implementation_sha256':digest_file(__file__),
        'pixel_counter_sha256':digest_file(source_path('separator_pixels.py')),
        'output_sha256':{p.name:digest_file(p) for p in output.iterdir() if p.is_file()}})
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--samples', type=Path, required=True)
    p.add_argument('--labels', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.samples, a.labels, a.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
