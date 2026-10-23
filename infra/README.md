# Azdemy Private 데모 인프라

2026-10-20 사용자가 승인한 약 2일 유지 구성입니다. 요구사항과 데모 예외는
[requirements.md](../docs/requirements.md)에 기록했습니다.

## 범위

다음 배포 대상은 현재 Azure CLI 구독의 신규 `rg-azdemy-rec-demo-krc`입니다.
Korea Central에 Foundry Standard Setup, Agent subnet delegation과 private tools
network injection을 사용합니다. Search Basic과 Cosmos Serverless를 사용하며
지원 실패 시 더 비싼 SKU나 key 인증으로 자동 전환하지 않습니다.

2026-10-22 기존 `rg-genius-rec-demo-krc`의 삭제를 확인했습니다.
다음 배포의 이름·태그는 `azdemy`를 사용하며, 아래 과거 배포·검증 기록의
`genius` 이름은 당시 실제 값으로 보존합니다. 새 자원을 배포한 기록은 아닙니다.
공용 Fabric capacity·기존 workspace·중앙 로그·Entra 앱은 삭제 대상에서 제외했고,
Foundry·Key Vault의 soft-delete 항목은 purge하지 않았습니다.

최초 인프라 배포는 API 실행 환경까지만 생성했습니다. 이후 Entra API 앱,
FastAPI 조회 코드와 Prompt Agent·OpenAPI 연결을 추가했습니다.
[데모 API 가이드](../docs/demo-api.md)에 설정·게시 명령과 실제 검증 범위,
남은 제한을 구분했습니다. 인프라 검사만으로 상담 기능을 검증할 수는 없습니다.

API key와 Storage Shared Key는 사용하지 않습니다. Linux VM은 공개 IP가
없으며 SSH 공개키 인증을 사용합니다. 개인키는 로컬 사용자 SSH 폴더에만
보관합니다. Bastion Standard 관리용 IP와 NAT outbound IP는 공개 IP이며
업무 데이터 서비스의 공개 접근과 구분합니다.

구독 내 기존 VNet 목록과 충돌하지 않는 `10.72.0.0/16`을 선택했습니다.
현재 다른 VNet·사내망과 peering하지 않습니다. 이후 연결 시 주소 충돌을
다시 확인해야 합니다. Agent subnet은 공식 예제 권장 크기인 `/24`,
Bastion subnet은 `/26`입니다.

## 파일

- [main.bicep](main.bicep): group-scope 배포 진입점과 비밀정보 없는 출력
- [network.bicep](network.bicep): VNet·NAT·NSG·Bastion Standard
- [services.bicep](services.bicep): Private/keyless Foundry·모델·종속 서비스·API 실행 환경
- [private-access.bicep](private-access.bicep): Private Endpoint 6개와 DNS zone 8개
- [project.bicep](project.bicep): 프로젝트·AAD 연결·서비스별 RBAC·Agent capability host
- [jump.bicep](jump.bicep): SSH 전용 Linux VM
- [api-config.bicep](api-config.bicep): API 인증 매핑·Python 시작 명령·로컬 진단 로그
- [configure-api.ps1](configure-api.ps1): 전용 Entra 앱·조회 역할과 실제 tool caller 연결
- [package_api.py](package_api.py): Linux Python 3.12 전용 배포 ZIP 빌드
- [publish-api.ps1](publish-api.ps1): Entra 인증 기반 Private SCM ZIP 게시
- [verify.ps1](verify.ps1): 배포 자원의 management-plane 불변조건 검사
- [validate_template.py](tests/validate_template.py): 컴파일한 ARM의 구성 검사
- [verify_private_network.py](tests/verify_private_network.py): VNet 내부에서 8개 hostname의 Private DNS·TLS 검사

Foundry 구문은 공식 template 19를 참고했습니다. 출처·라이선스는
[THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES)에 있습니다.
Preview Bicep 타입 정의에 누락된 두 속성만 근거를 달아 진단을 억제했습니다.

## 빌드와 배포

PowerShell에서 저장소 루트를 기준으로 실행합니다.

