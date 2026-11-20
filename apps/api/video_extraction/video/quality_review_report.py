"""Render the 2026-10-19 agent visual triage without changing extraction results.

Observations are specific to the inspected 32-frame snapshot. Hash binding prevents
reusing these decisions after source results change. This is not a human accuracy
evaluation or a ground-truth transcription.
"""
from collections import Counter
import html
import json
from pathlib import Path

from video_extraction.shared.common import digest_file, now, read, save
from video_extraction.video.vision import critical
from video_extraction.video.vision_benchmark import DEFAULT_OUT, validate_frozen


FRAME_NOTES={
1:'인쇄된 제목·설명·코드·출력 순서에서 뚜렷한 누락을 찾지 못함. 글자 단위 정답 인증은 아님.',
2:'주요 인쇄 내용 유지. 강의와 무관한 Windows 정품 인증 문구가 추출에 섞임.',
3:'자료형 밑줄은 실제 강조선. 잘린 글자를 별도 단어로 읽은 재판독을 거절한 것은 타당함.',
4:'자동 통과했지만 붉은 원·밑줄이 결과에 기록되지 않음. 기존 방식에도 같은 종류 누락이 있음.',
5:'자동 통과했지만 리스트 숫자 강조, 변환 흐름 화살표와 밑줄이 기록되지 않음. 기존 방식도 유사함.',
6:'자동 통과한 필기 전사 set 정렬은 원본 획만으로 확정하기 어려움. 이전 방식의 판독도 달라 별도 보류 필요.',
7:'코드 본문은 유지되나 필기와 강조선이 부분적으로 빠짐. 왼쪽 아래 필기 순서 결과는 확정 불가.',
8:'필기 전체를 하나의 포괄적 설명으로 합침. 순서 제거 등 필기 판독과 개별 대상 관계는 확정 불가.',
9:'코드·출력 본문 유지. 필기 객체/집합과 set 정의는 정확한 글자 및 강조 관계를 더 확인해야 함.',
10:'인쇄된 표의 4개 행을 확인. 내용 대응에서 뚜렷한 누락을 찾지 못함. Windows 워터마크 혼입.',
11:'표 내용 유지. 정제 뒤 화살표 다음 필기는 판독 불확실. min을 확정 전사로 사용하면 안 됨.',
12:'표 내용 유지. 화살표 뒤 필기 불확실성을 유지해야 함. 표의 실제 원·밑줄도 별도 시각 정보임.',
13:'표 내용 유지. 필기 처리라는 판독을 확정할 근거 부족. 강조선과 원의 대상 기록도 불완전.',
14:'표 내용 유지. 불명확한 필기 보류 타당. 합집합·교집합·차집합·공통 등의 강조 표시 보존 필요.',
15:'자동 통과했지만 객체(Object)의 개념 제목이 제목 블록과 그림 블록에서 중복됨. 자동차 연결 관계는 별도 보존 필요.',
16:'빈 b5는 글자가 없는 자동차 그림. NEW 표적 아이콘도 무문자 그림. b4는 붉은 테두리를 설명하지 않고 b2/b3 본문을 중복함.',
17:'잘린 제목 개념을 자동차 블록에 섞는 재판독 거절은 타당. 붉은 체크·밑줄과 그림 연결 정보는 여전히 불완전.',
18:'잘린 제목을 넣지 않은 것은 타당. 그림/필기를 본문과 분리하고 검토 예산 밖 3개 영역을 추적해야 함.',
19:'원본에 붉은 밑줄과 원이 존재. 그림과 필기 관계가 본문 재전사로 대체됨. 일부 작은 글자의 표시 상태도 주의.',
20:'본문과 겹친 붉은 숫자·원·밑줄을 중복으로 취급함. 화면에 실제 존재하는 시각 정보는 별도로 기록해야 함.',
21:'새 필기 6개가 검토 상한을 점유. 상한 밖 12개 후보에 중요 코드/표가 포함되는지 후속 검토 필요.',
22:'리스트의 아이콘은 문서 그림이며 []라고 읽으면 안 됨. 집합 아이콘은 겹친 원. 일부 글자가 불완전하게 보이는 구간의 자동 완성도 추가 확인 필요.',
23:'본문 위에 겹친 필기 6개를 중복으로 막음. 실제 강조 표시의 대상·종류가 보존되지 않음.',
24:'리스트·튜플·딕셔너리와 표의 붉은 표시가 실제 존재. 본문 중복 방지와 별개로 필기 레이어 보존 필요.',
25:'필기 검토가 예산을 점유하고 9개 후보가 뒤로 밀림. 본문 위 강조와 자동차 그림의 역할을 분리해야 함.',
26:'집합 설명 재판독 영역이 문장 끝을 자름. 원·밑줄과 본문을 각각 검토하고 필요한 전체 문맥으로 다시 잘라야 함.',
27:'Windows 정품 인증은 강의 내용이 아닌 화면 오버레이. 이를 읽으려는 요청은 내용 검토 예산을 낭비함.',
28:'상한 밖 후보 5개가 있음. 빨간 원으로 묶은 집합 메서드와 하단 표 강조가 추출에 충분히 표현되지 않음.',
29:'표의 딕셔너리(Dictionary)에서 (Dictionary)가 빠짐. 같은 표의 두 지적이 모두 중복 타깃으로 배제됨. 집합의 값(value)로 접근은 원본에도 있으므로 개념적으로 고치지 않아야 함.',
30:'주요 코드·결과는 유지되나 자동 통과 상태만으로 0/o와 구분선 개수를 확정할 수 없음. 31/32와 판정도 일관되지 않음.',
31:'0/o의 모양이 작아 소문자 o라는 검증기 주장을 확정하지 않음. 출력 공백을 바꾸지 않은 거절은 타당. 구분선 개수는 추가 확인.',
32:'붉은 필기 요약은 포함. 코드 0/o는 원본 모양을 더 확인해야 함. 출력 구분선 수가 인접 화면 결과와 달라 그대로 승인하지 않음.',
}

