# Azdemy 교육 추천·상담 데모 API

2026-10-22 기존 데모 RG를 삭제했습니다. 아래 실제 구성·상담 결과는 삭제 전
검증 기록입니다. 다음 배포에는 `azdemy` 자원명과 `AZDEMY_*` 설정을 사용하며,
이전 API·Foundry 주소와 MI·앱 ID를 새 환경에 그대로 적용하지 않습니다.
새 환경은 아직 배포·통합 검증하지 않았습니다.

합성 과정 30개와 합성 학습자 2명을 사용하는 읽기 전용 데모입니다.
2026-10-22 Azdemy API와 Prompt Agent를 재배포하고 새 native Fabric Spark 배치 결과를
기존 Private App Service에 수동 게시했습니다.
정적 추천 snapshot은 로컬 회귀 테스트와 명시적인 이전 버전 복구용으로 남깁니다.
FastAPI는 기존 Private App Service에, 상담 지시문과 OpenAPI
도구는 Microsoft Foundry Agent Service의 일반 Prompt Agent에 게시합니다.
Hosted Agent·다중 에이전트·별도 UI는 사용하지 않습니다.

## 실제 구성과 Mock

| 구분 | 구성 |
|---|---|
| 실제 | Python 3.12 App Service, FastAPI/Pydantic, Entra JWT 검증, Private Endpoint |
| 실제 | Foundry Prompt Agent `education-consultant`, `gpt-5.6-terra` GlobalStandard |
| 실제 | 읽기 전용 OpenAPI 3개, API key 없는 Managed Identity 인증 |
| 실제 | 전용 Private Fabric workspace, Lakehouse Delta, Spark ML·MLflow, 버전별 JSON 게시 |
| 데모 Serving | 기존 App Service의 지속 저장 영역. 별도 production Serving DB는 없음 |
| 합성·미통합 | 직원·학습 이력·원천 시스템. 최종 사용자 OBO는 미구현 |
| 합성 자료 | 자체 작성 과정·수강 조건·추천 이유. 외부 과정 콘텐츠를 수집하지 않음 |

도구 경로는 `Foundry → Private API → 게시된 JSON snapshot`입니다.
생성 경로는 `Fabric Spark ML → Delta 검증 → Private OneLake export → Private SCM 게시`입니다.
상담 에이전트가 추천을 생성하거나 순위를 다시 정하지 않습니다.
기존 BYO
Cosmos·Storage·Search는 Foundry Standard Setup의 종속 자원입니다.
이 자원에 추천 Serving 데이터를 적재하지 않습니다.

2026-10-22에 확인한 정상 게시 버전은
`fabric-4bf533b7-6664-476b-bbed-3479edfb2057`입니다.
학습 모델은 `genius-content-baseline:1`, 실제 상담 대상은
`education-consultant:6`이며 이전 버전은 삭제하지 않았습니다. 모델은 기본 Spark ML
TF-IDF·cosine 콘텐츠 기반 추천입니다. 추천 품질 개선이나 직원 대상 품질을
검증한 결과는 아닙니다. 생성·게시·rollback 운영은
[Fabric 가이드](../fabric/README.md)를 따릅니다.

## 호출 주체와 권한 경계

API는 RS256 서명, tenant, issuer, audience, 만료 시각, 필수 claim과
`Learner.Read` 앱 역할 또는 `access_as_user` 위임 scope를 검사합니다.
그다음 허용된 `oid → 합성 학습자` 매핑을 적용합니다. 이름이 같은 역할이나
유효한 Entra 토큰만으로는 호출할 수 없습니다. 임의 직원·scenario parameter도
허용하지 않습니다.

현재 audience는 `api://366a7288-b529-4b7f-a40d-03169869264f`이고, v2 JWT의
`aud`는 앱 client ID `366a7288-b529-4b7f-a40d-03169869264f`입니다.
허용된 호출 주체는 **실제 OpenAPI 호출에서 확인한 Foundry account MI**
`1380c4f0-06be-413c-8aee-2a4046ad5615` 하나이며 합성 학습자 A로 고정합니다.
이 MI에 전용 API의 조회 역할만 부여했습니다. 사람의 위임 인증·개인 직원
매핑은 아직 통합하지 않았습니다.