```powershell
az bicep build --file .\infra\main.bicep --outfile "$env:TEMP\azdemy-infra-compiled.json"
az bicep lint --file .\infra\main.bicep
python .\infra\tests\validate_template.py "$env:TEMP\azdemy-infra-compiled.json"
```

배포 parameter JSON은 저장소 밖에 보관합니다. `sshPublicKey`는 전용 로컬
공개키, `operatorObjectId`는 로그인 사용자의 Entra object ID입니다.
`expiresOn`은 새 실행에서 승인받은 정리 검토일로 지정합니다.
개인키를 parameter로 전달하지 않습니다.
구독 ID를 확인하고, 기존 동명 RG를 임의 재사용하지 않습니다.

```powershell
az deployment group what-if --resource-group rg-azdemy-rec-demo-krc --template-file .\infra\main.bicep --parameters "@$ParameterFile"
az deployment group create --resource-group rg-azdemy-rec-demo-krc --template-file .\infra\main.bicep --parameters "@$ParameterFile" --name azdemy-private
.\infra\verify.ps1
```

새 RG 생성과 실제 배포는 별도 승인이 필요합니다. 배포 후 `azdemy-private`의
출력값에서 `apiName`, `apiHostname`, `projectEndpoint`를 읽어 운영 스크립트에
전달합니다. 이름 접미사는 RG ID로 결정되므로 이전 API·Foundry hostname을
다시 사용하거나 새 접미사를 추측하지 않습니다.

```powershell
$deployment = az deployment group show -g rg-azdemy-rec-demo-krc -n azdemy-private -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot read deployment outputs' }
$ApiName = $deployment.properties.outputs.apiName.value
$ApiUrl = "https://$($deployment.properties.outputs.apiHostname.value)"
$ProjectEndpoint = $deployment.properties.outputs.projectEndpoint.value
```

API 설정은 `AZDEMY_*` 환경변수를 사용합니다. 기존 `GENIUS_*` 설정을 읽는
호환 모드는 없으므로 코드와 [api-config.bicep](api-config.bicep)을 함께 배포합니다.
새 Entra 앱 표시명은 `azdemy-rec-demo-api`이며, 기존 앱을 자동 삭제하거나
이름이 다른 앱의 권한을 새 앱으로 복사하지 않습니다.
기존 Fabric workspace·Delta 테이블·게시 저장 경로는 이번 변경에 포함하지 않습니다.
[fabric-private.bicep](fabric-private.bicep)을 사용할 때도 새 검토일을 담은 `tags`를
명시적으로 전달합니다. 기본 태그의 날짜는 최초 데모 검토일이며 자동 예약이 아닙니다.

what-if는 정책 remediation이나 플랫폼 내부 생성 자원의 전체 비용을
보장하지 않습니다. 실패 시 먼저 deployment operation의 원인을 확인합니다.
capability host가 subnet에 service link를 남겼다면 임의 삭제·purge하거나
중복 유료 환경을 만들지 말고 복구 계획을 확인해야 합니다.

## Linux SSH와 SOCKS

첫 PowerShell 창에서 native tunnel을 실행하고 유지합니다.

```powershell
$vmId = az vm show -g rg-azdemy-rec-demo-krc -n vm-azdemy-jump --query id -o tsv
az network bastion tunnel -g rg-azdemy-rec-demo-krc -n bas-azdemy-krc --target-resource-id $vmId --resource-port 22 --port 50022
```

VM Run Command 등 신뢰할 수 있는 management-plane 경로에서 SSH host key
fingerprint를 확인한 뒤, 두 번째 창에서 연결합니다. 개인키 경로는
로컬 전용 키를 가리켜야 합니다. host key 검증을 끄지 않습니다.

```powershell
ssh -i "$env:USERPROFILE\.ssh\azdemy-rec-demo" -p 50022 -N -D 127.0.0.1:1080 -o "UserKnownHostsFile=$env:USERPROFILE\.ssh\azdemy-rec-demo-known-hosts" -o KexAlgorithms=curve25519-sha256 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 demoadmin@127.0.0.1
```