CATEGORIES={
 'budget':'검토 상한 밖 후보',
 'annotation_overlap':'본문 위 필기·강조 정보 미보존',
 'unclear_handwriting':'불명확한 필기',
 'textless_graphic':'글자 없는 그림·아이콘',
 'crop_context':'잘린 영역·다른 블록 혼입',
 'false_text_change':'본문 변경이 불필요하거나 근거 부족',
 'nonlesson_overlay':'강의 외 화면 오버레이',
 'confirmed_omission':'확인된 텍스트 누락',
 'source_fidelity':'원본 기호·공백 확인 필요',
}

# Hold indices are zero-based in each immutable result.json.
SPECIFIC={
 (3,0):('false_text_change','자료형 밑줄은 텍스트가 아닌 강조선. 지표성이라는 제안은 채택하지 않음.'),
 (7,1):('annotation_overlap','독립 판독이 필기 표시 대신 인쇄 코드만 반환함.'),
 (7,2):('annotation_overlap','집합 필기와 중괄호 강조가 실제 존재. 코드 재전사만으로 충족되지 않음.'),
 (7,3):('unclear_handwriting','왼쪽 코드 아래 필기는 확정 불가. 순서 결과나 set 생성 중 하나를 추측해 채택하지 않음.'),
 (8,0):('unclear_handwriting','추출·감사·기존 결과의 판독이 서로 다름. 중복 처리만으로 필기 문제가 해결되지 않음.'),
 (9,0):('unclear_handwriting','오른쪽 코드 위 붉은 필기와 인쇄 코드가 혼재. 잘못된 영역 판독을 거절한 상태 유지.'),
 (16,1):('textless_graphic','학습 목표 옆 과녁과 화살은 글자가 없는 그림. 빈 전사는 글자 누락의 증거가 아님.'),
 (16,2):('textless_graphic','b5 경계는 파란 자동차 그림. 옆의 속성/동작 글자는 다른 블록으로 존재함.'),
 (16,3):('textless_graphic','같은 자동차 그림을 빈 텍스트로 다시 보류한 항목. 독립된 두 번째 누락은 아님.'),
 (17,0):('crop_context','잘린 제목 개념을 그림 본문에 넣으려는 제안을 거절. 그림의 연결 관계는 따로 기록해야 함.'),
 (18,1):('crop_context','동일하게 제목 조각 혼입. 거절 유지; 붉은 체크/밑줄은 별도 시각 정보.'),
 (19,1):('crop_context','제목 조각과 그림/필기의 혼합 문제. 원본 영역별 내용을 분리해야 함.'),
 (21,2):('crop_context','속성 제목 윗부분이 잘린 재판독. 붉은 표시만 좁게 자르면 본문이 잘림.'),
 (21,3):('crop_context','문장 끝이 잘린 재판독. 문장의 전체 블록과 강조 영역을 함께 참조해야 함.'),
 (22,0):('textless_graphic','리스트 제목 옆은 목록 모양 아이콘. []라는 문자를 누락했다고 단정하지 않음.'),
 (22,1):('textless_graphic','집합 제목 옆의 겹친 원 아이콘. 글자가 아닌 시각 객체로 보존할 항목.'),
 (22,2):('annotation_overlap','원/숫자 필기 대신 자동차 속성 등 다른 본문까지 읽음. 거절 유지.'),
 (26,5):('crop_context','집합 설명의 문장 끝이 잘린 상태. 잘린 판독으로 원문을 바꾸지 않음.'),
 (27,1):('nonlesson_overlay','Windows 정품 인증 오버레이. 강의 텍스트 검토에서 제외할 수 있으나 겹친 강의 글자는 보존해야 함.'),
 (29,0):('confirmed_omission','표 첫 열의 (Dictionary)가 원본에는 있으나 개선 추출에는 없음. 기존 결과에는 있음.'),
 (29,1):('false_text_change','원본 표에도 값(value)로 접근이라고 인쇄됨. 직접 접근 불가로 고치는 제안은 전사 목적에 맞지 않음.'),
 (29,2):('false_text_change','표의 주요 내용은 일치. [] 내부 공백 차이를 위해 재작성할 필요는 확인되지 않음.'),
 (29,3):('false_text_change','선택 가이드의 글자와 표지판 라벨은 유지됨. 별도 필기 강조는 보존할 필요가 있음.'),
 (31,0):('source_fidelity','작은 0/o 글꼴을 모델 주장만으로 확정하지 않음. 원본 오타를 의미로 교정하지 않는 원칙 유지.'),
 (31,1):('source_fidelity','이름 뒤 콜론 앞 공백을 지운 제안 거절은 타당. 구분선 정확한 개수는 별도 확인.'),
 (32,0):('source_fidelity','0/o와 구분선 개수 확인 필요. 인접 화면의 추출을 정답으로 간주하지 않음.'),
}


