import argparse
from video_extraction.shared import file_lock as fcntl
import sys
from pathlib import Path

from . import ROOT, OUTPUT
from .corpus import prepare, load_corpus
from .providers import Google
from .retrieval import build_index, keyword_search
from .pipeline import ask, display
from .unified_rag import UnifiedMultimodalRAG
from video_extraction.shared.common import save, now
from video_extraction.shared.gemini import Blocked
#검색부터 답변까지 연결. 검색 자료를 Gemini에 전달하고 답변의 출처·인용을 검사해. 결과와 처리시간을 JSON·HTML로 저장

def check_worker():
    lock=ROOT/'outputs/vision-optimization/.benchmark.lock'
    if lock.exists():
        with lock.open('r') as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('영상 비교 작업이 실행 중입니다. 해당 터미널 작업이 끝난 뒤 RAG를 실행하세요.') from None
            finally:
                try:fcntl.flock(f,fcntl.LOCK_UN)
                except OSError:pass


CASES=[
    ('스택의 Pop과 Peek는 어떻게 달라?', [{'chapter6-s023'},{'chapter6-s024'}],False),
    ('스택의 탐색 Search 시간 복잡도는?', [{'chapter6-s028'}],False),
    ('이 강의 중간고사 날짜는 언제야?', [],True),
]