SOCKS5 프록시는 `127.0.0.1:1080`입니다. 브라우저에서 프록시 쪽 DNS 해석도
활성화합니다. 지원하는 curl 클라이언트라면 `--proxy socks5h://127.0.0.1:1080`을
사용합니다. 원래 서비스 hostname과 HTTPS 인증서 검증을 유지합니다.
SOCKS는 Entra 인증이나 API 권한을 우회하지 않으며, 모든 OS 트래픽을
연결하는 VPN도 아닙니다. 사용 후 두 터미널을 종료합니다.

현재 Windows의 `ssh-keyscan`은 서버와 KEX 협상 중 오류가 발생했습니다.
검증에서는 VM Run Command로 읽은 공개 host key를 전용 known-hosts 파일에
기록하고 `StrictHostKeyChecking=yes`로 일치 여부를 확인했습니다.
다른 도구의 기본 known-hosts 파일을 덮거나 host key 검증을 해제하지 않습니다.

## 비용과 2일 뒤 정리

기존 공개 가격 산식을 48시간에 적용하면 VM 48시간 실행 시 인프라 고정성
비용은 약 USD 30.54입니다. GPT-5.6 Terra 상담 200회에 입력 총 200만·출력
40만 토큰을 가정한 USD 8.80과 변동비 여유분 USD 10을 더하면 약 USD 49.34입니다.
약 USD 65를 계획 여유로 볼 수 있지만 새로 확정된 예산 한도나 hard cap은
아닙니다. 세금·환율·계약 할인은 제외하며 모델 호출·RU·로그·전송량과 정책이
설치하는 보안 자원에 따라 달라집니다. 실제 청구를 확인해야 합니다.

VM 정지만으로 Bastion·Search·App Service plan·PE·NAT·IP·디스크 요금은
중단되지 않습니다. `expiresOn=2026-10-22`는 **삭제 예약이 아닌 검토 태그**입니다.
자동 삭제 작업이나 예약 프로세스는 만들지 않았습니다.

시연 종료 후 다음 순서로 정리합니다.

1. 대상 구독과 전용 RG의 자원 inventory를 확인하고 필요한 합성 설정만 보관합니다.
2. 프로젝트 capability host·account에 종속된 network service link의 상태를 확인합니다.
3. 명시적인 삭제 승인 후 전용 RG만 삭제합니다. 중앙 로그 RG나 다른 프로젝트는 제외합니다.
4. RG 삭제 완료와 남은 자원을 확인합니다. Soft-deleted Foundry/Key Vault의 purge는 별도 판단하며 임의 수행하지 않습니다.
5. RG 밖의 전용 Entra 앱 `azdemy-rec-demo-api`와 Foundry가 생성한 Agent Identity·blueprint의 정리 범위를 확인합니다. 앱 삭제는 별도 승인이 필요하며 중앙·공용 앱은 삭제하지 않습니다. 이전 배포의 `genius-rec-demo-api`도 별도 확인 대상입니다.

## 수용 검증

SEC-04·SEC-05: 서비스별 public access와 local/shared key 차단, PE 6개 승인,
Private DNS zone 8개, Jump host 공개 IP 없음, Bastion tunneling 활성화를
management plane에서 확인합니다. VNet 내부에서 실제 DNS 해석과 TLS 도달,
외부에서 데이터 API 차단, SSH host key와 SOCKS forwarding도 별도로 시험합니다.

REC·AGT의 추천·상담·권한 거절·근거·오류 상태는
[데모 API 가이드](../docs/demo-api.md)의 별도 검증을 사용합니다.
합성 데이터·Mock Fabric·Mock 추천 Serving은 그대로 유지합니다.

## 2026-10-20 배포·검증 결과

실제 배포 `genius-private-20261020`은 20:27:59 KST에 `Succeeded`로
완료됐습니다. Azure가 보고한 배포 시간은 33분 40초입니다.
what-if는 전용 RG 안의 신규 생성 58건이었으며 기존 자원의 수정·삭제는
없었습니다. 최종 `az resource list`에는 PE의 NIC·VM disk 등을 포함해
45개 자원이 표시됐습니다. 두 명령의 집계 대상은 다릅니다.