def classify(number,index,hold):
    if (number,index) in SPECIFIC:return SPECIFIC[number,index]
    reason=hold['reason']
    if reason=='region_budget':return 'budget',f"상한 때문에 후보 {hold['remaining']}개가 처리되지 않음. 후보 수이며 실제 오류 수가 아님."
    if reason=='remaining_uncertainty' or number in (11,12,13,14) and reason=='verification_hold':
        return 'unclear_handwriting','원본의 흘려 쓴 필기를 확정할 근거가 부족함. 추정 단어를 정답으로 채택하지 않음.'
    if reason=='duplicate_addition':
        return 'annotation_overlap','원본에 표시가 존재함. 본문과 겹친다는 이유로 추가가 거절되었지만 필기 보존 문제가 해결된 것은 아님.'
    raise ValueError(f'unclassified_hold:{number}:{index}:{reason}')


def deferred(result,max_regions):
    regions=list(result['audit']['regions']);targeted={r['target_id'] for r in regions}
    reused={r['target_id'] for r in result.get('reuse',[])}
    for b in result['original']['blocks']:
        if critical(b) and b['id'] not in targeted and b['id'] not in reused:
            regions.append({'target_id':b['id'],'bbox':b['bbox'],'kind':b['kind'],
                            'issue':'uncertain','reason':'critical_content_policy'})
    return regions[max_regions:]


