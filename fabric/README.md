# Azdemy Fabric 추천 배치

2026-10-22 Azure 전용 RG를 삭제했으며 기존 Fabric workspace·capacity는 유지합니다.
다음 Azure 배포는 `rg-azdemy-rec-demo-krc`와 `vm-azdemy-jump`를 사용합니다.
아래 과거 검증 결과는 삭제한 API가 현재 실행 중이라는 의미가 아닙니다.
새 자원과 Private 연결을 배포·검증한 뒤 게시 절차를 실행해야 합니다.

기본 Spark ML 콘텐츠 기반 모델을 학습한 뒤, 승인 대상으로 선택한 모델로
별도 배치를 실행합니다. 과정 30개와 학습자·이력·정책은 모두 합성입니다.
품질 개선이나 실제 직원 대상 추천 품질을 증명하는 작업은 아닙니다.

## Fabric UI에서 수동 배치 실행

`ws-genius-rec-demo`에서 **`genius-recommendation-batch`** Pipeline을 열고
상단 **Run**을 선택합니다. 자동 예약은 없으며
**Spark Job Definition `genius-recommendation-spark-job`** 하나를 실행합니다.
현재 Pipeline에는 Notebook activity가 없습니다. 별도 입력 없이 등록 모델 버전 1로
추천 생성·검증·Lakehouse export를 실행합니다. 모델 재학습과 API 게시는 하지 않습니다.

1. Pipeline을 열어 Spark Job Definition activity `Generate_and_validate_recommendations`를 확인합니다.
2. **Run**으로 수동 실행합니다. F4가 Active 상태여야 하며 Spark 실행 비용이 발생합니다.
3. 실행 기록에서 Pipeline `Completed`와 Spark activity `Succeeded`를 확인합니다.
4. Lakehouse의 `Files/batches/<Pipeline RunId>/export`에서 새 결과를 확인합니다.

각 수동 실행은 Pipeline RunId를 batch key로 사용하고 TriggerTime을 기준 시각으로
전달합니다. 같은 실행의 재시도에서는 key와 실제 생성 시각을 유지하며, 새 Run은
별도 결과를 생성합니다. 결과의 최대 유효 기간은 실제 생성 시각부터 48시간입니다.
기존 API snapshot의 날짜를 연장하거나 자동 교체하지 않습니다.

Pipeline ID는 `909a63d5-31a0-4caa-be7b-19c6bfe7c85c`입니다.
2026-10-21 native Spark 검증 Run `ff13b193-3a34-417a-b71b-078ffdd7f8a4`는
`Completed`, activity는 `Succeeded`로 끝났습니다. 새 결과 버전은
`fabric-ff13b193-3a34-417a-b71b-078ffdd7f8a4`이며, 학습자 A의 모델 추천 3건과
직무 cold-start 정책 추천 3건을 검증했습니다. 현재 API 활성 버전
`fabric-0672c7fa738b44538e04`는 바뀌지 않았습니다.

Delta 테이블은 여러 batch의 행을 함께 보관합니다. 실행별 결과를 확인하려면
SQL에서 `batch_key`를 해당 Pipeline RunId로 제한합니다. 의무교육은 일반
추천 순위와 별도이며 기존 API에서 분리해 반환합니다.

```sql
SELECT [rank], course_id,
       JSON_VALUE(candidate_json, '$.reason') AS reason
FROM dbo.genius_recommendations
WHERE batch_key = 'ff13b193-3a34-417a-b71b-078ffdd7f8a4'
  AND mode = 'personalized'
  AND subject = 'learner-a'
ORDER BY [rank];
```

Spark job은 승인된 workspace 전용 Workspace Identity로 실행합니다.
이 identity에는 해당 workspace의 Contributor만 부여했고
`genius-rec-demo-spark-wi` 연결을 사용합니다. API key·클라이언트 secret은
만들지 않았고 tenant 설정과 Foundry account MI·API 권한은 바꾸지 않았습니다.
API에 새 결과를 반영하려면 별도의 검증·게시 승인이 필요합니다.
실패한 Pipeline 결과를 정상 게시나 cold-start로 대체하지 않습니다.
Lakehouse 탐색기의 기존 `Unidentified` 표시 문제는 이 Pipeline 추가로
해결됐다고 주장하지 않으며, 테이블의 조회·결과 검증과 구분합니다.