| 항목 | 실제 값·검증 결과 |
|---|---|
| 구독 | `b214e225-c96c-489e-a778-a1f25bd40cdb` |
| 전용 RG | `rg-genius-rec-demo-krc`, Korea Central |
| Foundry account·project | `geniusmda53gutai` / `learning` |
| 모델 | `gpt-5.6-terra`, `2026-07-09`, GlobalStandard, capacity 10 |
| API 실행 환경 | `geniusmda53gutapi.azurewebsites.net`, 이후 FastAPI 코드 게시 완료 |
| Jump host | `vm-genius-jump`, Linux, `10.72.2.4`, 공개 IP 없음 |
| Bastion | `bas-genius-krc`, Standard, native tunnel 활성화 |
| Private Endpoint | 6개 모두 Succeeded·Approved |
| Private DNS | 8개 hostname 모두 `10.72.1.0/24`의 IP로 해석, TLS 1.3 인증서 검증 성공 |
| 공개 접근·인증 | 6개 서비스 public access 차단, Foundry·Search·Cosmos local auth 차단, Storage Shared Key 차단 |
| SSH | 관리 경로의 host key를 고정한 실제 공개키 로그인 성공 |
| SOCKS | localhost 전용 listener와 remote DNS로 Foundry 요청 성공 |
| 인증된 Agent 목록 조회 | SOCKS 경로 HTTP 200, 빈 목록. 같은 토큰의 외부 직접 접속은 public access 차단 HTTP 403 |
| 중앙 로그 | 정책이 `setByPolicy-MCAPSGovernance`를 생성해 기존 중앙 workspace에 allLogs·AllMetrics 연결 |
| 정리 태그 | `expiresOn=2026-10-22`, 자동 삭제 아님 |

첫 Agent 목록 조회는 BYO Cosmos 초기화 관련 timeout을 반환했습니다.
프로젝트 identity·Cosmos 데이터 역할·시스템 컨테이너와 network injection을
점검했고, 설정 변경 없이 재시험한 동일 요청은 HTTP 200을 반환했습니다.
초기 전파·준비 지연이 원인인지는 별도 확정하지 않았습니다. 오류를 정상
응답으로 바꾸거나 Cosmos 공개 접근을 허용하지 않았습니다.

검증용 SSH/SOCKS와 Bastion tunnel 프로세스는 종료했습니다. 재접속용 전용
키와 known-hosts 파일은 로컬 사용자 SSH 폴더에 남겼습니다. Azure VM은
실행 상태로 유지합니다.

이 절은 최초 인프라 배포의 검증 기록입니다. 이후 Prompt Agent
`education-consultant`를 생성해 모델 추론과 Private OpenAPI 조회를 확인했습니다.
최신 결과와 미검증 항목은 [데모 API 가이드](../docs/demo-api.md)에 기록합니다.

## 2026-10-21 Fabric 추가 구성

기존 Korea Central F4 `pocfabcap01`에 전용 `ws-genius-rec-demo`를 직접
배정했습니다. Workspace ID는 `a9e11b86-dd2e-44ef-9454-461d89793045`,
Lakehouse ID는 `d1a58be0-d465-4ceb-b3d7-f4ae2df84d65`입니다.

[fabric-private.bicep](fabric-private.bicep)의 exact workspace what-if는
PLS·PE·DNS zone·VNet link·zone group의 신규 생성 5건이며,
기존 자원의 변경·삭제는 없었습니다. 배포
`genius-fabric-private-20261021`은 `Succeeded`입니다. Bicep은 해당 Fabric
PLS 타입 정보가 없어 BCP081 경고를 표시합니다. API 버전·속성은 공식
workspace Private Link 예제를 따르며, 실제 Azure 배포 결과도 별도로 확인했습니다.

`pls-genius-fabric`은 이 workspace에만 연결되고 `pe-genius-fabric`은 기존
VNet의 private-endpoints subnet에 있습니다. Workspace 전용 API·OneLake
DNS는 VNet 안에서 각각 `10.72.1.13`, `10.72.1.16`으로 해석됩니다.
실제 합성 JSON 읽기는 내부 HTTP 200, 외부 global·workspace OneLake
endpoint 모두 HTTP 403 `DeniedByPolicy`였습니다. Core Items 조회도
내부 200·외부 403 `RequestDeniedByInboundPolicy`로 확인했습니다.