현재 공식 OpenAPI 문서는 project MI를 설명하지만, 이 환경의 로그인 로그는
account MI의 API 토큰 요청과 미할당 오류 `501051`을 기록했습니다. 실제 역할과
API 매핑을 account MI에 연결한 뒤 도구 호출이 성공했습니다. Agent가 가진
별도 `instance_identity`, 프로젝트 MI, account MI를 같은 주체로 취급하면
안 됩니다. 진단 중 추가한 프로젝트 MI·Agent Identity의 API 역할은 회수했습니다.
재배포·런타임 변경 때도 실제 caller를 다시 확인해야 합니다.

하나의 전용 account만 쓰는 고정 A 데모용 경계입니다. 같은 account 안의
다른 에이전트까지 분리하는 production 권한 모델이나 최종 사용자 OBO 구현으로
설명하지 않습니다. 합성 과정 사실은 인증된 호출 주체가 모두 조회할 수 있지만,
수강 자격·선수 과정·수료 여부는 별도로 계산합니다.

## 조회 계약

| Operation | 경로 | 응답 |
|---|---|---|
| `getMyRecommendations` | `GET /recommendations/me` | 본인의 추천·원본 순위·이유·생성 시각·버전·분리된 의무교육 |
| `searchCourses` | `GET /courses/search` | `query`, `category`, `language`, `limit` 조건으로 과정 검색 |
| `getCourses` | `GET /courses?ids=SYN-DEV-001,SYN-DEV-002` | 쉼표로 구분한 최대 5개 과정의 사실과 수강 가능 여부 |

카탈로그의 `detail_path`는 인증된 JSON 상세 조회 경로입니다. 신청 페이지가
아니며 쓰기 API는 없습니다. 과정 사실은 `source_ref`, 추천 이유는
`reason_source_ref`로 구분합니다.

현재 Fabric 결과에서 학습자 A의 일반 추천은 `SYN-DEV-002`, `SYN-PRD-002`,
`SYN-DAT-002`이며 순위는 **1·2·3**입니다. 기존 정적 fixture의 순위는
**1·7·8**이며 로컬 회귀 테스트에서 그대로 검증합니다. 수료·수강 자격·필수 선수
과정·모집 기간·마감·폐강 검사를 거치되 다시 번호를 매기지 않습니다.
의무교육 `SYN-SEC-001`은 순위 없이 별도로 표시합니다.

학습 이력이 부족한 합성 학습자 B는 `cold_start_by_role` 정책 snapshot을
사용합니다. API 실패나 누락된 개인화 snapshot을 cold-start로 숨기지 않습니다.
B·만료·무결과·장애 fixture는 로컬 테스트에서만 주입합니다. 공개 scenario
전환이나 인증 우회 endpoint는 없습니다.

현재 Fabric snapshot의 실제 생성 시각은 `2026-10-21T02:25:03.487255Z`이며
`2026-10-23T02:25:03.487255Z`까지 유효합니다. KST로는 10월 23일
11:25:03.487255까지입니다. 처음 실패한 배치의 생성 시각을 재시도에서도
유지했으며, 게시 시각이나 성공한 재시도 시각으로 TTL을 다시 시작하지 않았습니다.
카탈로그·학습자 입력 버전은 `2026-10-20.1`로 별도 기록합니다.

기존 정적 fixture의 유효 기간은 `2026-10-20T12:00:00Z`부터
`2026-10-22T12:00:00Z`까지이며 양 끝 시각을 포함합니다. API는 실제 UTC
요청 시각으로 확인합니다. 만료 뒤 자동 연장·자동 추천 생성은 없으며,
생성 시각과 기간을 검토해 수동 재게시해야 합니다.

| 상태 | API 표현 |
|---|---|
| 정상 | HTTP 200, `status=OK` |
| 검색 0건 | HTTP 200, `status=NO_RESULTS`, `items=[]` |
| 알 수 없는 과정 ID·추천 0건 | HTTP 404, `error.code=NO_RESULTS` |
| 토큰 없음·만료·서명/issuer/audience 불일치 | HTTP 401, `UNAUTHORIZED` |
| 앱 역할/scope 부족·허용되지 않은 호출 주체 | HTTP 403, `FORBIDDEN` |
| snapshot 만료·미래 생성 시각 | HTTP 409, `STALE_DATA` |
| 잘못되거나 중복된 parameter | HTTP 422, `INVALID_REQUEST` |
| 데이터/인증 키 일시 불가·예상 밖 장애 | HTTP 503/500, `SYSTEM_ERROR` |

