"""Run in the same Python/environment as the worker before resuming paid/quota-limited work."""
from video_extraction._layout import PROJECT_ROOT
import argparse
from pathlib import Path
import tempfile
import time

from video_extraction.shared.common import now, save
from video_extraction.shared.errors import guidance
from video_extraction.shared.gemini import Blocked, Gemini, api_key, obj, EXTRACT

ROOT=PROJECT_ROOT


def diagnose(env_file, model, transport=None, check_vision=False, sleeper=time.sleep):
    report={'checked_at':now(),'model':model,'state':'checking','checks':{},
            'note':'Fresh API contract check with optional synthetic image; not lecture OCR accuracy validation.'}
    started=time.monotonic()
    client=None
    try:
        api_key(env_file)
        report['checks']['key_loaded']=True
        # Fresh cache: a prior success must not hide an expired key or changed permissions.
        with tempfile.TemporaryDirectory(prefix='gemini-preflight-') as folder:
            client=Gemini(Path(folder)/'cache',model,env_file,max_calls=9 if check_vision else 3,
                          delay=15 if check_vision else 1,transport=transport,sleeper=sleeper)
            value=client.call('connection_check',[],
                'This is an API connectivity test. Return the JSON object with ok set to true.',
                obj({'ok':{'type':'boolean','enum':[True]}}))
            if value['ok'] is not True:raise Blocked('invalid_model_response')
            report['checks'].update(api_generation=True,structured_output=True)
            if check_vision:
                from PIL import Image, ImageDraw
                picture=Path(folder)/'contract-test.png'
                im=Image.new('RGB',(640,320),'white')
                ImageDraw.Draw(im).text((60,100),'x + 1',fill='black',font_size=64)
                im.save(picture)
                try:
                    client.call('image_extraction_contract',[picture],
                        'Transcribe the visible expression as one code block. Use id b1, normalized '
                        '[left,top,right,bottom] bbox coordinates in 0..1000 and no invented content. '
                        'Return blocks, readable and notes using the extraction schema.',EXTRACT)
                except Blocked as exc:
                    # One discriminating probe separates image acceptance from schema acceptance.
                    if str(exc)=='gemini_http_400':
                        try:
                            client.call('basic_image_contract',[picture],
                                'This is an image API contract test. Return ok=true.',
                                obj({'ok':{'type':'boolean','enum':[True]}}))
                            report['checks']['image_input_basic']=True
                            exc.detail['basic_image_probe']='passed; extraction schema combination needs investigation'
                        except Blocked as probe:
                            exc.detail['basic_image_probe']={'reason':str(probe),'detail':probe.detail}
                    raise
                report['checks'].update(image_input=True,extraction_schema=True)
        report['state']='ready'
        report['next_action']=('연결·인증·모델 호출·JSON 응답'+('·이미지 추출 형식' if check_vision else '')+
                               ' 확인을 통과했습니다. 저장된 작업을 이어갑니다.')
    except Blocked as exc:
        report.update(state='blocked',reason=str(exc),detail=exc.detail,next_action=guidance(str(exc)))
    except OSError as exc:
        report.update(state='blocked',reason='local_configuration_unreadable',
                      detail={'exception_type':type(exc).__name__},
                      next_action='프로젝트 .env와 출력 폴더의 파일 접근 권한을 확인하세요.')
    report['elapsed_seconds']=time.monotonic()-started
    report['api']=client.stats if client else {'requests':0,'successes':0}
    return report


def main():
    parser=argparse.ArgumentParser(description='Check Gemini access without exposing the key')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--model',default='gemini-3.8-flash')
    parser.add_argument('--check-vision',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/video-extraction/연결진단.json')
    args=parser.parse_args()
    report=diagnose(args.env_file,args.model,check_vision=args.check_vision)
    save(args.output,report)
    lines=[f'Gemini 연결 진단: {report["state"]}',f'모델: {args.model}',
           f'오류 코드: {report.get("reason","없음")}',report['next_action'],
           f'진단 JSON: {args.output.resolve()}']
    if report.get('detail',{}).get('api_message'):
        lines.insert(-1,'Google 응답: '+report['detail']['api_message'])
    text='\n'.join(lines)+'\n'
    args.output.with_suffix('.txt').write_text(text,encoding='utf-8')
    print(text,flush=True)
    return 0 if report['state']=='ready' else 2


if __name__=='__main__':raise SystemExit(main())