Tenant 전체 Private Link·공개 접근 설정과 다른 PoC workspace는 변경하지
않았습니다. Workspace inbound는 `Deny`, outbound는 기존 `Allow`입니다.
Spark는 같은 workspace의 검증된 default Lakehouse 상대 경로로 Delta를
읽고 씁니다. 외부 운영자 데이터 전송은 workspace 전용 PE를 사용하지만,
Fabric 내부 Spark가 고객 VNet PE를 사용한다거나 outbound까지 격리됐다고
설명하지 않습니다.

Tenant home region은 West US 3입니다. 사용자는 합성 데모에 한해 해외
tenant 메타데이터를 허용했으며, 이 구성으로 국내 처리·저장 준수를 증명하지
않습니다. F4·공유 자원은 정리 검토일만으로 삭제하지 않습니다.

첫 실행의 승인 시간은 2시간이었지만 실행 도구 세션 재설정으로 로컬 종료
guard가 사라져 제한을 지키지 못했습니다. 10:08 KST에 재개한 자원을
13:29 KST경 중지·할당 해제한 뒤 실측 상태를 확인하고 사용자에게 보고했습니다.
이후 사용자는 남은 작업을 진행하는 동안 유지하도록 별도로 재개를 승인했습니다.
로컬 guard를 Azure의 지속적 종료 예약이나 청구 hard cap으로 설명하지 않습니다.

운영 명령·모델 실행·게시·정리 범위는 [Fabric 가이드](../fabric/README.md)를
따릅니다. 새 capacity·VM·production Serving DB는 만들지 않았습니다.

최종 소스 재배포와 Private 상담 검증을 마친 뒤 ARM 조회에서 F4 `Paused`,
Jump host `Deallocated`를 확인하고 이번 세션의 SSH·Bastion 터널을 종료했습니다.
API·Foundry·workspace·PE·DNS는 보존합니다. F4 중지와 VM 할당 해제만으로
기존 API·Bastion·PE·디스크·OneLake 저장 비용까지 중단되지는 않으며,
실제 청구액은 미확인입니다. 10월 22일 정리 검토와 삭제 승인은 별도입니다.

## Fabric UI 확인과 수동 Pipeline

사용자의 UI 확인 요청으로 기존 F4·Jump host를 재개하고 Edge 전용 프로필에
SOCKS를 연결했습니다. 사용자 확인 중에는 앞 절의 최종 정리 상태와 달리
capacity·VM·터널이 실행 중일 수 있습니다. 종료를 원하면 별도로 정리해야 하며,
수동 Pipeline을 추가했다고 capacity를 자동 재개·중지하는 예약은 만들지 않았습니다.

Workspace의 `genius-recommendation-batch`는 기존 최종 배치 노트북 하나만
실행하도록 처음 구성한 뒤, 사용자 승인에 따라
**Spark Job Definition `genius-recommendation-spark-job` 하나만 실행**하도록
전환했습니다. 현재 Notebook activity는 없습니다.
새 capacity·VM·gateway는 추가하지 않았고 tenant 네트워크 설정과 기존 API
게시 버전도 변경하지 않았습니다. Native Spark Run의 완료·activity 성공과
새 export 검증을 확인했습니다.
UI 실행 방법과 결과 위치는 [Fabric 가이드](../fabric/README.md#fabric-ui에서-수동-배치-실행)를
따릅니다. 자동 예약·재학습·API 자동 게시는 포함하지 않습니다.

Native Spark 실행을 위해 사용자가 별도 승인한 workspace 전용 Workspace Identity와
`genius-rec-demo-spark-wi` connection을 만들었습니다. Entra 서비스 주체
`dcfed3ba-4a2e-4829-aba2-c6591153f006`에는 이 workspace Contributor만 부여했습니다.
Fabric이 identity 자격 증명을 관리하며 클라이언트 secret·API key는 저장하지 않습니다.
Foundry account MI와 전용 API 역할은 변경하지 않았습니다.
정리 승인 때 이 identity·connection도 포함해 검토하되 공용 identity·다른 workspace를
삭제하지 않습니다. Workspace Identity의 수명과 삭제는 Fabric에서 관리합니다.
