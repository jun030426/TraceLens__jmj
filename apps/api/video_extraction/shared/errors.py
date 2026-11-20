"""Actionable, credential-free API diagnostics shared by the worker and launcher."""
import json
import re
import socket
import ssl


def redact(value, key=''):
    text=str(value)
    if key:text=text.replace(key,'[REDACTED]')
    text=re.sub(r'AIza[\w-]{20,}', '[REDACTED]', text)
    text=re.sub(r'(?i)((?:api[_-]?key|key)=)[^\s&"\']+', r'\1[REDACTED]', text)
    return text[:1200]


def network_failure(error):
    cause=getattr(error,'reason',error)
    if isinstance(cause,socket.gaierror):reason='gemini_dns_failed'
    elif isinstance(cause,ssl.SSLCertVerificationError):reason='gemini_tls_certificate_failed'
    elif isinstance(cause,PermissionError):reason='gemini_network_permission_denied'
    elif isinstance(cause,(TimeoutError,socket.timeout)):reason='gemini_timeout'
    else:reason='gemini_network_unavailable'
    # Avoid copying arbitrary URL/proxy credentials from exception messages.
    return reason,{'exception_type':type(cause).__name__,'errno':getattr(cause,'errno',None)}


def http_failure(error, key=''):
    info={'http_status':error.code}
    try:
        data=json.loads(error.read(65536));api_error=data.get('error',{})
        if isinstance(api_error,dict):
            for field in ('code','status','message'):
                if field in api_error:info['api_'+field]=redact(api_error[field],key)
            violations=[]
            for item in api_error.get('details',[]) if isinstance(api_error.get('details',[]),list) else []:
                if not isinstance(item,dict):continue
                for violation in item.get('fieldViolations',[]) if isinstance(item.get('fieldViolations',[]),list) else []:
                    if isinstance(violation,dict):
                        violations.append({field:redact(violation[field],key) for field in ('field','description') if field in violation})
            if violations:info['field_violations']=violations[:12]
    except (ValueError,TypeError,AttributeError,OSError):pass
    try:
        seconds=float(error.headers.get('Retry-After',''))
        if 0<=seconds<604800:info['retry_after_seconds']=seconds
    except (AttributeError,ValueError,TypeError):pass
    code=str(info.get('api_code','')).lower()
    message=info.get('api_message','').lower()
    reason=f'gemini_http_{error.code}'
    if code=='quota_exceeded':reason='gemini_daily_quota_exceeded'
    elif error.code==401 or ('api key' in message and any(s in message for s in ('invalid','expired','leaked'))):
        reason='gemini_authentication_failed'
    return reason,info


def guidance(reason):
    return {
      'missing_api_key':'프로젝트 .env에 GEMINI_API_KEY가 저장되어 있는지 확인하세요. 키 값은 채팅이나 로그에 붙이지 마세요.',
      'gemini_dns_failed':'이 실행 환경에서 Google API의 도메인 이름을 IP 주소로 변환하지 못했습니다. 제한된 실행 환경의 접근 문제와 Mac 터미널의 일시적인 네트워크 문제는 구분해야 합니다. 이 메시지만으로 Mac의 DNS 설정 오류라고 판단할 수 없습니다. API 키 검사 전 단계이므로 키 재발급·유료 전환을 먼저 할 필요는 없습니다. 프로젝트의 연결상태_확인.command로 같은 터미널에서 주소 조회와 HTTPS 연결을 확인할 수 있습니다.',
      'gemini_network_permission_denied':'현재 실행 환경의 네트워크 권한을 확인하세요. 권한이 허용된 환경에서 같은 실행 파일로 이어갈 수 있습니다.',
      'gemini_tls_certificate_failed':'Python이 HTTPS 인증서를 신뢰하지 못합니다. Python 인증서 설치 또는 조직의 승인된 인증서 설정을 확인하세요. 인증서 검증을 끄지 마세요.',
      'gemini_timeout':'API 응답 시간이 초과되었습니다. 네트워크 상태를 확인한 후 같은 파일을 다시 실행하세요.',
      'gemini_network_unavailable':'Google API에 연결하지 못했습니다. Mac의 인터넷·프록시·방화벽 연결 상태를 확인하세요.',
      'gemini_authentication_failed':'Google AI Studio에서 키 상태와 프로젝트를 확인하고 필요하면 .env의 키를 갱신하세요.',
      'gemini_http_400':'Google이 요청 설정 또는 계정 조건을 거절했습니다. state.json의 blocked_detail 또는 api-cache/last-error.json에서 api_message·stage·field_violations를 확인하세요.',
      'gemini_http_402':'계정 결제 잔액 관련 응답입니다. 자동으로 결제를 변경하지 않습니다. 계정 상태와 사용 가능한 무료 모델을 확인하세요.',
      'gemini_http_403':'이 키의 프로젝트·API 사용 권한 또는 제한을 Google AI Studio에서 확인하세요.',
      'gemini_http_404':'현재 모델 이름이나 계정의 모델 접근 가능 여부를 확인하세요.',
      'gemini_http_429':'분당 요청·토큰 한도 또는 일일 할당량을 확인하세요. 짧은 제한은 대기 후 재실행하고, 일일 한도라면 초기화 후 이어가세요.',
      'gemini_daily_quota_exceeded':'일일 할당량을 초과했습니다. 한도가 초기화된 후 같은 파일을 실행하면 완료한 단계는 재사용합니다.',
      'request_budget_exhausted':'이번 실행의 호출 상한에 도달했습니다. 사용량을 확인한 후 같은 파일을 다시 실행하면 이어갑니다.',
      'invalid_model_response':'Gemini 응답이 요구한 JSON 형식을 만족하지 못했습니다. api-cache의 invalid 기록을 확인해야 합니다.',
      'malformed_http_response':'서버 또는 프록시가 JSON이 아닌 응답을 반환했습니다. 네트워크 상태와 API 응답을 확인해야 합니다.',
    }.get(reason,'저장된 오류 코드와 메시지를 확인하세요. 기존 완료 결과는 보존되어 있습니다.')