def build(out=DEFAULT_OUT):
    out=Path(out);manifest=read(out/'manifest.json');validate_frozen(out,manifest)
    selected=manifest['selected_ids']
    if selected!=[f'frame-{i:05}' for i in range(1,33)]:raise ValueError('review_snapshot_requires_frames_1_to_32')
    dest=out/'quality-review';binding_path=dest/'input-hashes.json'
    inputs=[out/'manifest.json',out/'baseline/results.json',out/'run-state.json',out/'local-comparison.json',out/'comparison.json']
    inputs+=sorted((out/'optimized/vision').glob('*/result.json'))
    inputs+=sorted((out/'optimized/api-cache').glob('*.json'))
    hashes={str(p.relative_to(out)):digest_file(p) for p in inputs}
    if binding_path.exists() and read(binding_path)!=hashes:raise ValueError('review_inputs_changed_reinspect_before_rebinding')
    baseline=read(out/'baseline/results.json');state=read(out/'run-state.json');local=read(out/'local-comparison.json')
    comparison=read(out/'comparison.json');frames=[];holds=[]
    for n,fid in enumerate(selected,1):
        r=read(out/'optimized/vision'/fid/'result.json');pending=deferred(r,manifest['max_regions'])
        expected=sum(h['remaining'] for h in r['holds'] if h['reason']=='region_budget')
        if len(pending)!=expected:raise ValueError('deferred_reconstruction_changed:'+fid)
        frame={'frame_id':fid,'time_seconds':r['frame_time_seconds'],'status':r['status'],
               'notes':FRAME_NOTES[n],'deferred_regions':pending,'hold_count':len(r['holds']),
               'image_sha256':manifest['frame_sha256'][fid]}
        frames.append(frame)
        for index,h in enumerate(r['holds']):
            category,note=classify(n,index,h)
            holds.append({'review_id':f'{fid}/hold-{index}','frame_id':fid,'hold_index':index,
                          'category':category,'review_note':note,'original_hold':h,
                          'original_hold_retained':True})
    successful=[read(p) for p in (out/'optimized/api-cache').glob('*.json') if 'parsed' in read(p)]
    old_calls=local['old_successful_calls'];new_calls=len(successful)
    metrics={'baseline_successful_calls':old_calls,'optimized_successful_calls':new_calls,
             'successful_call_reduction_percent':round(100*(1-new_calls/old_calls),2),
             'optimized_request_attempts':sum(r['api']['requests'] for r in state['runs']),
             'optimized_active_seconds':state['active_elapsed_seconds'],
             'baseline_recorded_response_seconds':local['old_recorded_response_seconds'],
             'optimized_recorded_response_seconds':sum(c['seconds'] for c in successful),
             'baseline_reconstructed_paced_seconds':local['old_paced_schedule_seconds'],
             'wall_time_speedup_claim':None,
             'time_limit':'개선 실행 누적 시간은 실측. 기존 32개 동일 표본의 총 경과시간은 직접 측정값이 없어 속도 향상률을 확정하지 않음.',
             'stages':dict(Counter(c['stage'] for c in successful))}
    findings=[
      {'id':'F1','title':'무문자 그림과 빈 전사를 구분해야 함','frames':[16,22],
       'evidence':'16번 b5는 자동차, NEW 영역은 과녁 그림. 22번은 목록 아이콘과 겹친 원.',
       'action':'텍스트 판독과 그림 설명·연결 관계를 별도 필드로 보존. 빈 문자열만으로 그림을 오류나 삭제 대상으로 판단하지 않기.'},
      {'id':'F2','title':'필기 재판독이 본문 중복으로 바뀜','frames':[16,20,21,23,24,25,26],
       'evidence':'16번 b4에 기존 b2/b3 본문이 반복됨. 중복 추가 거절 29건에는 실제 원·밑줄 영역이 다수 포함됨.',
       'action':'필기 종류·대상 블록·좌표·판독 가능한 필기 글자를 별도로 저장. 본문을 재전사해 필기를 대신하지 않기.'},
      {'id':'F3','title':'같은 표의 두 지적이 모두 배제됨','frames':[29],
       'evidence':'b-summary-table 두 지적이 invalid_or_duplicate_target으로 제외. (Dictionary) 누락은 기존 결과에는 없던 회귀.',
       'action':'동일 타깃의 지적을 하나의 전체 블록 검토로 합치되 각 지적을 보존. 내용 교정은 원본 대조 후에만 적용.'},
      {'id':'F4','title':'상한 밖 후보 61개가 별도 목록 없이 남음','frames':[7,16,18,19,21,23,24,25,26,27,28],
       'evidence':'11개 region_budget 항목의 remaining 합계는 61. 본 보고서 JSON에는 해당 후보 목록을 재구성함.',
       'action':'보류된 개별 영역을 체크포인트로 저장하고 코드·표·불확실한 글자와 그림/필기 예산을 분리해 후속 처리.'},
      {'id':'F5','title':'자동 통과가 전체 정보 보존을 뜻하지 않음','frames':[4,5,6,15,30],
       'evidence':'4/5번 강조 표시 누락, 6번 불명확한 필기 단정, 15번 제목 중복, 30번의 코드 기호 판정 불일치.',
       'action':'자동 통과 표본도 원본 대조 대상에 포함. 필기 누락·중복·기호를 참조 검사에 추가.'},
      {'id':'F6','title':'검증기가 제안한 의미 교정을 따라가면 안 됨','frames':[29,31,32],
       'evidence':'29번 표의 값(value)로 접근은 실제 원본에도 있음. 31/32의 0/o 구분은 작은 글꼴만으로 확정하지 않음.',
       'action':'확인된 원본 문구를 개념적으로 고치지 말고, 기호가 불명확하면 원본 이미지와 불확실성을 함께 보존.'},
    ]
    report={'created_at':now(),'review_type':'agent_visual_triage','human_review':False,
            'scope':'32개 원본 전체 화면을 열어 확인하고 75개 보류 항목을 분류. 모든 글자·그림 관계의 독립 정답 검증은 아님.',
            'decision':'hold_full_115_frame_rollout','decision_reason':'그림/필기 처리와 표 재판독의 구조적 결함 및 확인된 누락이 남음.',
            'production_results_modified':False,'new_api_requests':0,
            'frames_reviewed':len(frames),'holds_triaged':len(holds),
            'category_counts':dict(Counter(h['category'] for h in holds)),
            'deferred_candidate_count':sum(len(f['deferred_regions']) for f in frames),
            'metrics':metrics,'reference_checks':comparison['reference_checks'],
            'findings':findings,'frames':frames,'holds':holds,
            'acceptance_before_rollout':[
                '그림/필기 전용 표현과 겹침 처리, 동일 타깃 병합, 미검토 영역 저장을 수정한 뒤 새 표본 실행.',
                '4·5·6·16·21·22·29·30·31·32번을 우선 재검증하고 결과를 현재 버전과 분리 보관.',
                '24개 기존 문구 검사에 표 셀 (Dictionary), 필기/강조 존재, 중복 본문, 코드 기호 검사 추가.',
                '품질 회귀와 지원되지 않는 자동 완성이 없음을 확인한 뒤 나머지 83개 화면 처리 및 음성 연결.']}
    if len(holds)!=75:raise ValueError('hold_snapshot_changed')
    save(binding_path,hashes);save(dest/'review.json',report)
    e=html.escape
    def source_link(fid):return f'../inputs/frames/{fid}.png'
    cards=[]
    for frame in frames:
        fid=frame['frame_id'];r=read(out/'optimized/vision'/fid/'result.json')
        rows=[h for h in holds if h['frame_id']==fid]
        entries=''.join(f'<li><b>{e(CATEGORIES[h["category"]])}</b> · 보류 #{h["hold_index"]+1}<p>{e(h["review_note"])}</p><details><summary>원래 판정 기록</summary><pre>{e(json.dumps(h["original_hold"],ensure_ascii=False,indent=2))}</pre></details></li>' for h in rows)
        pending=f'<details><summary>검토 상한 밖 후보 {len(frame["deferred_regions"])}개</summary><pre>{e(json.dumps(frame["deferred_regions"],ensure_ascii=False,indent=2))}</pre></details>' if frame['deferred_regions'] else ''
        cards.append(f'<details id="{fid}" class="frame"><summary>{fid} · {frame["time_seconds"]:g}초 · 보류 {len(rows)}건 · {e(frame["status"])}</summary>'
            f'<p class="note">{e(frame["notes"])}</p><a href="{source_link(fid)}"><img loading="lazy" src="{source_link(fid)}" alt="원본 {fid}"></a>'
            f'<ul>{entries}</ul>{pending}<div class="cols"><details><summary>기존 추출</summary><pre>{e(baseline[fid]["text"])}</pre></details>'
            f'<details><summary>개선 추출</summary><pre>{e(r["text"])}</pre></details></div></details>')
    findings_html=''.join(f'<article><h3>{e(f["id"]+" · "+f["title"])}</h3><p>{e(f["evidence"])}</p><p><b>수정 방향:</b> {e(f["action"])}</p><p>'+ ' · '.join(f'<a href="#frame-{n:05}">{n}번 원본·검토</a>' for n in f['frames'])+'</p></article>' for f in findings)
    category_rows=''.join(f'<tr><td>{e(CATEGORIES[k])}</td><td>{v}</td></tr>' for k,v in report['category_counts'].items())
    page=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>화면 추출 품질 검토</title>
