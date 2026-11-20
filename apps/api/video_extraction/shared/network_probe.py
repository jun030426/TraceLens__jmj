"""Read-only checks using the worker's own runtime and normal OS resolver.

No API key, no model generation, no DNS/proxy edits, no alternate resolver.
Run in the user's Terminal to distinguish its access from a restricted agent runtime.
"""
from video_extraction._layout import PROJECT_ROOT
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from video_extraction.shared.common import now, save

ROOT=PROJECT_ROOT
LOOKUP='''import socket,sys,json
try:
 result=socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)
 print(json.dumps({"ok":bool(result)}))
except OSError as e:
 print(json.dumps({"ok":False,"exception_type":type(e).__name__,"errno":e.errno}))
'''


def probe():
    report={'checked_at':now(),'scope':'This Python process only; not a diagnosis of all apps on this Mac.',
            'dns':{},'api_key_used':False,'settings_modified':False}
    for host in ('generativelanguage.googleapis.com','www.google.com','example.com'):
        start=time.monotonic()
        try:
            p=subprocess.run([sys.executable,'-c',LOOKUP,host],capture_output=True,text=True,timeout=8,check=True)
            value=json.loads(p.stdout)
        except subprocess.TimeoutExpired:value={'ok':False,'exception_type':'lookup_timeout'}
        except (ValueError,subprocess.CalledProcessError,OSError):value={'ok':False,'exception_type':'probe_failed'}
        report['dns'][host]={**value,'seconds':time.monotonic()-start}
    google_ok=report['dns']['generativelanguage.googleapis.com']['ok']
    report['https']={'attempted':google_ok,'response_received':False}
    if google_ok:
        try:
            with urllib.request.urlopen('https://generativelanguage.googleapis.com/',timeout=8) as r:
                report['https'].update(response_received=True,http_status=r.status)
        except urllib.error.HTTPError as e:
            # A normal 404/401/403 still proves an HTTP response was received. Not API authorization.
            report['https'].update(response_received=True,http_status=e.code)
        except (urllib.error.URLError,TimeoutError,OSError) as e:
            cause=getattr(e,'reason',e)
            report['https']['exception_type']=type(cause).__name__
    failures=sum(not v['ok'] for v in report['dns'].values())
    if failures==3:
        report['interpretation']='이 실행 환경에서는 일반 사이트도 모두 주소 조회가 실패했습니다. API 키나 특정 모델의 문제로 좁힐 수 없습니다. 실행 환경의 네트워크 제한 또는 연결 문제를 구분해야 합니다.'
    elif not google_ok:
        report['interpretation']='일반 사이트와 Google API의 주소 조회 결과가 다릅니다. Google API 도메인의 접근 상태를 확인해야 하지만 이 검사만으로 원인을 확정할 수 없습니다.'
    elif not report['https']['response_received']:
        report['interpretation']='주소 조회는 성공했지만 HTTPS 응답을 받지 못했습니다. 기록된 오류 종류를 확인하세요. 키 검사는 아직 하지 않았습니다.'
    else:
        report['interpretation']='현재 이 실행 환경에서 Google API 주소 조회와 HTTPS 응답을 확인했습니다. API 키·모델 접근·할당량은 실제 API 요청에서 별도로 확인합니다.'
    report['state']='transport_reachable' if google_ok and report['https']['response_received'] else 'blocked'
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'outputs/vision-optimization/network-terminal.json')
    args=parser.parse_args();report=probe();save(args.output,report)
    for host,row in report['dns'].items():print(f'{host}: '+('주소 조회 성공' if row['ok'] else '주소 조회 실패'))
    print(report['interpretation']);print('설정 변경·API 키 사용·모델 호출: 없음');print(f'진단 파일: {args.output}')
    return 0 if report['state']=='transport_reachable' else 2


if __name__=='__main__':raise SystemExit(main())