정의는 [pipeline.py](pipeline.py)에서 생성합니다. 운영자 명령은 Pipeline을
생성하거나 명시적으로 갱신하며 실행·예약·API 게시를 수행하지 않습니다.
같은 이름이 이미 있으면 기본 동작은 중복 생성·덮어쓰기 거절입니다.
`--update`는 state에 기록된 동일 Pipeline만 수정하며 이전 정의를 저장소 밖에 보관합니다.

```powershell
.\.venv\Scripts\python -m fabric.pipeline --state $State
```

## Notebook 없는 Spark 배치 구성

현재 경로는 `수동 Pipeline → Spark Job Definition → Python 배치 → Delta·export`입니다.
학습 Notebook은 별도로 유지합니다. 기존 배치 Notebook은 복구용으로 남아 있지만
Pipeline이 참조하거나 실행하지 않습니다.
수동 실행은 Pipeline의 **Run**을 사용합니다. Spark Job Definition 자체를
인자 없이 직접 실행하면 Pipeline이 전달할 batch key·기준 시각이 없어 실패합니다.

Spark Job Definition ID는 `90fed26c-3efc-4107-9f2b-6b2c06d4ce2c`입니다.
진입점은 [spark_batch_main.py](spark_batch_main.py), 공유 추천 로직은
[azdemy_recommendations](../azdemy_recommendations/)에 있습니다.
Spark job 런타임에는 Notebook의 `/lakehouse/default/Files` 마운트가 없었습니다.
실제 Hadoop 기본 파일시스템의 workspace·Lakehouse ID를 검증한 뒤,
Entra 기반 파일 마운트를 만들고 결과 저장을 마치면 해제합니다.
NotebookUtils의 파일시스템 라이브러리만 사용하며 Notebook cell이나
다른 Notebook을 실행하는 호출은 없습니다.

Fabric의 Python Spark job `additionalLibraryUris`는 `.py`만 허용해
공유 패키지 ZIP 등록을 거절했습니다. 진입점은 동일 Lakehouse에서 버전별 패키지를
읽고 SHA-256을 대조한 뒤, Apache Spark가 지원하는 `SparkContext.addPyFile`
방식으로 로드합니다. 런타임 `pip install`, secret·SAS, 공개 접근 전환은 없습니다.
패키지·코드 버전은 결과 provenance에 남습니다.

```powershell
.\.venv\Scripts\python -m fabric.spark_definition --state $State
.\.venv\Scripts\python -m fabric.pipeline --update --state $State
```

위 명령은 승인·구성된 기존 Spark job·Workspace Identity 연결을 갱신하는
명령입니다. 다른 workspace의 자원이나 tenant 정책을 자동 생성·수정하지 않습니다.
새 Workspace Identity가 필요하면 workspace admin이 별도 승인 아래 생성하고,
해당 workspace Contributor와 Spark Job Definition용 WorkspaceIdentity 연결만
설정해야 합니다. 기존 Foundry account MI를 이 identity로 대신하지 않습니다.

이 환경에서 UI가 실제 저장한 native activity type은
`FabricSparkJobDefinition`입니다. 공개 REST 참조의 `SparkJobDefinition`과 달라
실행 접수 전 거절됐으며, UI 저장본으로 원인을 확인한 뒤 실제 형태로 맞췄습니다.
운영 환경이 달라지면 문서 이름만 바꾸지 말고 UI 정의와 실제 실행을 함께 확인합니다.

REST에서 수동 실행을 검증할 때는 Job Scheduler에 빈 본문 `{}`를 보냅니다.
이전 Notebook 예제의 `OwnerUserPrincipalName`·`OwnerUserObjectId`를 강제로
넘기면 이 경로에서는 `UserAccessTokenException`이 발생했습니다. 해당 필드 없이
실행한 실제 Spark `submitter`가 workspace identity 서비스 주체임을 확인했습니다.
개인 사용자 토큰을 connection에 저장하거나 key로 대체하지 않습니다.

## 저장 위치와 권한

| 대상 | 위치 |
|---|---|
| 원본 합성 JSON | 같은 Lakehouse의 `Files/inputs/<입력 hash>` |
| 버전별 실행 코드 | `Files/code/<코드 hash>` |
| 학습 모델·실험 | 같은 Fabric workspace의 MLflow |
| 추천 결과 | Lakehouse Delta `genius_recommendations` |
| 완성된 export | `Files/batches/<batch key>/export` |
| API 조회용 복사본 | 기존 App Service의 `/home/data/genius-recommendations` |