<style>body{{max-width:1120px;margin:36px auto;padding:0 24px 60px;background:#f6f8fa;color:#203040;font:16px/1.7 system-ui}}h1{{font-size:32px}}h2{{margin-top:40px}}article,.frame,.banner{{background:white;border:1px solid #d6dee5;border-radius:10px;padding:20px;margin:16px 0}}.banner{{border-left:6px solid #b66a00;background:#fff6e5}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{border:1px solid #d6dee5;padding:10px;text-align:left}}summary{{cursor:pointer;font-weight:650}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf1f5;padding:14px;font-size:13px}}img{{width:100%;height:auto}}a{{color:#086f8d}}li{{margin-bottom:16px}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.note{{background:#eaf3f8;padding:14px}}@media(max-width:700px){{.cols{{grid-template-columns:1fr}}}}</style></head><body>
<h1>화면 추출 품질 검토</h1><p>2026-10-19 · 비교 표본 32개 · AI 원본 대조 및 보류 항목 분류</p>
<div class="banner"><b>판정: 전체 115개 화면 확대 보류</b><p>호출 수는 감소했지만 그림·필기·표 검토에서 보완할 문제가 확인됐습니다. 기존 결과·보류 상태는 유지하며, 이 보고서는 사람의 승인이나 정답률 인증이 아닙니다.</p></div>
<table><tr><th>항목</th><th>확인 결과</th></tr><tr><td>성공 응답 호출 수</td><td>{old_calls} → {new_calls}회 · {metrics['successful_call_reduction_percent']}% 감소</td></tr>
<tr><td>개선 실행 전체 요청 시도</td><td>{metrics['optimized_request_attempts']}회 · 실패 포함, 캐시 재사용 제외</td></tr><tr><td>개선 실행 누적 시간</td><td>{metrics['optimized_active_seconds']/60:.1f}분 · 중단 대기 제외</td></tr>
<tr><td>처리시간 비교</td><td>기존 32개 동일 표본의 총 경과시간 실측 부재. 속도 향상률은 확정하지 않음.</td></tr>
<tr><td>기존 문구 검사</td><td>24/24 보존 · 전체 정확도를 뜻하지 않음. 검사 밖 표 셀 누락 발견.</td></tr><tr><td>보류 검토</td><td>24개 화면의 75개 기록 전부 분류. 동일 영역의 중복 기록을 포함.</td></tr><tr><td>검토 상한 밖</td><td>11개 화면에 61개 후보 · 실제 오류 수가 아님. 아래 화면별 목록 제공.</td></tr></table>
<h2>확인된 문제와 수정 순서</h2>{findings_html}
<h2>보류 항목 분류</h2><table><tr><th>분류</th><th>기록 수</th></tr>{category_rows}</table>
<h2>다음 실행 조건</h2><ol>{''.join('<li>'+e(s)+'</li>' for s in report['acceptance_before_rollout'])}</ol>
<p>이번 검토에서는 새로운 Gemini 요청을 보내지 않았으며, 기존 추출을 정답으로 덮어쓰지 않았습니다. 원본에서 불확실한 필기는 추측으로 채우지 않았습니다.</p>
<p><a href="review.json">기계 판독용 전체 검토 기록</a> · <a href="input-hashes.json">입력 해시</a> · <a href="../화면최적화_비교결과.html">기존 비교 보고서</a></p>
<h2>32개 화면별 원본과 판단 근거</h2><p>각 항목을 펼치면 원본, 보류별 분류, 미처리 후보와 기존/개선 추출을 볼 수 있습니다. 원본 이미지를 누르면 전체 크기로 열립니다.</p>{''.join(cards)}</body></html>'''
    (dest/'품질검토.html').write_text(page,encoding='utf-8')
    if hashes!={str(p.relative_to(out)):digest_file(p) for p in inputs}:raise ValueError('source_changed_during_review_render')
    return report


if __name__=='__main__':
    r=build()
    print(json.dumps({k:r[k] for k in ('decision','frames_reviewed','holds_triaged','category_counts','deferred_candidate_count','metrics')},ensure_ascii=False,indent=2))
