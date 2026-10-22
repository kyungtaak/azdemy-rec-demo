# Azdemy 합성 교육 카탈로그

[courses.synthetic.json](courses.synthetic.json)은 6개 카테고리에 5개씩,
총 30개 과정을 담은 초기 데모 데이터입니다. 모든 제목·소개·학습 목표·
커리큘럼·수강 조건은 직접 작성했습니다. **외부 교육기관에서 수집한 데이터나
실제 과정 설명의 번역·변형이 아닙니다.** 실제 교육기관의 개설·수강 자격·
인증 정보를 나타내지 않으며 실제 수강 신청도 불가능합니다.

외부 공개 목록에서는 제목·시간·수준처럼 어떤 필드가 표시되는지만
참고했습니다. 개별 강좌 상세 설명이나 커리큘럼은 수집하지 않았습니다.
따라서 외부 강좌의 상세 정보를 검증했다고 설명하면 안 됩니다.

## 구성과 사용 범위

| 카테고리 | ID 범위 | 과정 수 |
|---|---|---:|
| 소프트웨어 개발 | SYN-DEV-001~005 | 5 |
| 데이터 분석·AI | SYN-DAT-001~005 | 5 |
| 클라우드·인프라 | SYN-CLD-001~005 | 5 |
| 보안 | SYN-SEC-001~005 | 5 |
| 업무 생산성 | SYN-PRD-001~005 | 5 |
| 리더십·커뮤니케이션 | SYN-LDR-001~005 | 5 |

카탈로그는 과정 사실과 공통 수강 조건만 담습니다. 직원·수료 이력·추천
순위·점수·추천 이유는 포함하지 않았습니다. 이후 추가한
[learners.synthetic.json](learners.synthetic.json)과
[recommendations.synthetic.json](recommendations.synthetic.json)이 과정 ID로
연결됩니다. 카탈로그·직원·추천 snapshot은 Private API에 게시하며,
실행·인증·상담 도구 계약은 [데모 API 가이드](../docs/demo-api.md)를 따릅니다.

실제 Fabric 실행은 카탈로그·학습자 JSON과
[recommendation-policy.synthetic.json](recommendation-policy.synthetic.json)을
입력으로 사용합니다. 정책 파일에는 직무별 cold-start 후보와 의무교육 이유만
있으며 학습자 A의 모델 순위를 미리 저장하지 않습니다.
[recommendations.synthetic.json](recommendations.synthetic.json)은 기존 정적
회귀 fixture로 보존하고, 실제 배치 결과는 Lakehouse와 App Service의 별도
버전별 영역에 게시합니다. 현재 입력의 합성 작성 시각을 새로 수집한 시각으로
바꾸거나 정적 fixture 만료를 자동 연장하지 않습니다.

## 필드 계약

| 필드 | 의미 |
|---|---|
| `schema_version` / `data_version` | 필드 구조 버전 / 데이터 snapshot 버전 |
| `created_at` | 합성 snapshot 작성 시각. 외부 사이트 조회 시각이 아님 |
| `scenario_reference_at` | 날짜 시나리오를 재현하는 고정 기준 시각 |
| `categories` / `roles` | 카테고리·합성 직무 코드와 한국어 이름 |
| `id` / `title` / `category_id` | 안정적인 합성 과정 ID·한국어 표시명·카테고리 참조 |
| `skill_tags` | 검색·직무별 후보 선정에 사용할 역량 태그. 추천 이유 자체는 아님 |
| `level` | `beginner`, `intermediate`, `advanced` |
| `duration_minutes` | 양의 정수인 가상 학습 시간. 분 단위 |
| `language` / `subtitle_languages` | 실제로 설정한 가상 강의 언어 / 자막 언어 목록. `ko`, `en` 사용 |
| `summary` / `learning_objectives` / `curriculum` | 자체 작성한 과정 소개·학습 목표·목차 |
| `target_roles` | 내용이 주로 적합한 직무. 접근 권한이 아님 |
| `eligible_roles` | 데모 업무 정책상 수강 가능한 직무. API에서 검증 |
| `prerequisite_knowledge` | 상담에 사용하는 설명형 선수 지식. 자동 수료 판정에 사용하지 않음 |
| `prerequisite_course_ids` | 수료 여부 검증용 필수 선수 과정 ID. 목록의 모든 과정 수료가 필요 |
| `has_hands_on` | 가상 실습 포함 여부. `false`여도 사례 토론·문서 작성 연습은 가능 |
| `enrollment` | timezone을 포함한 모집 시작·종료 시각 |
| `status` | `open`, `closed`, `cancelled`, `upcoming` |
| `is_mandatory` | 합성 정책상 의무교육 여부. 실제 회사 정책이 아님 |
| `detail_path` | 인증된 내부 JSON 상세 조회 경로. 신청 기능이 아님 |
| `source_ref` | `synthetic:<버전>:<과정 ID>` 형식의 내부 근거 식별자. 외부 출처나 실제 기관의 보증이 아님 |
| `is_synthetic` | 파일·과정 모두 `true`. 사용자 표시와 Agent 도구 결과에서도 유지해야 함 |