유효한 검색의 0건은 실패가 아닌 명시적인 업무 결과입니다. 존재하지 않는
과정 ID, 권한 오류, 만료, 장애를 HTTP 200으로 바꾸지는 않습니다. 오류는
로그에 남기고, 예상 밖 예외는 내부 상세를 노출하지 않은 채 request ID와
함께 반환합니다. 응답 캐시는 `no-store`입니다.

Foundry의 현재 OpenAPI 실행 경로는 일부 non-2xx를 자연어 응답 대신
상위 `tool_user_error`/`tool_server_error`로 중단합니다. 실제 unknown-course
404와 인증 오류는 이 플랫폼 오류로 보일 수 있으므로 호출 측은 이를 숨기지
말아야 합니다. 모든 장애 상태의 자연어 상담 안내까지 완료된 것으로
해석하면 안 됩니다. 단순 검색 0건은 명시적인 `NO_RESULTS` 응답으로 처리합니다.

## 로컬 실행과 검증

저장소 루트의 PowerShell에서 실행합니다. 로컬 검증은 Python 3.14,
배포 대상은 Python 3.12입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r .\requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s .\tests -v
.\.venv\Scripts\python -m compileall -q .\api .\agent
```

실제 앱 기동에는 `AZDEMY_TENANT_ID`, `AZDEMY_API_CLIENT_ID`,
`AZDEMY_PRINCIPAL_LEARNERS` 환경변수가 필요합니다. 매핑 값은
`{"허용할-object-id":"learner-a"}` 형식입니다. 테스트는 서명된 로컬 JWT와
고정 시계·의존성 교체를 쓰며, 인증을 건너뛰는 앱 실행 모드는 없습니다.

```powershell
.\.venv\Scripts\python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

## Private 게시와 상담 실행