def main():
    p=argparse.ArgumentParser(description='로컬 강의자료 최소 RAG')
    p.add_argument('command',choices=['prepare','search','index','ask','chat','quiz','shorts','shorts-candidates','evaluate','section-create','section-ingest','section-list','check-worker'])
    p.add_argument('question',nargs='?')
    p.add_argument('--output',type=Path,default=OUTPUT)
    p.add_argument('--course',help='수업 과목 ID (예: cs101, 자료구조)')
    p.add_argument('--section',help='수업 분반 ID (예: sec01, 1분반)')
    p.add_argument('--course-name',help='수업 과목명 (예: 자료구조 및 실습)')
    p.add_argument('--section-name',help='수업 분반명 (예: 1분반)')
    p.add_argument('--professor',help='교수자 ID 또는 이름')
    p.add_argument('--concept',help='퀴즈 또는 숏츠 대상 개념 키워드')
    p.add_argument('--seconds',type=int,default=60,help='숏츠 영상 목표 길이(초)')
    p.add_argument('--auto',action='store_true',help='음성비중+피피티비율+필기보너스 기반 숏츠 자동 추출')
    p.add_argument('--min-score',type=float,default=70.0,help='숏츠 자동 추출 기본 최소점수(기본값: 70.0)')
    p.add_argument('--offline',action='store_true',help='API 호출 없이 오프라인 모드로 실행')
    p.add_argument('--input',type=Path,nargs='+',help='prepare용 PPTX/DOCX 원본. API 없이 코드·본문 분리')
    p.add_argument('--max-calls',type=int,default=80)
    p.add_argument('--delay',type=float,default=2)
    args=p.parse_args()

    # Automatic section directory resolution
    if args.course and args.section and args.output == OUTPUT:
        from .section_manager import CourseSectionManager
        out = CourseSectionManager().get_section_dir(args.course, args.section)
    else:
        out = args.output

    if args.command=='check-worker':check_worker();return

    if args.command=='section-list':
        from .section_manager import CourseSectionManager
        mgr=CourseSectionManager()
        sections=mgr.list_sections()
        if not sections:print("등록된 분반이 없습니다.")
        else:
            print(f"=== 등록된 수업 분반 목록 (총 {len(sections)}개) ===")
            for s in sections:
                print(f"- [{s['course_id']} / {s['section_id']}] {s['course_name']} {s['section_name']} (교수: {s.get('professor_id')}, 청크: {s.get('chunk_count')}개, 경로: {s['folder']})")
        return

    if args.command=='section-create':
        if not args.course or not args.section:p.error('section-create에는 --course와 --section이 필수입니다.')
        from .section_manager import CourseSectionManager
        mgr=CourseSectionManager()
        meta=mgr.create_section(args.course,args.section,course_name=args.course_name,section_name=args.section_name,professor_id=args.professor)
        print("✅ 수업 분반 물리적 디렉토리 및 메타데이터 생성 완료:")
        print(f"  과목: {meta['course_name']} ({meta['course_id']})")
        print(f"  분반: {meta['section_name']} ({meta['section_id']})")
        print(f"  폴더: {meta['folder']}")
        return

    if args.command=='section-ingest':
        if not args.course or not args.section:p.error('section-ingest에는 --course와 --section이 필수입니다.')
        from .section_manager import CourseSectionManager
        mgr=CourseSectionManager()
        input_target=args.input[0] if args.input else out
        dest,corpus=mgr.ingest_corpus_to_section(args.course,args.section,input_target,course_name=args.course_name,section_name=args.section_name)
        print("✅ 수업 분반 자료 등록 및 메타데이터 태깅 완료:")
        print(f"  분반: {args.course} {args.section}")
        print(f"  저장 위치: {dest}")
        print(f"  등록된 청크 수: {len(corpus['chunks'])}개")
        return
    if args.command=='prepare':
        if args.input:
            from .document_ingest import prepare_documents
            c=prepare_documents(args.input,out)
        else:c=prepare(out)
        print(f"자료 준비 완료: {len(c['chunks'])}개 청크, API 0회. 보류 항목은 review-queue.json 확인");return
    if args.input:p.error('--input은 prepare에서만 사용합니다.')
    corpus=load_corpus(out)
    if args.command=='search':
        if not args.question:p.error('질문을 입력하세요.')
        print('키워드 검색만 실행 — 임베딩 검색이나 AI 답변이 아닙니다.')
        for h in keyword_search(corpus['chunks'],args.question,4):print(f"\n[{h['id']}] {h['title']}\n{h['text']}")
        return
    check_worker()
    run_lock=(out/'.rag.lock').open('a')
    try:fcntl.flock(run_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('같은 자료로 RAG 작업이 이미 실행 중입니다.') from None
    client=None
    if not args.offline:
        try:
            client=Google(out,ROOT/'.env',max_calls=args.max_calls,delay=args.delay)
        except Exception:
            if args.command in ('quiz','shorts','chat'):
                client=None
            else:
                raise
    if args.command=='index':
        folder=build_index(out,corpus,client);print('벡터 저장 완료: '+str(folder));return
    if args.command=='ask':
        if not args.question:p.error('질문을 입력하세요.')
        display(ask(out,corpus,client,args.question));return
    if args.command=='evaluate':
        results=[]
        for question,groups,negative in CASES:
            r=ask(out,corpus,client,question);display(r)
            ids={h['id'] for h in r['hits']}|{h['parent_slide_id'] for h in r['hits'] if h.get('parent_slide_id')}
            passed=(r['status']=='abstained') if negative else (r['status']=='citation_checked' and all(ids & g for g in groups))
            results.append({'question':question,'passed':passed,'status':r['status'],'required_sources_retrieved':all(ids & g for g in groups),'timing':r['timing'],'api_stats':r['api_stats']})
        save(out/'evaluation.json',{'at':now(),'cases':results,'passed':sum(r['passed'] for r in results),'total':len(results),
            'limitation':'Retrieval, literal citation, and abstention smoke tests only; not independently graded answer accuracy.'})
        print(f"\nRAG 실행 완료 · 최소 점검 {sum(r['passed'] for r in results)}/{len(results)} 통과")
        if not all(r['passed'] for r in results):raise RuntimeError('최소 점검 실패: evaluation.json과 답변 기록을 확인하세요.')
        return
    if args.command=='quiz':
        topic=args.question or args.concept or '강의 핵심 개념'
        rag=UnifiedMultimodalRAG(out,client=client)
        q=rag.generate_quiz(topic)
        print(f"\n[적응형 퀴즈 생성 결과: {topic}]")
        print(f"문제: {q.get('question_stem') or q.get('question')}")
        for opt in q.get('options',[]):print(f"  {opt}")
        print(f"\n정답: {q.get('correct_index')+1}번" if isinstance(q.get('correct_index'),int) else "")
        print(f"해설: {q.get('explanation')}")
        print(f"출처: {q.get('source_locator',q.get('source_id'))}")
        save(out/'latest-quiz.json',q)
        return
    if args.command=='shorts-candidates':
        rag=UnifiedMultimodalRAG(out,client=client,course_id=args.course,section_id=args.section)
        candidates=rag.extract_shorts_candidates(min_score=args.min_score,top_n=10)
        if not candidates:
            print(f"기준 점수({args.min_score}점 및 보완 최저선 60.0점) 이상인 숏츠 추천 후보를 찾지 못했습니다.")
            return
        print(f"\n=== [숏츠 영상 대본 자동 추천 후보 Top {len(candidates)}] ===")
        print("산출 기준: 기본 100점(음성 70% + PPT밀도 30%) + 필기 가산 보너스(+0~10점) [하이브리드 룰 적용]")
        for i, c in enumerate(candidates, 1):
            m = c['metrics']
            rule_tag = "🌟 기본 70% 충족" if c.get('selection_rule') == 'primary' else "🛡️ 하이브리드 보완 선정"
            multi_tag = f" [연계 {c['slide_count']}장]" if c.get('is_multi_slide') else ""
            print(f"{i}. [{c['tier']} 등급 | 총점: {c['total_score']}점 | {rule_tag}] {c['source_locator']}{multi_tag} - '{c['title']}'")
            print(f"   📊 기본점수: {m['base_score']}점 (음성 {m['speech_score']}점 [70%] + PPT {m['ppt_score']}점 [30%])")
            print(f"   🎁 필기 보너스: +{m['ink_bonus']}점 (키워드 {m['keyword_count']}개, 필기마크: {m['ink_score']}점)")
            print(f"   🎯 추천 숏츠 훅(Hook): \"{c['recommended_hook']}\"")
        return
    if args.command=='shorts':
        rag=UnifiedMultimodalRAG(out,client=client,course_id=args.course,section_id=args.section)
        topic=args.question or args.concept
        if args.auto or not topic:
            # Automatic candidate extraction using 3-factor composite score and hybrid rule
            candidates=rag.extract_shorts_candidates(min_score=args.min_score,top_n=1)
            if not candidates:
                print(f"기준 점수({args.min_score}점) 이상인 자동 추천 후보가 없어 기본 요약으로 진행합니다.")
                topic = topic or '강의 핵심 요약'
                s=rag.generate_shorts_script(topic_or_concept=topic,target_seconds=args.seconds)
            else:
                top_cand = candidates[0]
                m = top_cand['metrics']
                rule_tag = "기본 70% 컷" if top_cand.get('selection_rule') == 'primary' else "하이브리드 보완 룰"
                print(f"\n🌟 [숏츠 자동 추천 1위 선정 - 총점 {top_cand['total_score']}점 ({top_cand['tier']} 등급 | {rule_tag})]")
                print(f"  - 슬라이드: {top_cand['source_locator']} ('{top_cand['title']}')")
                print(f"  - 기본 점수: {m['base_score']}점 (음성 {m['duration_seconds']}초/{m['speech_score']}점 + PPT {m['ppt_score']}점)")
                print(f"  - 필기 보너스: +{m['ink_bonus']}점 (필기 키워드: {m['keyword_count']}개)")
                s=rag.generate_shorts_script(chunk_id=top_cand['id'],target_seconds=args.seconds)
        else:
            s=rag.generate_shorts_script(topic_or_concept=topic,target_seconds=args.seconds)
        print(f"\n[숏츠 영상 대본 생성: {s.get('title')}]")
        print(f"출처: {s.get('source_locator')} | 원본 영상 구간: {s.get('original_video_timestamp')}")
        for act in s.get('acts',[]):
            print(f"\n[{act['act']} - {act['seconds']}]")
            print(f"  🎬 화면 연출: {act['visual_direction']}")
            print(f"  🎙️ 나레이션: {act['narration']}")
        rag.render_shorts_html(s,out/'숏츠_대본.html')
        save(out/'latest-shorts.json',s)
        hg=rag.export_heygen_format(s,out_dir=out)
        print(f"\n✅ 숏츠 대본 및 헤이젠/캔바 파일 생성 완료:")
        print(f"  - 웹 미리보기 HTML: {out/'숏츠_대본.html'}")
        print(f"  - 헤이젠 스튜디오 복붙용: {hg['txt_file']}")
        print(f"  - 헤이젠 API JSON 규격: {hg['json_file']}")
        print(f"  - 캔바(Canva) 대량제작 CSV: {hg['canva_csv']}")
        return
    print('대화형 챗봇 모드입니다. 이전 대화 맥락을 기억합니다. 종료: /exit')
    history=[]
    rag=UnifiedMultimodalRAG(out,client=client)
    while True:
        question=input('\n질문 > ').strip()
        if question=='/exit':return
        if question:
            res=rag.ask_chat(question,history=history)
            if 'reply' in res:
                print(f"\n답변: {res['reply']}")
                history.append({'role':'user','content':question})
                history.append({'role':'assistant','content':res['reply']})
            elif 'candidate' in res:
                c=res['candidate']
                if c.get('claims'):
                    reply_text="\n".join(cl['text'] for cl in c['claims'])
                    print(f"\n답변:\n{reply_text}")
                    for cl in c['claims']:
                        print(f"  - [인용 출처: {cl.get('source_id')}] \"{cl.get('quote')}\"")
                    history.append({'role':'user','content':question})
                    history.append({'role':'assistant','content':reply_text})
                else:
                    print(f"\n답변 불가: {c.get('reason')}")


if __name__=='__main__':
    try:main()
    except (Blocked,RuntimeError,ValueError,FileNotFoundError) as exc:
        print(f'\n진행 보류: {exc}',file=sys.stderr);sys.exit(2)
    except (KeyboardInterrupt,EOFError):
        print('\n종료했습니다. 저장된 결과는 유지됩니다.');sys.exit(130)