모델 URI·버전·입력 hash·정책 버전·실행 ID는 결과 provenance에 남습니다.
API는 요청마다 Spark를 실행하거나 OneLake를 조회하지 않습니다.
배치 결과를 JSON으로 복사하는 구조이며 production Serving DB를 도입하지 않습니다.

운영자는 Entra 인증으로 적재·실행·게시합니다. API 조회는 기존 Foundry
account MI와 합성 학습자 A 매핑을 유지합니다. 운영자 자격 증명을 API나
Notebook에 저장하지 않으며 API key·SAS를 사용하지 않습니다.

## 실행 전 조건

[승인 범위](../docs/requirements.md#2026-10-21-fabric-연동-승인과-범위)를
먼저 확인합니다. F4의 Paused 상태를 해제하기 전 사용 시간을 승인받아야 합니다.
기존 Jump host·Bastion·SSH host key를 재사용합니다.

전용 workspace는 F4에 직접 배정해 생성합니다. 중지된 capacity에는 workspace를
생성할 수 없으며, 실패를 피하려고 다른 리전의 shared capacity에 먼저 생성하지
않습니다. Private Endpoint와 DNS를 구성한 뒤 inbound 공개 접근 차단의 전파를
실제로 확인해야 합니다. 승인된 동일 요청이 내부에서 200, 외부에서
`403 RequestDeniedByInboundPolicy`인지 확인한 뒤 합성 데이터를 적재합니다.

Workspace Private Link는 inbound 경로입니다. 테넌트 전체 차단이나 Spark의
outbound 격리를 뜻하지 않습니다. West US 3의 tenant 메타데이터는 합성 데모
예외로 승인됐으며 국내 처리·저장 준수를 주장하지 않습니다.

## 운영자 명령

저장소 루트의 PowerShell에서 실행합니다. `$State`는 저장소 밖에 둔 실행
inventory JSON 경로이고 `$Export`는 합성 export를 내려받을 디렉터리입니다.
둘 다 토큰을 저장하지 않습니다. 같은 state의 batch key를 유지해야 재시도가
새 실행으로 둔갑하지 않습니다.

```powershell
.\.venv\Scripts\python -m fabric.run start --state $State
.\.venv\Scripts\python -m fabric.run workspace --state $State
```

[fabric-private.bicep](../infra/fabric-private.bicep)은 기존 VNet·API·capacity를
재배포하지 않는 추가 템플릿입니다. 새 workspace ID를 parameter로 지정해
what-if에서 PLS·PE·DNS 신규 생성만 확인한 뒤 배포합니다. 기존 서비스의
변경·삭제가 있으면 진행하지 않습니다.

[Private 접속](../infra/README.md#linux-ssh와-socks)과 외부 차단 검증을 마친 뒤:

```powershell
.\.venv\Scripts\python -m fabric.run deny --state $State
.\.venv\Scripts\python -m fabric.run prepare --state $State
.\.venv\Scripts\python -m fabric.run train --state $State
.\.venv\Scripts\python -m fabric.run batch --state $State
.\.venv\Scripts\python -m fabric.run export --state $State --output $Export
.\infra\publish-snapshot.ps1 -State $State -Export $Export -ApiName $ApiName
.\.venv\Scripts\python -m fabric.run stop --state $State
```

`train` 후 state에 기록된 구체적인 모델 URI·등록 버전을 검토한 뒤 `batch`를
실행합니다. `latest`나 이름만으로 모델을 자동 선택하지 않습니다.
`batch` 재시도는 같은 key·기준 시각·기존 생성 시각을 유지합니다.
`export`는 실제 완료된 작업이 기록된 state에서만 실행합니다.

기본 인증 도구는 Azure CLI입니다. 2026-10-21 실행 도중 공유 설치의
`CLI2` Python 실행 파일이 없어져 명령이 실패했습니다. 공유 설치를 변경하지
않고, 같은 tenant·운영자임을 확인한 기존 Azure Developer CLI를 명시적으로
선택해 REST 작업을 복구했습니다. 토큰이 없거나 권한이 다르면 중단하며
다른 identity나 key로 자동 전환하지 않습니다.

```powershell
$env:AZURE_DEV_USER_AGENT = 'microsoft_foundry_skill'
.\.venv\Scripts\python -m fabric.run prepare --auth-cli azd --state $State
```

`--auth-cli azd`는 적재·조회·게시와 ARM REST 기반 자원 재개·중지에 적용됩니다.
Bastion native tunnel과 App Service 재시작은 기존 Azure CLI를 사용합니다. 실제 실행 도중
Azure CLI 설치가 다시 사용 가능한 상태가 됐지만, 공유 설치 복구는 이 작업에서
수행하지 않았습니다.

최초 시간 제한이 지난 뒤 재개하려면 원래 실행 기록을 보존하고 새 승인을
받아야 합니다. 2026-10-21에는 사용자가 해당 세션에서 작업하는 동안 유지하도록
별도로 승인했습니다. 이 범위는 명시적인 `start --session-window`로 시작하고
활성 세션이 끝나면 `stop`으로 정리합니다. 기존 2시간 deadline을 뒤에서
덮어쓰지 않으며, 이전 시작·종료 기록은 state의 `execution_history`에 남습니다.

실제 실행에서 Fabric 런타임이 이미 `fabric` Python namespace를 로드하고
있어 동일 이름의 업무 패키지를 import할 수 없었습니다. 공통 추천 코드는
[azdemy_recommendations](../azdemy_recommendations/)에 두고 API·Notebook이
같이 사용합니다. `fabric` 디렉터리는 로컬 운영자 명령과 Notebook 정의용입니다.
Spark Delta 입출력은 Python 드라이버의 `/lakehouse/default` 경로가 아니라
실제 runtime workspace·Lakehouse ID를 확인한 뒤 같은 Lakehouse의
`Tables/genius_recommendations` 상대 경로를 사용합니다.

## 게시와 실패 처리

App Service에는 스키마·참조·입력 hash·추천 이유를 검사한 완성된 release만
전송합니다. API는 공개 write endpoint를 추가하지 않습니다. 운영자 전용 SCM에
incoming bundle과 요청을 전송하고 앱을 재시작하면, API의 Python 3.12 환경이
전체를 검증한 뒤 활성 포인터를 전환합니다. 이 방식은 무중단 배포가 아닙니다.

검증 실패나 끊긴 전송은 이전 정상 포인터를 변경하지 않습니다. 게시자는 서버의
해당 request ID 결과를 확인하며 실패·timeout을 성공으로 보고하지 않습니다.
API 요청 하나는 변경 불가능한 release 하나를 읽습니다. 활성화 비교·전환은
게시 lock과 expected-current 값으로 직렬화합니다.

[publish-snapshot.ps1](../infra/publish-snapshot.ps1)은 파일 전송, 저장소 표준
Azure CLI 재시작, 개별 서버 receipt 확인을 순서대로 실행합니다.
`$ApiName`은 새 [배포 출력](../infra/README.md#빌드와-배포)의 실제 앱 이름입니다.
직접 `fabric.run`으로 게시·확인·복구할 때도 `--api-name $ApiName` 또는
`AZDEMY_API_NAME` 환경변수를 지정해야 합니다. 고정된 이전 hostname으로
자동 연결하지 않으며 SCM 요청은 지정한 앱의 hostname만 허용합니다.
API의 게시 설정 키는 `AZDEMY_PUBLICATION_ROOT`이고 기존 저장 경로
`/home/data/genius-recommendations`와 Delta 테이블 이름은 변경하지 않습니다.
낮은 수준의 `fabric.run publish`는 전송 후 `status=pending`만 기록합니다.
`az webapp restart` 후 `fabric.run confirm`이 해당 request ID·버전의
`completed` receipt를 확인해야 게시 성공입니다. ARM 재시작 HTTP 200이나
토큰 없는 API의 401만으로 활성화 성공을 판단하지 않습니다.
실행 중 일부 직접 호출에서 새 startup 처리가 확인되지 않아 timeout이
발생했으며, 최종 PowerShell 절차로 실제 receipt까지 확인했습니다.

유효 기간은 최대 48시간입니다. 기존 정상 결과가 만료되면 API는 409를 반환합니다.
장애 때 cold-start로 전환하지 않습니다. 활성 버전과 직전 정상 버전을 유지하며,
검토 전 실행 이력·실패 원인·이전 export를 자동 삭제하지 않습니다.

같은 배치의 재실행은 기본 동작입니다. 새로운 입력·모델로 별도 결과를 만들려면
운영자가 `batch --new-batch`를 명시합니다. 이는 새 실제 실행이며 기존 결과의
생성 시각이나 만료를 수정하는 명령이 아닙니다.

최초 전환 시에만 기존 배포 snapshot을 만료·내용 변경 없이 지속 저장 영역으로
옮기는 `bootstrap`을 사용할 수 있습니다. 활성 release가 이미 있으면 거절합니다.
이는 실패 안전한 이전 버전 보존 절차이며 실제 Fabric 생성 결과가 아닙니다.

이전 정상 버전으로의 복구는 다음과 같이 명시적으로 실행합니다. 해당 버전이
만료됐으면 복구하지 않고 실패하며, 정상 조회에서 자동으로 Mock으로 바꾸지 않습니다.

```powershell
.\infra\publish-snapshot.ps1 -State $State -Rollback -ApiName $ApiName
```

완료한 export를 내려받고 필요한 게시를 마쳤다면 `pause`로 F4만 먼저 중지할 수
있습니다. API가 살아 있는 동안 Spark 실행 없이 snapshot 조회가 유지되는지
검증한 뒤 `stop`으로 Jump host를 정리합니다.

## 검증 범위

```powershell
.\.venv\Scripts\python -m unittest discover -s .\tests -v
.\.venv\Scripts\python -m compileall -q .\api .\fabric .\agent
.\.venv\Scripts\python -m agent.verify_responses --response-dir $Responses --release-dir $Export
```

로컬 검증은 실제 Spark·Delta·MLflow 실행을 대신하지 않습니다. Notebook 완료,
Delta 값 대조, Private 게시·재시작·rollback, API·Foundry 답변까지의 실측은
각각 별도 증거를 남겨야 합니다. 완료하지 않은 항목은 미검증으로 보고합니다.

## 2026-10-22 Azdemy 배포 검증

기존 workspace·Spark Job Definition·수동 Pipeline을 그대로 사용했습니다.
공유 Python 패키지는 `azdemy_recommendations`로 바꾸고 새 immutable 코드
경로에 게시했습니다. 카탈로그의 변경은 안내 문구뿐이며, 과정 사실·태그·직무 등
모델 입력 특성이 이전 export와 같음을 확인한 뒤 기존 모델 버전 1을 재사용했습니다.
재학습·새 자원·자동 예약·권한 확대는 하지 않았습니다.

| 항목 | 확인한 결과 |
|---|---|
| 코드 버전 | `ff0db5e7925331c113e25ecb62f8d7a0810ff7ecec210b6a1f364ff2c12ec3c6` |
| Native Pipeline run | `4bf533b7-6664-476b-bbed-3479edfb2057`, Completed |
| 완료 export | `Files/batches/4bf533b7-6664-476b-bbed-3479edfb2057/export` |
| 추천 결과 | 검증된 6건. 충분한 이력의 A와 cold-start B에 각 3개 |
| 게시 버전 | `fabric-4bf533b7-6664-476b-bbed-3479edfb2057`, 수동 게시 completed receipt 확인 |
| 생성·만료 UTC | `2026-10-22T06:42:21.591857Z` / `2026-10-24T06:42:21.591857Z` |
| 무결성 | 입력·코드·모델 버전, manifest checksum, 참조·추천 이유·수강 자격을 실제 export로 검사 |
| 격리 실측 | 같은 인증의 workspace items 요청이 Private 200·외부 `RequestDeniedByInboundPolicy` 403 |
| 구성 보존 | workspace에 Pipeline 1개·Spark Job Definition 1개 유지 |
| F4 중지 후 | 실제 Agent v6 추천 payload와 답변이 게시된 export와 일치 |
| 실행 자원 복구 | F4 Paused·Jump host Deallocated 확인, 검증용 터널 종료. API·Agent·모델·데이터는 삭제하지 않음 |

정책 관리 endpoint의 직접 조회는 403으로 거절돼 정책을 변경하지 않았습니다.
접근 경계는 실제 Private·외부 items 요청으로 확인했습니다.
로컬 회귀 테스트 73개와 Python 컴파일도 통과했습니다.
실제 export를 고정 시계로 재생한 cold-start·만료 검사는 실제 상담 identity
전환이나 서버 시계 변경 시험과 구분합니다.

## 2026-10-21 실제 실행 증거

| 항목 | 확인한 결과 |
|---|---|
| 학습 | 실제 Spark job `278c9695-0bfa-4278-aa24-608c0f105f70` Completed |
| 등록 모델 | `genius-content-baseline:1`, MLflow run `fc0f5679-1f9f-4a9e-b103-90e63b55ebfa` |
| 추천 배치 | `c16e857d-50a0-4f37-b539-24dcb97451ea` Completed, Delta 6건 |
| 동일 key 재실행 | `e79385d3-9abb-4ed4-96dd-219bbc2dff9f` Completed, 건수·중복 검사·export bytes 동일 |
| 게시 버전 | `fabric-0672c7fa738b44538e04` |
| 생성·만료 | `2026-10-21T02:25:03.487255Z` / `2026-10-23T02:25:03.487255Z` |
| 실제 추천 | A의 `SYN-DEV-002`, `SYN-PRD-002`, `SYN-DAT-002`, 순위 1·2·3 |
| 상담 | `education-consultant:5`, 추천·비교·언어 검색·타 학습자 거절·무결과 5개 원본 대조 통과 |
| 실패 안전성 | 실제 checksum 불일치 요청 거절, 활성 버전·직전 정상 버전 불변 |
| 명시적 복구 | 기존 `2026-10-20.1`로 rollback 후 실제 상담 순위 1·7·8 확인, 이후 Fabric 버전 재활성화 |
| 지속 저장 | 코드 ZIP 교체와 앱 재시작 뒤 활성 JSON 보존 확인 |
| 최종 배포 | `4d71a35e-6b84-4574-a3a2-71e8947a193e`, 서버 코드와 로컬 파일 일치 |
| 로컬 검증 | 테스트 58개·Python 컴파일·Bicep 빌드·PowerShell 5개 구문 검사 통과 |
| F4 중지 후 조회 | 최종 실제 상담 응답과 전체 API payload를 게시 원본과 대조해 일치 확인 |
| Native Spark Pipeline | Run `ff13b193-3a34-417a-b71b-078ffdd7f8a4` Completed, activity Succeeded, Notebook activity 0개 |
| Native 실행 주체 | Workspace Identity `dcfed3ba-4a2e-4829-aba2-c6591153f006`, 이 workspace Contributor |
| Native 전환 후 로컬 검증 | 기존 회귀·SJD 패키지·실행 인자·Lakehouse binding·LRO를 포함해 69개 테스트와 Python 컴파일 통과 |

Delta 6건은 A 모델 추천 3건과 직무별 cold-start 정책 3건입니다.
의무교육은 일반 추천과 별도로 API에서 반환합니다.
학습 결과의 실제 업무 품질·MOD-03/04 평가·최종 사용자 OBO·production Serving·
전체 국내 처리 및 outbound 격리는 검증하지 않았습니다.

## 최종 노트북 정리

2026-10-21 사용자의 삭제 요청에 따라 실패·진단용 노트북 4개를 삭제했습니다.
삭제 전 정의와 실행 기록은 저장소 밖의 세션 증거에 보관했습니다.
현재 workspace에 남은 노트북은 다음 두 개입니다.

| 노트북 | 역할 |
|---|---|
| `genius-train-8b1a28b2` | 등록 모델 버전 1을 만든 최종 학습 노트북 |
| `genius-batch-bcfc8277` | 현재 게시 결과와 동일 key 재실행을 검증한 최종 배치 노트북 |

Lakehouse·Delta 결과·완료 export·MLflow 모델·실험은 삭제하지 않았습니다.
삭제 뒤 완료 export bytes와 API 활성 버전이 그대로인지 확인했습니다.
이 정리는 노트북 실행 정책 변경과는 별개입니다. 현재 로컬 운영자 명령은
설정 hash가 달라지면 새 노트북을 만들 수 있으므로, 설정을 바꾸는 실행 전에
동일 노트북 재사용 또는 Pipeline 전환 범위를 확인해야 합니다.

수동 Data Pipeline `genius-recommendation-batch`는 최초 Notebook activity로
검증한 뒤 사용자의 요청에 따라 native Spark Job Definition activity로
전환했습니다. 학습은 배치와 분리합니다. 현재 API 게시자는 운영자의 Private SCM 경로를
사용하므로 API 게시까지 자동화됐다고 설명하지 않습니다. 자동 예약은 없습니다.