영어 강의 6개 중 5개는 한국어 자막이 있고 1개는 영어 자막만 있습니다.
한국어 강의 24개 중 1개는 자막이 없습니다. 한국어로 표시한 제목·소개가
강의 언어를 뜻하지 않습니다. 가격·평점·수강생 수·실제 강사·외부 수강
링크는 의도적으로 제외했습니다.

## 고정 날짜와 시연 사례

기준 시각은 `2026-10-20T12:00:00Z`입니다. 테스트는 시스템 현재 시각 대신
이 값을 사용합니다. 실제 API는 UTC 요청 시각을 주입해 모집 기간을
확인해야 합니다. 단순히 `status=open`이라고 해서 날짜 검사를 생략하면
안 됩니다. 모집 가능 범위는 `opens_at <= now <= closes_at`으로 정의합니다.
날짜를 벗어난 과정이나 `cancelled` 과정은 추천 후보에서 제외합니다.
API는 이 정책에 따라 필터링하며 테스트에서 고정 시계를 주입합니다.

| 시험 목적 | 데이터 |
|---|---|
| REC-04 모집 마감 제외 | SYN-DEV-005: 10월 19일 모집 종료, `closed` |
| REC-04 폐강 제외 | SYN-CLD-005: 날짜는 모집 기간 안이지만 `cancelled` |
| REC-04 모집 시작 전 제외 | SYN-LDR-005: 11월 1일 모집 시작, `upcoming` |
| REC-04 직무별 수강 자격 | SYN-LDR-002: `people_manager`만 수강 가능 |
| REC-04 선수 과정 | SYN-SEC-005: SYN-SEC-002와 SYN-DAT-004 모두 수료 필요 |
| REC-04 의무교육 분리 | SYN-SEC-001: 전 직무 대상 의무교육 |
| AGT-01 과정 비교 | SYN-DEV-001·002의 수준·시간·목표·선수 과정 비교 |
| AGT-04 언어 근거 | SYN-DEV-003: 영어 강의·한국어 자막 / SYN-DEV-005: 영어 강의·영어 자막 |
| DAT-02 일관성 | 고유 ID·유효한 참조·순환 없는 선수 과정 |

이 데모의 30개 합성 과정 사실은 허용된 호출 주체에게 모두 조회 가능합니다.
별도 제한 콘텐츠는 없습니다. `eligible_roles`는 수강 자격을 뜻하며 콘텐츠
열람 권한을 대신하지 않습니다. API는 JWT·앱 권한·호출 주체 매핑을 검사하고,
상담 도구는 합성 학습자 A에 고정됩니다.

신규 사용자 대체 추천(REC-05), 개인별 수료 제외, 결과 없음·stale data·
401·403·시스템 오류(AGT-06)는 직원·추천 snapshot과 API 테스트에서
검사합니다. Cold-start 합성 학습자 B는 로컬 fixture이며, 통합 상담의 A를
요청 parameter로 B로 바꿀 수 없습니다.
상담은 합성 과정 사실과 명시적인 내부 근거를 인용하고, 원본에 없는 정보는
확인할 수 없다고 안내해야 합니다. 순위·추천 이유는 별도 추천 데이터에서만
가져옵니다(AGT-05).

## 검증

추가 패키지 없이 저장소 루트에서 실행합니다.

```powershell
python -m unittest discover -s .\tests -p test_course_catalog.py -v
```

테스트는 총 30개·카테고리별 5개, 필드와 타입, 합성 표시, 직무 참조,
선수 과정 순환·잘못된 참조, 언어·자막 구분, 모집 기간·상태, 의무교육·
비교용 사례, 외부 링크·추천 순위·직원 정보의 부재를 확인합니다.
JSON 데이터에는 별도 앱 빌드 단계가 없으며, 이 테스트에서 실제 파일을
파싱해 계약을 검증합니다. 상담 품질이나 API 권한 시험을 대체하지 않습니다.

150개 확장은 30개로 조회·비교 흐름을 확인한 뒤 진행합니다. 실제 카탈로그로
교체할 때는 이용 허가·출처·확인 시각을 별도 기록하고 합성 데이터와
혼동하지 않도록 식별자와 provenance를 구분해야 합니다.