[Linux SSH와 SOCKS](../infra/README.md#linux-ssh와-socks)의 터널 두 개를 먼저
실행합니다. 저장소 루트에서 다음 명령을 사용합니다. Entra 앱 생성·역할
배정 권한이 없으면 중단하며 API key·공개 접근으로 전환하지 않습니다.

```powershell
.\infra\configure-api.ps1 -ApiName $ApiName -ToolPrincipalId $ToolPrincipalId
.\.venv\Scripts\python .\infra\package_api.py --output "$env:TEMP\azdemy-api.zip"
.\infra\publish-api.ps1 -ApiName $ApiName -Package "$env:TEMP\azdemy-api.zip"
.\agent\publish.ps1 -ApiClientId $ApiClientId -ApiUrl $ApiUrl -ProjectEndpoint $ProjectEndpoint
```

`$ApiName`·`$ApiUrl`·`$ProjectEndpoint`는 [Bicep 배포 출력](../infra/README.md#빌드와-배포),
`$ToolPrincipalId`는 새 환경에서 확인한 실제 호출 주체, `$ApiClientId`는
`configure-api.ps1`의 응답값을 사용합니다. 로컬 OpenAPI에는 고정 배포 주소가 없으며,
Agent 정의 생성 시 명시한 HTTPS API URL을 `servers`에 넣습니다.

계정·프로젝트·endpoint를 새 환경에서 재사용할 때는 각 스크립트의 명시적
parameter와 앱의 server URL을 해당 환경에 맞춰 검토해야 합니다.
`api-config.bicep`의 appsettings는 데모 설정 전체를 관리합니다. 별도 설정이
있는 앱에 검토 없이 적용하지 않습니다. 메인 인프라 재배포 뒤에는 API
구성 단계를 다시 적용합니다. 패키지는 Linux CPython 3.12 wheel을 담고
Windows 가상환경이나 키를 포함하지 않습니다.

현재 확인 대상 버전은 `education-consultant:6`입니다. 새 게시 때 반환된
버전 번호를 명시해서 호출합니다.

```powershell
.\agent\invoke.ps1 -ProjectEndpoint $ProjectEndpoint -AgentVersion $AgentVersion -Message '내 추천 교육과 추천 이유를 알려줘.' -OutputFile "$env:TEMP\azdemy-response.json"
.\agent\invoke.ps1 -ProjectEndpoint $ProjectEndpoint -AgentVersion $AgentVersion -Message 'SYN-DEV-001과 SYN-DEV-002를 비교해줘.' -OutputFile "$env:TEMP\azdemy-comparison.json"
```

스크립트는 액세스 토큰을 메모리와 curl 표준입력으로만 전달합니다.
출력 파일에는 합성 도구 결과·답변·사용량이 포함되며 토큰은 저장하지 않습니다.
HTTP 오류와 streaming의 실패 종료 이벤트는 성공으로 처리하지 않습니다.
App Service 로컬 진단은 1일·HTTP 로그 25MB로 설정했습니다. 조직 정책의
중앙 로그 저장·30일 보존과는 별개입니다.

## 검증 범위

### 2026-10-22 Azdemy 재배포 검증

API 배포 `4d080331-8d58-4d1b-b0cf-e4699e2564d2`의 완료·활성 상태와
서버의 API·공유 패키지 Python 12개 파일의 SHA-256 일치를 확인했습니다.
실제 Prompt Agent v6의 지시문, Azdemy API 스키마와 Managed Identity 도구를
조회했습니다. 모델과 API 권한·학습자 매핑은 변경하지 않았습니다.

Native Pipeline이 생성한 `fabric-4bf533b7-6664-476b-bbed-3479edfb2057`을
수동 게시하고 API의 completed receipt를 확인했습니다.
생성 시각은 `2026-10-22T06:42:21.591857Z`, 만료는
`2026-10-24T06:42:21.591857Z`입니다. v6의 실제 응답 5개를 이 export와
대조해 추천 순위·이유 원문·근거, 의무교육 분리, 과정 비교·누락 가격,
영어·자막·마감 조건, 타 학습자 조회 거절과 검색 0건을 확인했습니다.
F4를 Paused로 바꾼 뒤 추천 상담을 다시 호출해 같은 게시 원본과 일치함을
확인했습니다.

Private API의 토큰 없는 요청과 잘못된 토큰은 401, 외부 직접 요청은
403이었습니다. 로컬 테스트 73개와 Python 컴파일이 통과했습니다.
검색 0건 검증기는 `NO_RESULTS`·빈 items 검사를 유지하면서
“없습니다”와 “찾지 못했습니다”를 모두 명시적 무결과 안내로 검사합니다.
실제 export의 cold-start·만료 시계 재생은 로컬 검사이며, live identity나
서버 시계를 바꾸지 않았습니다. 강제 장애·Playground 브라우저·OBO는
이번 실제 시험 범위에 넣지 않았고, 추가 자동 생성 평가 suite도 만들지 않았습니다.

### 2026-10-21 실제 Fabric 연동 검증

최종 소스 기준 로컬 테스트 58개와 Python 컴파일이 통과했습니다. API 구성·
Fabric 네트워크 Bicep 빌드와 관련 PowerShell 스크립트 5개의 구문 검사도
통과했습니다. Fabric PLS는 Bicep 타입 정의가 없어 BCP081 경고가 남지만,
공식 API 형태와 실제 배포 성공을 별도로 확인했습니다.

최종 Linux Python 3.12 패키지 배포는
`4d71a35e-6b84-4574-a3a2-71e8947a193e`, 상태 4·complete·active입니다.
Private SCM에서 실제 `api/main.py`, `api/service.py`, `api/publication.py`가
로컬 최종 파일과 같은지도 확인했습니다.

실제 Fabric 원본과 추천·비교·검색·타 학습자 거절·무결과 상담 5개를
대조했습니다. 추가로 F4를 Paused 상태로 둔 뒤 최종 배포의
`education-consultant:5`를 호출해 전체 추천 API payload와 답변의 이유·근거·
생성 시각·유효 기간이 원본과 같은지 검사했습니다. 최종 확인 응답 ID는
`resp_0f52f6b759c3fe4e006ad87a5a1d2481958d3668cea3b69561`입니다.

실제 배치 key 재실행의 Delta 중복·건수와 export bytes 불변, 동일 버전
재게시, checksum 손상 거절과 이전 정상 포인터 유지, 명시적인 이전 버전
rollback·재활성화, 코드 패키지 교체·앱 재시작 후 지속 저장을 확인했습니다.
Windows의 동시 pointer 읽기·교체 경합은 reader와 writer가 같은 게시 lock을
사용하도록 보완했고 회귀 테스트와 최종 배포를 다시 확인했습니다.

최종 검사 중 로컬 DNS·SSH 연결이 끊겨 한 번의 추가 상담 호출은 HTTP 000으로
실패했습니다. 이를 성공으로 집계하지 않았고, 연결 복구·최종 패키지 재배포 후
별도 응답 파일로 다시 실행해 위의 최종 성공 결과를 확인했습니다.
실제 청구액, 전체 국내 처리·저장 준수, workspace outbound 격리,
최종 사용자 OBO와 실제 추천 품질은 미검증입니다.

### 2026-10-20 기존 정적 fixture 검증 기록

2026-10-20 Playground에서 token rate limit이 보고돼 기존 Terra 배포의
capacity를 10에서 100으로 올렸습니다. 관리 API에서 `Succeeded`,
100,000 TPM·100 RPM을 확인했습니다. 모델·버전·GlobalStandard SKU는
변경하지 않았습니다. 실제 토큰 사용량에 따른 과금은 유지되며, 이 한도가
429 발생 방지나 보장 처리량을 뜻하지는 않습니다.

2026-10-20에 로컬 테스트 31개, Python 컴파일, Bicep lint, PowerShell
구문 검사가 통과했습니다. 최종 API ZIP 배포 상태는 `4`(성공)이며
`education-consultant:4`의 실제 상담 5개를 원본 JSON과 대조했습니다.
Private API의 토큰 없는 요청은 HTTP 401, 외부 직접 요청은 HTTP 403입니다.
최종 API 조회 역할 배정은 실측 account MI 1개만 남아 있습니다.

로컬 테스트는 REC-01~05, AGT-01~06의 조회 범위, DAT-02 참조 무결성,
PIP-05 기간, SEC 인증 경계를 검사합니다. REC-06 피드백과 실제 Fabric
학습·게시·rollback은 이번 읽기 전용 데모에 포함하지 않습니다.

실제 Private 상담에서 추천 조회, 원문 순위·이유와 근거 보존, 의무교육
분리, 과정 비교, 언어별 검색, 마감·선수 과정 조건, 다른 직원 요청 거절,
누락된 강사·가격의 확인 불가 안내, 검색 0건 안내를 확인했습니다.
미존재 과정 `SYN-DEV-999`는 원래 API의 HTTP 404·`NO_RESULTS`를 포함한
Foundry `tool_user_error`로 종료됐으며, 자연어 답변을 만들지 않았습니다.
저장된 최종 응답 파일을
`live-recommendations.json`, `live-comparison.json`, `live-search.json`,
`live-denial.json`, `live-noresult.json`으로 같은 폴더에 두면 다음 검사를
재실행할 수 있습니다.

```powershell
.\.venv\Scripts\python -m agent.verify_responses --response-dir $ResponseDirectory
.\infra\verify.ps1
```

실제 Fabric 결과의 상담 검증에는 정적 fixture 대신 해당 export를 명시합니다.
도구 payload와 답변의 순위·이유·근거·provenance를 그 버전과 대조합니다.

```powershell
.\.venv\Scripts\python -m agent.verify_responses --response-dir $ResponseDirectory --release-dir $Export
```

Cold-start·stale·강제 시스템 장애·다른 호출 주체의 JWT 거절은 로컬 테스트
근거입니다. 실제 Azure에서 A를 B로 전환하거나 장애를 주입하지 않았습니다.
Foundry Playground의 브라우저 전체 흐름, 최종 사용자 OBO, 실제 청구액은
미검증입니다.

추가 유료 Azure 자원은 만들지 않았습니다. 기존 VM·Bastion·Search 등은
계속 과금되며 `expiresOn=2026-10-22`는 자동 삭제 예약이 아닙니다. 전용
Entra 앱도 RG와 별개이므로 시연 종료 뒤 삭제 승인 범위에 포함해야 합니다.
