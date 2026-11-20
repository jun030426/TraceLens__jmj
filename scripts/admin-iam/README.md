# 관리자 AWS 제어 권한 — 운영 적용 완료

2026-11-15 현재 `ap-southeast-2`의 기존 서버 `i-0c64182a7dada987a`만 제어한다.

AWS 새 경험 프로젝트의 관리 SCP가 IAM OIDC provider 기능을 제한하므로, 지원되는 Lambda Function URL을 사용했다. 프로젝트 정책·요금제를 변경하지 않았다.

`Vercel 관리자 API → Vercel production OIDC 토큰 → Lambda → EC2`

- 함수: `lerny-admin-control`, Node.js 24, arm64, 128MB, 20초 제한, 예약 동시 실행 2.
- 실행 역할: `lerny-admin-control-lambda`. Lambda 서비스만 역할을 사용한다.
- Function URL의 전송 계층 AuthType은 NONE이며, 함수가 매 요청의 RS256 서명·issuer·audience·subject·만료를 검증한다. 인증 없는 요청은 401이다. 장기 AWS 키나 새 공유 비밀을 Vercel에 넣지 않는다.
- issuer: `https://oidc.vercel.com/kigkig495-2084s-projects`
- audience: `https://vercel.com/kigkig495-2084s-projects`
- subject: `owner:kigkig495-2084s-projects:project:lerny:environment:production`
- JWKS는 고정 issuer의 `/.well-known/jwks`만 읽는다. 다른 팀·프로젝트·환경·서명·만료 토큰은 거부한다.
- 입력은 describe/start/stop 중 하나뿐이다. 서버 ID는 함수 환경에서 고정하고 요청에서 받지 않는다. 정상 StopInstances만 사용한다.
- SDK 호출은 1회만 전송한다. 타임아웃 뒤 자동 재전송하지 않으며 DB 명령 처리기가 상태를 재조회한다.
- 로그 `/aws/lambda/lerny-admin-control`은 14일 보관한다. 이벤트·토큰·원시 예외를 기록하지 않는다.

`lambda-autopilot-baseline.json`은 iam-policy-autopilot 0.4.0이 실제 함수 소스에서 생성했다.

```text
uvx iam-policy-autopilot@latest generate-policies <absolute-repository>/deploy/admin-control/handler.mjs --language javascript --region ap-southeast-2 --account 604472166923 --service-hints ec2 --pretty
```

`ec2-control-policy.json`은 생성 결과에서 EC2 작업만 남기고 시작·중지를 기존 서버 한 대로 제한했다. 조회 API의 Resource `*`는 유지하되 요청 리전을 제한했다. 다른 서버·TerminateInstances·SSM·license-manager/resource-groups 권한은 없다. 배포 시 전용 로그 그룹의 CreateLogStream/PutLogEvents만 추가했다.

Function URL 리소스 정책은 InvokeFunctionUrl을 AuthType NONE에, InvokeFunction을 InvokedViaFunctionUrl=true에 제한한다. 모든 URL 요청은 위 JWT 인증을 거친다.

`autopilot-baseline.json`과 `vercel-production-trust.json`은 초기 직접 STS 방식 검토 자료이며 운영에는 적용하지 않았다. Python 어댑터의 선택적 직접 역할 모드는 남아 있으나 현재는 `LERNY_ADMIN_CONTROL_URL`을 사용한다.

실제 Vercel 운영 인증으로 상태 조회·중지·브라우저 시작·세 처리기 복구를 확인했다. 별도 IAM 모의 평가나 Access Analyzer 검증을 수행했다고 주장하지 않는다.

참고: [Vercel OIDC](https://vercel.com/docs/oidc/reference), [AWS 지원 서비스](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html), [Lambda URL 권한](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html).
