# 기술 결정·대안 비교·판단 이유

기술 결정은 앞으로 **이 문서 하나에 누적**한다. 개별 ADR 파일을 만들지 않는다. 각 결정에 날짜·상태·비교한 대안·선택 이유·감수하는 단점·재검토 조건을 남긴다. 판단이 바뀌면 기존 기록을 지우지 않고 변경 이유와 대체 결정을 연결한다. 전체 동작 설명은 [v1-design.md](v1-design.md), 실행 방법은 [운영 절차](v1-operations.md)에 둔다. 이 문서에는 선택의 근거와 변경 이력을 남기며 실행 순서·파일 목록은 반복하지 않는다.

| 번호 | 날짜 | 결정 | 상태 |
| --- | --- | --- | --- |
| TD-001 | 2026-09-29 | 버전 Manifest는 JSON, Compose/Workflow는 YAML | 채택 (TD-008에서 필드 축소) |
| TD-002 | 2026-09-29 | 소스 SHA + 이미지 digest + CI 출처를 기록하고 실제 성공 상태는 별도 관리 | **대체됨 → TD-008** |
| TD-003 | 2026-09-29 | 중앙 자동 CD로 전환하며 Backend부터 적용, Worker 제외 | **대체됨 → TD-008·009** (전 서비스 자동 CD) |
| TD-004 | 2026-09-29 | main의 앱 실행 설정 보존 | 원칙 유지, 구현은 TD-008·014로 갱신 |
| TD-005 | 2026-09-29 | SSM + 고정 Git 커밋 archive, S3 없이 전달 | **대체됨 → TD-008** (기존 main의 checkout 방식) |
| TD-006 | 2026-09-29 | 기존 스택 검증·채택 후 Backend만 교체·복구 | **대체됨 → TD-012** |
| TD-007 | 2026-09-29 | 현재 앱의 검사를 활용하고 미구현 검사 계약은 요구하지 않음 | **갱신 → TD-014** |
| TD-008 | 2026-09-29 | 무거운 중앙 CD 엔진 대신 최소 구성으로 재작성하고 전 서비스를 자동 배포 | 채택 |
| TD-009 | 2026-09-29 | 새 이미지 감지는 앱 저장소 PR이 아니라 Cloud의 10분 주기 조회 | 채택 |
| TD-010 | 2026-09-29 | Bash + gh/jq를 release.sh로 분리, Actions dry_run 추가 | 채택 |
| TD-011 | 2026-09-29 | FE는 당분간 `feat/v1` 브랜치 CI를 배포 기준으로 사용 | 채택 (임시) |
| TD-012 | 2026-09-29 | 설정 해시로 바뀐 서비스만 교체, 실패 시 이미지 롤백·실패 이미지 차단 | 채택 |
| TD-013 | 2026-09-29 | 자동 복구되지 않은 장애만 Discord로 알림 | 채택 |
| TD-014 | 2026-09-29 | Backend healthcheck를 `/actuator/health`로 강화 | 채택 |
| TD-015 | 2026-09-30 | CloudWatch 로그·인프라 알람 + Prometheus·Grafana 상세 관측 | 채택 (운영 적용 전) |
| TD-016 | 2026-09-30 | 배포 시 Secret 자동 조회 유지, 실패 시 교체 중단, env·JWT 적용 상태 추적 | 채택 (운영 적용 전) |
| TD-017 | 2026-09-30 | main 보호 규칙 없이 GITHUB_TOKEN으로 자동 병합, 형식 검사는 release.sh에서 수행 | 채택 |
| TD-018 | 2026-09-30 | main의 배포 사전 검사 복원(TLS·ACME·uploads, NAVER 키 필수), 배포는 main에서만 | 채택 (운영 적용 전) |
| TD-019 | 2026-09-30 | AI의 SENTRY_DSN을 선택 키로 주입, 목록에 없는 Secret 키는 계속 전달하지 않음 | 채택 (운영 적용 전) |
| TD-020 | 2026-09-30 | production Environment의 필수 승인자 제거, 배포 승인 없이 자동 배포 | 채택 |
| TD-021 | 2026-09-30 | 변경 감지를 Compose 라벨 대신 마지막 배포의 적용 기록으로 판단 (TD-012 보완) | 채택 (운영 적용 전) |
| TD-022 | 2026-09-30 | GitHub schedule 대신 EventBridge 예약 규칙 + API destination으로 Auto release·Health check 실행 (TD-009 실행 수단 변경) | 채택 (운영 적용) |
| TD-023 | 2026-10-01 | 외부 감시는 유지하되 Actions Health check를 Sentry Uptime Monitoring으로 이전 (같은 날 Route 53 안에서 변경) | 결정 (적용 대기) |

## TD-001 — 버전 Manifest 형식

**맥락:** 기존 main은 YAML에 실제 이미지 SHA를 기록하고, 작업 브랜치는 JSON과 중앙 자동 CD를 준비했다. 사용자는 수정량과 별개로 형식의 적합성을 비교하도록 요청했다.

| 기준 | YAML | JSON |
| --- | --- | --- |
| 수동 작성·설명 | 간결하고 주석 가능 | 괄호·따옴표가 많고 주석 없음 |
| 자동 갱신 | 가능. 주석·표현 형식을 보존하려면 적절한 도구 필요 | 표현 방식이 작아 일관된 직렬화가 쉬움 |
| 타입 해석 | 따옴표 없는 값과 parser/schema 설정에 주의 | 문자열·숫자 등을 문법으로 구분 |
| 변경 검토 | 짧은 파일에서 읽기 편함 | 작은 Manifest라면 충분히 검토 가능 |
| 충돌·검증 | 안정적 출력·스키마 검증 별도 필요 | 동일. 형식만으로 Git 충돌·잘못된 값이 방지되지 않음 |

**선택:** `production-manifest.json`을 단일 목표 버전 기록으로 사용한다. Compose와 GitHub Workflow는 해당 도구의 YAML을 유지한다.

**이유:** 변경 주체는 CI이고 내용은 작은 정형 데이터다. 버전·출처를 기계가 일관되게 생성/소비하는 데 JSON의 제한된 표현이 적합하다. 사람의 변경 이유는 PR과 이 문서에 남긴다. 기존 Python 코드 수정량이 작다는 것은 부수적 이점이며 결정의 주된 근거가 아니다.

**감수하는 단점:** 수동 편집이 더 장황하고 파일 안에 주석을 달 수 없다. 키 순서·들여쓰기를 고정하고 중복 키·필수 필드·타입 검증을 별도로 구현해야 한다. YAML도 안전한 parser와 동일한 검증으로 자동 CD에 사용할 수 있다.

**재검토:** 사람이 빈번하게 직접 수정하거나 필드 옆의 운영 주석이 필수 요구가 되는 경우. JSON과 YAML을 같은 버전의 원본으로 동시에 유지하지 않는다.

근거: [JSON RFC 8259](https://www.rfc-editor.org/rfc/rfc8259), [YAML 1.2.2 명세](https://yaml.org/spec/1.2.2/).

## TD-002 — 무엇을 버전으로 기록할 것인가

**상태:** 대체됨 → TD-008. 아래는 당시 결정이며 현재 실행 지침이 아니다.

**대안:** SHA 태그만 기록 / digest만 기록 / SHA·digest·CI 출처를 함께 기록.

**선택·이유:** Git에는 네 서비스의 소스 SHA와 digest, 자동 갱신 대상 Backend의 성공 main CI run ID를 기록한다. SHA는 소스 추적, digest는 실제 이미지 식별, run ID는 빌드·게시 출처 검증을 담당한다. 배포 직전 ECR 값이 기록된 digest와 같은지 검사하고 해당 digest로 실행한다.

Git의 목표 Manifest와 호스트의 current/previous 성공 상태를 분리한다. PR 병합 후 실제 배포가 실패할 수 있으므로 Git 변경만으로 운영 성공을 판단할 수 없다.

**감수하는 단점:** 조회 권한과 출처 검증 코드가 필요하고 롤백 후 목표/실제 상태를 정합화해야 한다. 초기 digest·run ID를 모르면 null로 표시하고 실제 배포를 차단한다. pin-manifest.py로 실제 값을 확인한 뒤 반영한다. 실패/복구 이력은 호스트 history와 Actions/SSM 기록으로 남긴다.

**재검토:** 서명·attestation 검증이나 여러 환경으로 동일 이미지 승격이 필요할 때 기록 스키마를 확장한다. schema_version을 변경해 기존 parser가 조용히 오해하지 않게 한다.

## TD-003 — 중앙 자동 CD와 Backend 우선 적용

**상태:** 대체됨 → TD-008·009. 현재 자동 배포 대상은 네 서비스다.

**대안:** main의 수동 workflow 유지 / App별 독립 CD / Cloud 중앙 자동 CD.

**선택·이유:** 사용자가 중앙 자동 CD 전환을 명시했다. Backend CI 성공 → 후보 PR → 정책 검사·자동 병합 → Cloud main → SSM 배포로 연결한다. 서비스 실행 환경과 배포 실행 주체는 별개이므로 main의 검증된 앱 설정을 유지하면서 중앙 자동화를 적용할 수 있다.

처음에는 Backend만 자동 갱신·교체한다. Worker는 소스 정책·Manifest·Compose·큐 검사에서 제외한다. 기존 Frontend·Nginx·AI는 계속 실행하며 후보 PR에서 해당 이미지 변경을 거부한다.

**감수하는 단점:** GitHub App·출처 검증·상태 관리가 필요하다. 중앙 workflow/호스트 잠금을 공유하며 다른 서비스의 배포는 이번 경로로 처리할 수 없다. 새 서비스 추가 시 앱 계약과 복구 범위를 함께 확장해야 한다.

**재검토:** Backend 인수 시험이 끝나고 다른 서비스의 CI·health·호환성 계약이 확인될 때 자동화 범위를 확대한다. 이번 Backend 우선 결정이 중앙 자동 CD 목표의 포기는 아니다.

## TD-004 — 충돌 병합에서 main의 실행 설정 보존

**대안:** main 전체 선택 / 작업 브랜치 전체 선택 / 실행 설정과 배포 제어를 구분해 통합.

**선택·이유:** compose.yaml과 prepare-runtime.py는 main을 기준으로 유지한다. RDS 주소, 환경변수, JWT 파일, TLS/ACME·업로드 mount, 메모리 제한, 로그 방식, 실제 이미지 SHA는 앱과 맞춘 변경 이력이 있다. 반면 수동 배포 workflow와 전체 기동 절차는 중앙 자동 CD 제어 흐름으로 연결한다. 당시 deploy.sh는 Python 엔진의 진입점이었다. TD-008 이후에는 Bash로 교체·검증·복구를 직접 수행하며 Backend healthcheck는 TD-014에서 변경했다.

서비스 이름은 main을 따른다: web=Nginx, frontend=Next.js. 작업 브랜치에서 web=Next.js였던 매핑을 그대로 섞지 않는다. 최신화된 로컬 BE 소스 SHA를 운영 버전으로 임의 대체하지 않는다.

**감수하는 단점:** 충돌 표시가 없는 candidate/monitor/문서도 함께 수정해야 한다. 저장소 병합과 단위 테스트는 운영 성공 증거가 아니므로 EC2 인수가 남는다.

**재검토:** 앱 팀이 실행 설정을 바꾸면 Compose 및 검사·복구 스냅샷을 함께 검토한다.

## TD-005 — S3 없는 배포 코드 전달

**상태:** 대체됨 → TD-008. 현재는 기존 checkout을 지정 Cloud SHA로 전환한다.

**대안:** S3 묶음 전달 / 운영 checkout을 해당 SHA로 전환 / 고정 SHA를 별도 디렉터리에 archive.

**선택·이유:** 기존 EC2의 Git 읽기 인증을 활용해 SSM에서 main을 fetch하고 지정된 커밋이 main 이력에 포함되는지 확인한 뒤 별도 release 디렉터리에 archive한다. S3 미사용 환경에 불필요한 저장소·IAM 의존성을 추가하지 않고 운영 checkout도 변경하지 않는다.

**감수하는 단점:** 호스트에서 GitHub에 접근하고 fetch할 수 있어야 한다. release 디렉터리 보관·디스크 용량 관리가 필요하다. 소스 준비 잠금과 배포 잠금은 별개다. SSM 관찰 timeout 후에도 원격 작업이 계속될 수 있으므로 실제 상태를 조회한다.

**재검토:** 호스트의 Git 접근을 없애야 하거나 서명된 전달 묶음·장기 보존 요구가 생길 때 S3 등 artifact 전달 방식을 검토한다.

## TD-006 — 기존 스택 채택과 Backend 복구

**상태:** 대체됨 → TD-012. 아래 adopt·current 상태 파일 절차는 현재 사용하지 않는다.

**대안:** 기존 컨테이너를 내리고 최초 배포 / 실행 중이라는 이유만으로 정상 상태 기록 / 검증 후 adopt.

**선택·이유:** adopt는 이미지 ID와 main의 Compose 설정 해시, health·연결 검사를 확인하고 current를 만든다. 일반 배포는 current가 없으면 거부한다. Backend 신·구 이미지를 먼저 pull하고 Backend만 stop/recreate하며 Nginx는 reload한다. 실패하면 Backend만 복구하고 실패 digest/config를 차단한다.

**감수하는 단점:** 초기 채택 절차와 state 관리가 필요하고 설정/Compose 버전 차이로 채택이 거부될 수 있다. recreate 동안 Backend 요청 중단이 가능하다. 런타임 파일의 내용 해시를 검사하므로 Secret 회전은 별도 점검이 필요하다. 자동 배포가 임의로 정상 상태를 추정하거나 다른 서비스까지 재생성하지 않는다.

**재검토:** 무중단 요구, 다중 호스트 전환, 자동 Secret 회전이 필요할 때 배포 및 상태 관리 방식을 확장한다.

## TD-007 — 현재 검사 활용과 관측의 한계

**상태:** 갱신 → TD-013·014. 아래 TCP health·관측 설명은 당시 검토 내용이다.

**대안:** 미확정 /app/bin 검사·Worker 큐 검사 강제 / main의 실제 검사 활용 / 앱 readiness·업무 smoke를 새로 구현.

**선택·이유:** main의 네 서비스 healthcheck와 연결 검사를 유지하고 HTTPS·재시작 관찰을 적용한다. 존재가 확인되지 않은 /app/bin/smokecheck나 DB job 큐 검사를 호출하지 않는다. Worker 제거를 검사·모니터링에도 반영한다.

**감수하는 단점:** Backend TCP health는 업무 API·DB 쿼리 성공을 보장하지 않는다. 최신 로컬 BE CI는 main/dev 이미지를 게시하고 테스트를 생략하므로 Cloud의 main 성공 검증을 테스트 성공으로 표현하지 않는다. json-file 로그를 유지하며 앱 로그 전송·HTTP 오류율 알람은 이번 병합에서 새로 설치하지 않는다. SNS·배포 알람이 비어 있으면 알람 기반 배포 차단도 없다.

**재검토:** 실제 Backend readiness·업무 smoke 계약 및 오류 지표가 준비되면 앱 검사를 강화한다. 빈 알람 목록을 장기적인 관측 완료 상태로 취급하지 않는다.

## TD-008 — 최소 구성으로 재작성, 전 서비스 자동 CD

**맥락:** TD-002~006으로 만든 중앙 CD는 Backend만 자동 교체했다. Frontend·Nginx·AI는 변경을 거부해서, 기존 수동 배포 workflow가 없어진 뒤로는 배포할 방법이 없었다. 운영 담당자가 "스크립트가 왜 이렇게 많은지" 이해하기 어려웠다. 사용자는 "할 거면 다 자동 CD"를 요구했다.

| 기준 | 기존 중앙 CD 엔진 (TD-002~006) | 최소 구성 (채택) |
| --- | --- | --- |
| 대상 | Backend만 | Backend·Frontend·Nginx·AI |
| 코드 | 여러 Python 배포 모듈·상태 관리와 테스트 | release.sh·deploy.sh·notify-discord.sh와 workflow 4개. prepare-runtime.py로 배포 시 런타임 자동 갱신(TD-016) |
| 준비물 | GitHub App, 읽기 토큰, 검증용·배포용·감시용 OIDC 역할 3개, runtime.json, adopt, digest pin | 기존 배포 역할·EC2 checkout 재사용, Discord Webhook |
| 버전 기록 | SHA + ECR digest + CI run ID | SHA만 (기존 main과 같음) |
| 상태 관리 | current·previous·inflight·blocked·frozen JSON | 실행 중인 컨테이너가 현재 상태. `failed-images`, `history.log`, Secret 적용 확인용 `runtime-applied-서비스.json`(TD-016) |
| 실패 처리 | 롤백·차단·동결·recover·resume 모드 | 롤백·차단. 롤백 실패 시 Discord |
| 이해·유지보수 | 어려움 | 파일 하나씩 읽으면 흐름이 보임 |

**선택·이유:** 운영하는 사람이 구조를 이해하지 못하면 장애 때 손을 댈 수 없다. 이 위험이 안전장치 일부를 덜어내는 위험보다 크다고 판단했다. 네 컨테이너가 도는 단일 EC2 규모에서는 기존 main의 배포 방식(SSM → EC2 checkout → `deploy.sh`)에 "자동 감지·병합"과 "바뀐 서비스만 교체·검증·롤백"만 더하면 충분하다.

**감수하는 단점:**
- digest를 고정하지 않는다. SHA 태그를 덮어쓰지 않는다는 앱 CI의 관례를 믿는다.
- 배포 도중 SSM이 끊겼을 때 자동 recover가 없다. 호스트 잠금(`flock`)으로 동시 실행만 막고, 복구는 사람이 한다.
- 단위 테스트 48개가 사라진다. `deploy.sh`는 가짜 docker로 시나리오를 확인했고, 실제 EC2 인수 시험이 남는다.

**재검토:** 서비스·호스트가 늘거나, 무중단·서명 검증·다중 환경 승격이 필요해지면 V2(ECS)에서 다시 설계한다.

## TD-009 — 새 이미지 감지: Cloud 조회 vs 앱 저장소가 PR 생성

**상태:** 채택 (2026-09-29).

| 기준 | Cloud가 주기적으로 조회 — 채택 | 앱 CI가 Cloud에 PR 생성 |
| --- | --- | --- |
| 앱 저장소 변경 | 기존 이미지 게시 CI 사용 | 각 저장소 CI와 Cloud 쓰기 인증 연결 |
| 반영 시점 | 다음 정상 조회에서 판단 | 이미지 게시 후 즉시 요청 가능 |
| 놓친 후보 | Manifest와 다른 최신 SHA를 다시 조회 | CI의 PR 생성 단계 재실행 설계 필요 |
| 동시 변경 | Cloud 조회를 직렬화하고 최신 main에서 분기 | 여러 PR의 충돌·재처리 필요 |
| 실행 비용·부하 | 변경이 없어도 runner와 API 사용, EC2 조회 부하 없음 | 이미지 게시 때만 실행 |
| 서비스 확장 | sources 매핑뿐 아니라 Compose·검증·배포 순서 등 고정 목록도 수정 | 앱 CI와 Cloud 계약을 함께 확장 |

**선택 이유:** 기존 앱 CI의 SHA 이미지 게시를 활용해 Cloud 안에서 자동화를 시작하고, Cloud 쓰기 토큰을 앱 저장소마다 전달하는 부담을 줄인다. 최신 main에서 PR을 만들더라도 사람이 동시에 바꾸는 경우의 충돌까지 없어지는 것은 아니다.

**감수하는 단점:** 10분은 조회 간격이며 완료 시간 상한이 아니다. 첫 저장소 API 오류가 뒤 저장소를 막을 수 있다. 병합 전 후보는 다시 조회하지만 이미 Manifest에 반영된 버전의 배포 실패까지 자동 재시도하지 않는다. 스케줄 지연·누락과 공개 저장소의 무활동 비활성화도 운영에서 확인한다. **주기 실행 수단 자체가 멈추면 자동 CD 전체가 멈춘다**(아래 사후 검토).

**재검토:** 즉시 반영이 필요하면 앱 CI의 dispatch 알림과 조회를 병행하는 방식을 검토한다. 인증·호출 권한과 중복 실행 처리까지 함께 설계한다.

**사후 검토 (2026-10-01):** 2026-09-30 이 레포(또는 조직)에서 schedule 이벤트가 한 번도 발생하지 않아 자동 CD가 멈췄다([TD-022](#td-022--github-schedule-대신-eventbridge로-주기-실행)). 처음 감수한 단점에는 "지연·누락"만 있었고, 실행 수단이 아예 멈추는 경우는 없었다.

PR 생성 방식이었다면 앱 저장소의 push로 시작하므로 **이 장애는 피했을 것이다.** 당시 schedule만 안 됐고 push·수동 실행은 정상이었다. 대신 앱 CI가 Cloud 저장소에 쓰는 인증이 필요해 다른 벽에 부딪힌다. 앱 CI의 `GITHUB_TOKEN`은 다른 저장소에 쓸 수 없고 GitHub App은 조직 owner가 필요해 진행이 어렵다([TD-017](#td-017--자동-릴리스-pr-병합과-main-보호-규칙)). 남는 수단은 개인 PAT이며, 결국 조회 방식도 EventBridge 때문에 개인 PAT을 받아들였다. 두 방식을 같은 전제(개인 PAT)에서 비교하면 다음과 같다.

| 기준 | 조회 + EventBridge — 현재 | 앱 CI가 PR 생성 |
| --- | --- | --- |
| schedule 장애 영향 | 받음. EventBridge로 우회 | 받지 않음 |
| 토큰 권한 | Cloud 레포 Actions Read and write | Cloud 레포 Contents·Pull requests 쓰기 |
| 토큰 보관 위치 | AWS 한 곳 | 앱 저장소 3곳의 Secrets. 등록·교체에 각 저장소 관리자 권한 필요 |
| 호출 한 번 실패 | 다음 조회가 다시 잡음 | 그 버전은 다음 커밋까지 누락. 재실행 설계 필요 |
| 외부 감시(Health check) | 같은 EventBridge로 함께 해결 | 주기 실행이 필요한 작업이라 별도 수단이 또 필요 |

**판단:** 결정을 유지한다. schedule 장애를 피하는 이점보다 토큰 권한 범위·보관 위치·누락 복구의 부담이 더 크다. 교훈으로, 주기 실행에 기대는 결정은 "실행 수단이 멈추는 경우"를 단점에 적고, 병합 직후 실제 실행을 확인한다.

## TD-010 — 조회·병합 로직을 어디에 쓸 것인가

**상태:** 같은 날 YAML 인라인에서 **Bash 스크립트 분리 + Actions dry_run으로 변경** (2026-09-29).

| 기준 | YAML 인라인 | Bash + gh/jq — 채택 | Python |
| --- | --- | --- | --- |
| 흐름 | workflow 한 파일에 로직과 순서가 함께 있음 | YAML은 순서, release.sh는 조회·병합 | 함수·모듈로 정책 분리 가능 |
| 로컬 확인 | run 블록을 따로 꺼내야 함 | 같은 스크립트를 DRY_RUN으로 실행 | 가짜 응답으로 단위 검사하기 쉬움 |
| 오류 처리 | Bash 종료 규칙에 의존 | 동일. set -euo pipefail·inherit_errexit 사용 | 예외·복잡한 상태 처리를 명시하기 쉬움 |
| 현재 적합성 | 초기 짧은 호출에 적합 | 현재의 API 조회·JSON 수정·Git 호출에 충분 | 복잡한 상태·저장소별 독립 재처리가 늘면 검토 |

**선택 이유:** 코드 줄 수만으로 언어를 바꾸지 않는다. release.sh로 분리해 로컬 실행과 shellcheck를 가능하게 하고 gh·jq를 유지한다. Python도 gh를 호출할 수 있으므로 REST·인증을 반드시 직접 구현해야 하는 것은 아니다.

**미리 보기 방식:** Actions 수동 dry_run을 권장 경로로 추가했다. 운영과 같은 runner 환경에서 자동 배포를 켜기 전에 후보를 확인한다. 아직 병합하지 않은 코드는 WSL·Linux 로컬 DRY_RUN으로 확인한다. Windows Git Bash와 jq의 줄바꿈 차이를 운영 스크립트의 우회 코드로 처리하지 않기로 했다. 옵션 기본값·스위치·checkout 범위·실행 명령은 [운영 절차 2절](v1-operations.md#2-배포-전-후보-조회)이 기준이다.

**오류와 재시도:** 한 저장소의 API·Git 오류가 나면 멈추는 정책을 유지한다. 조회 조건 불충족과 API 실패는 구분한다. 다음 조회가 처리하는 범위는 아직 Manifest에 반영되지 않은 후보이며, 병합 뒤 배포 호출 실패는 수동 재실행이 필요하다.

**검토한 한계:**

- PR 검사: 앞선 검토에는 “GITHUB_TOKEN PR은 검사 workflow가 생성되지 않는다”고 적었으나 현재 공식 문서에 맞춰 정정했다. PR 생성·갱신 검사는 승인 대기 상태로 생성된다. 기존 2026-09-29 공개 API 확인 기록에는 main 보호 규칙·ruleset이 없다고 남아 있지만, 이번 문서 정리에서 원격 설정을 재조회하지는 않았다. 현재 스크립트는 검사 완료를 기다리지 않는다. 필수 검사·리뷰를 도입할 때 GitHub App 토큰 등 인증 수단, 검사 실행, 병합 완료 확인과 배포 트리거를 함께 재설계한다. [GitHub 공식 문서](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- ECR 조회: 게시 job 성공을 근거로 삼고 이미지 존재는 EC2의 사전 pull에서 확인한다. 사전 검증용 AWS 인증·권한·조회 경로의 관리 비용을 현재는 추가하지 않는다. 반드시 별도의 IAM 역할을 새로 만들어야 한다는 뜻은 아니다. 누락 이미지가 Manifest에 남아 후속 배포를 막는 한계를 수용한다.
- dry_run: 실제 GitHub 쓰기 권한·PR 병합·배포 성공을 증명하지 않는다. 이 경로는 별도 인수 시험이 필요하다.

**재검토:** 저장소별 독립 처리가 필요하거나 상태·재시도 정책이 복잡해지면 Python을 포함한 구현 방식을 다시 비교한다. 필수 검사 정책이나 이미지 공급 계약이 바뀌면 현재 검증 범위도 다시 결정한다.

## TD-011 — FE 배포 기준 브랜치

**맥락(2026-09-29 당시 확인):** 운영 FE 이미지로 기록된 `d3ca2ac`는 FE 저장소의 `feat/v1`에 있었고 FE `main`은 9/22 커밋에 머물러 있었다. BE·AI처럼 `main`을 기준으로 삼으면 자동 CD가 켜지는 순간 운영 FE가 옛 버전으로 돌아간다.

| 기준 | `main` | `feat/v1` — 채택 |
| --- | --- | --- |
| BE·AI와 일관성 | 같음 | 다름 |
| 지금 바로 사용 | 불가. FE가 `feat/v1`을 main에 병합하기 전까지 FE 자동 CD를 켜면 안 됨 | 가능. FE CI는 `feat/v1` push에서도 이미지를 게시함 |
| 전환 비용 | — | FE가 main으로 옮기면 `sources.json`의 `branch` 한 줄만 바꿈 |

**재검토:** FE 팀이 main으로 배포 기준을 옮기면 main의 CI·게시 job과 두 이미지의 SHA를 확인하고 sources.json을 수정한다. 과거 커밋 기록만으로 현재 원격 브랜치 상태를 판단하지 않는다.

## TD-012 — 배포 검증과 롤백 방식

**상태:** 채택 (2026-09-29).

| 대안 | 이점 | 부담·한계 |
| --- | --- | --- |
| 전체 compose up | 호출이 짧고 Compose가 변경 계산 | 명시적인 실패 검증·복구 처리가 별도로 필요 |
| 이전 Cloud 커밋 전체로 복구 | 설정까지 이전 코드 기준으로 되돌릴 수 있음 | 런타임·데이터·스크립트 형식 호환성 및 상태 관리 필요 |
| 서비스별 교체 + 이미지 복구 — 채택 | 변경 대상·실패 지점이 보이고 기존 호스트 상태 활용 | 설정·Secret·DB까지 복구하지 못함 |

**선택 이유:** Compose 설정 해시로 변경 대상을 계산하고 사전 pull·healthy 대기·연결 검사·관찰을 붙인다. 실행 중 컨테이너에서 이전 이미지를 얻어 별도 current/previous JSON 관리 비용을 줄인다. 자세한 순서·판정·복구 절차는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md)에 둔다.

**감수하는 단점:** 교체 중 해당 서비스가 잠시 중단된다. 복구는 이미지 태그 범위이며 설정 원인이면 복구 후에도 실패할 수 있다. 교체를 시도한 서비스만 차단 대상으로 고려해 FE 두 서비스의 원자적 복구·차단은 보장하지 않는다. 메모리의 이전 태그는 프로세스 중단 후 사라진다. health를 통과한 기능 버그는 앱 수정 또는 수동 롤백으로 처리한다.

**재검토:** FE 묶음의 원자성, 중단 후 자동 복구, 설정 롤백, 서비스 간 버전 호환성 검증이 요구될 때 보강한다.

## TD-013 — 장애 알림: 자동 복구되지 않은 경우만 Discord

**상태:** 채택 (2026-09-29).

| 대안 | 판단 |
| --- | --- |
| CloudWatch 알람 + SNS | IAM·지표 수집·알람 설정이 추가로 필요. 이전 미적용 초안은 보관 이력으로 남김 |
| GitHub 기본 실패 알림 | 팀 채널과 전달 범위가 다르고 롤백 성공도 workflow 실패로 표시됨 |
| Discord Webhook — 채택 | 팀이 쓰는 채널에서 실행 링크와 대응할 오류를 확인 가능 |

**선택 이유:** 배포가 자동 롤백되면 배포 실패 알림을 생략하고, 사람이 확인할 실패와 외부 응답의 장애·복구 변화를 보낸다. 설정·정상 기준·알림 조건·수신 시험·대응은 [장애 알림 시스템 구축](./v1-alerting.md)에 둔다.

**감수하는 단점:** 감지 시간 상한을 보장하지 않는다. 외부 검사는 HTTP 코드만 보므로 AI·DB·업무 오류를 놓칠 수 있다. 직전 workflow 결과가 검사·API·알림 오류로 실패한 경우 장애 상태 비교도 영향을 받는다. 호스트 지표와 로그 수집은 포함하지 않는다.

**재검토:** 감지 시간·알림 전달 보장이나 호스트 지표가 필요하면 별도 모니터링을 추가한다. 외부 감시를 Sentry Uptime으로 옮기는 결정은 [TD-023](#td-023--외부-감시-유지-sentry-uptime으로-이전)에 있다. 옮기면 외부 장애 알림은 Sentry의 Discord 연동으로 받고, 직전 실행 비교로 인한 누락 문제는 사라진다.

## TD-014 — Backend healthcheck를 `/actuator/health`로 강화

**맥락(2026-09-29 당시 확인):** Backend healthcheck는 8080 포트만 확인했다. BE 팀이 `/actuator/health`를 추가했고 당시 운영 이미지로 기록된 `15b54fe`에도 포함된 것으로 확인했다(`spring-boot-starter-actuator`, `EndpointRequest.to(HealthEndpoint)` permitAll, `show-details: never`). AI의 `/health`는 기존 healthcheck에서 이미 쓰고 있다.

**선택:** compose의 Backend healthcheck가 `/actuator/health` 응답에 `"status":"UP"`이 있는지 확인한다. DB 확인 범위는 Backend Actuator 설정에 의존하며 Cloud는 응답의 UP을 검사한다. 이미지에 curl이 있는지 확실하지 않아서 기존처럼 bash `/dev/tcp`로 HTTP 요청을 보낸다.

**감수하는 단점:** 이 변경으로 Backend 설정 해시가 바뀐다. 기존 healthcheck가 남아 있는 호스트에는 적용 시 이미지가 같아도 Backend 재생성이 필요하다. Nginx는 `/actuator`를 Backend로 넘기지 않으므로 외부 감시는 계속 `/api`를 쓴다.

## TD-015 — CloudWatch + Prometheus + Grafana

**맥락:** 사용자가 CloudWatch와 PG(Prometheus·Grafana)를 도입하고 Loki는 제외하도록 지정했다. 기존 CloudWatch 알람·Agent 초안을 확장한다.

**선택:** CloudWatch에 앱 로그·EC2/RDS 알람을 두고, PG는 내부 health·상세 호스트 지표·앱 계측 지표를 담당한다. Grafana의 서비스/수집 장애는 Discord로, CloudWatch 알람은 SNS 이메일로 보낸다. 기존 Actions 외부 감시는 유지한다. 내부 프로브·CloudWatch로 대체되지 않는 범위와 이후 Sentry Uptime으로 옮기는 계획은 [TD-023](#td-023--외부-감시-유지-sentry-uptime으로-이전)에 있다. 로그는 Docker awslogs를 사용하며, IAM·그룹 준비 후 호스트 marker로 활성화한다. PG는 같은 EC2의 별도 checkout·Compose 프로젝트에서 수동 갱신한다.

**대안·이유:** CloudWatch만으로 통일하면 PromQL 기반 앱 지표·부하 관측 요구를 충족하기 어렵다. Loki 추가는 요구 범위를 벗어나며 별도 로그 저장소를 늘린다. Agent로 Docker 로그 glob을 읽는 대신 awslogs를 써 컨테이너별 스트림을 만들고, Agent에는 호스트 메트릭만 맡긴다. 초기부터 별도 감시 호스트를 추가하는 대신 기존 EC2 용량을 확인해 시작한다. 상세 설정·적용 순서는 [모니터링 운영 구성](v1-monitoring.md)에 둔다.

**감수하는 단점:** PG가 앱과 자원을 공유하고 호스트 장애 때 함께 멈춘다. CloudWatch·Actions가 외부 감시를 보완하지만 Grafana 단독 장애 통보는 미구현이다. AWS 로그·지표 비용이 추가된다. non-blocking 버퍼가 차면 로그가 유실될 수 있고 최초 스트림 생성은 AWS에 의존한다. 로그 설정 변경은 기존 이미지 롤백으로 되돌아가지 않는다. 앱 계측은 별도 저장소 작업이며 완료 전에는 타깃을 활성화하지 않는다.

**재검토:** 부하 테스트와 PG가 자원 경쟁을 하거나 다중 호스트로 확장할 때 감시 호스트 분리·중앙 저장을 검토한다. 로그의 무손실 전달·장기 보관 또는 단일 알림 채널이 필요하면 수집 경로·보관 정책·라우팅을 다시 정한다.

## TD-016 — 배포 시 Secret 자동 조회와 실패 처리

**상태:** 채택 (2026-09-30, 사용자 요청). main의 정상 운영 방식을 유지한다. 실제 EC2 적용은 별도 배포·인수 시험으로 확인한다.

**맥락:** main의 deploy.sh는 이미지 pull 전에 prepare-runtime.py를 실행했다. AWS 조회 실패, JSON/필수 값/JWT 기본 형식 오류는 Python이 비정상 종료하고 `set -euo pipefail`로 배포가 멈췄다. TLS·runtime 파일·일부 필수 env 추가 검사도 있었다. 따라서 main에 실패 처리가 없었던 것은 아니다. 다만 교체 후 자동 이미지 롤백과 JWT 파일 내용 변경 감지는 없었다. 자동 CD 재작성 중 조회가 수동 작업으로 분리됐지만, 운영자가 갱신을 빠뜨리면 Secret 변경 후 배포해도 이전 값으로 실행되는 문제가 생긴다.

| 대안 | 판단 |
| --- | --- |
| 운영자가 EC2에서 매번 수동 갱신 | 코드 배포와 Secret 변경을 분리하지만 추가 작업·누락 가능성이 생김 |
| 매 배포에서 조회·검증 후 반영 — 채택 | 기존 main의 사용 방식 유지, 별도 EC2 수동 작업 없이 다음 배포에 반영 |
| 버전 고정 Secret·설정까지 자동 복구 | 복구 범위는 넓지만 외부 DB/API 자격 증명과의 일관성 및 상태 관리가 추가로 필요 |

**선택:** deploy.sh가 호스트 잠금을 획득한 뒤 BE·AI Secret을 조회하고 전부 검증한 후 파일을 갱신한다. 조회/검증 실패 시 파일 갱신 전에 종료하며, 파일 저장 실패도 컨테이너 교체 전에 종료한다. 새 스크립트는 `set -e`를 사용하지 않으므로 호출 결과를 명시적으로 확인하고 `runtime_prepare_failed`(2)로 기록·알림한다. AWS 명령은 60초 제한을 두며 비밀값과 오류 원문은 출력하지 않는다. 같은 파일 내용이면 inode를 교체하지 않는다.

로컬 Compose CLI 실험에서 env_file 내용만 바꿔도 `config --hash`가 같게 나왔다. JWT 파일 내용도 Compose 해시에 포함되지 않으므로 env·JWT 변경을 Compose 해시에만 의존하지 않는다. `/opt/keepgo/state/runtime-applied-backend.json`, `runtime-applied-ai-api.json`에 마지막 정상 적용 컨테이너 ID와 서비스별 파일의 합성 SHA-256 지문을 root 전용(0600)으로 저장한다. Backend는 backend.env와 JWT 두 파일, AI는 ai.env를 비교한다. 값과 지문을 로그·컨테이너 라벨에 출력하지 않는다. 기록과 다른 서비스만 강제 재생성한다. 최초 도입·기록 유실 시 BE·AI 중 기록이 없는 서비스를 한 번 재생성한다. pull 실패나 중단 때 적용 기록을 앞당겨 갱신하지 않아 재시도에서도 미적용 파일을 감지한다. 차단 때문에 건너뛴 서비스는 기록하지 않는다. 교체 후 전체 검사·관찰 성공 또는 이미지 롤백 후 전체 검사 성공 때 실제 컨테이너 ID로 기록한다.

**감수하는 단점:** 실제 배포마다 Secrets Manager 접근이 필요하고, FE만 바뀌더라도 BE/AI Secret 조회 실패 시 배포가 멈춘다. 파일별 저장은 atomic replace지만 여러 파일 전체의 저장은 단일 트랜잭션이 아니다. 저장 도중 I/O 실패 시 일부 호스트 파일이 갱신될 수 있어 원인 해결 후 전체 조회·배포를 재실행한다. 이미지 롤백도 최신 Secret을 사용하며 Secret·DB를 되돌리지 않는다. 잘못된 비밀번호/API 키 또는 RSA 키 쌍의 실제 유효성은 기본 형식 검사만으로 보장되지 않는다. Secret 문제는 Secrets Manager에서 유효한 값으로 수정/복원하고 수동 배포한다. JWT 교체가 기존 토큰에 미치는 영향은 앱 팀과 조율한다.

**검증:** 단위 시험과 가짜 Docker/AWS로 실제 deploy.sh를 실행하는 회귀 시험을 추가한다. 조회/검증 실패 시 파일 보존·교체 중단, 무변경 배포, JWT만 변경, AI env만 변경(Compose 해시 동일), pull 실패 후 재시도, 적용 기록 유실/차단, 이미지 복구 후 기록을 검증한다. 실제 EC2 권한·Docker bind mount·서비스 인증은 운영 인수 시험 대상이다.

**재검토:** 무중단 키 회전, Secret 버전 고정, 실패 시 설정 전체 복구 또는 여러 호스트 간 원자적 반영이 필요해질 때 배포 상태·Secret 버전 관리 방식을 확장한다.

## TD-017 — 자동 릴리스 PR 병합과 main 보호 규칙

**상태:** 채택 (2026-09-30, 사용자 결정). main에 브랜치 보호 규칙(필수 status check·필수 리뷰)을 설정하지 않는다.

**맥락:** release.sh는 Actions 기본 `GITHUB_TOKEN`으로 Manifest PR을 만들고 즉시 squash 병합한다. GitHub는 `GITHUB_TOKEN`이 만든 push에서 다른 workflow를 실행하지 않는다. PR의 `pull_request` workflow는 run이 생기지만 사람의 승인을 기다린다(아래 2026-10-01 추가). 따라서 release PR에서는 Validate가 실제로 돌지 않고, main에 필수 check가 있으면 `gh pr merge`가 실패한다. `GITHUB_TOKEN`은 자기 PR을 승인할 수 없어 필수 리뷰와도 양립하지 않는다.

| 대안 | 판단 |
| --- | --- |
| GitHub App 토큰으로 PR 생성 → Validate 실행 후 `--auto` 병합 | 정석이지만 조직(100-hours-a-week) owner가 App을 만들고 설치해야 한다. 현재 진행이 어렵다 |
| 개인 PAT | 특정 사람 계정·만료에 배포가 묶이고, 퇴장 시 자동 CD가 멈춘다 |
| main 보호 규칙 없이 병합, 검사는 release.sh에서 — 채택 | 추가 권한 없이 동작한다. release PR의 변경은 API에서 받은 SHA 한 줄이라 Validate가 잡을 범위가 작다 |

**선택:** release.sh가 Manifest를 바꾼 직후 Validate와 같은 `scripts/check-manifest.jq`로 형식을 검사하고, 실패하면 커밋·병합하지 않고 오류로 끝낸다(자동 릴리스 실패 Discord 알림). Validate와 release.sh가 같은 jq 파일을 써서 기준이 갈라지지 않게 한다. 실제 배포 안전장치는 deploy.sh의 Manifest·Compose 검사, health 확인, 롤백·실패 이미지 차단이다(TD-012).

**감수하는 단점:** 사람도 리뷰·Validate 통과 없이 main에 직접 push·병합할 수 있다. compose.yaml·deploy.sh 같은 사람의 변경은 Validate 결과를 보고 병합하는 팀 규칙에 의존한다. AUTO_DEPLOY_ENABLED=true이면 그런 변경의 main push가 곧바로 운영 배포된다.

**재검토:** 조직 App 발급이 가능해지거나, 사람의 main 직접 변경으로 사고가 나면 App 토큰 + 필수 check로 전환한다. 전환 시 병합 push가 Deploy production을 직접 트리거하므로 auto-release.yaml의 배포 호출 단계는 제거한다. 아래의 `[skip ci]`도 함께 뺀다. 남겨 두면 release PR의 Validate와 병합 후 main push의 workflow까지 건너뛴다.

**추가 (2026-10-01): release 커밋에 `[skip ci]`.** release PR마다 Validate run이 생겨 승인을 기다리다 만료되고 Failure로 남았다(예: PR #31, 01:30:34 병합 → 01:30:35 Validate 생성 → 만료. 같은 시각 Deploy production은 성공). job은 시작하지 않았으므로 검사 결과가 아니다. 그런데 릴리스마다 빨간 X가 쌓여 실제 실패를 가린다. workflow의 `if:` 조건은 승인 대기보다 늦게 평가돼 소용없으므로 release.sh 커밋 메시지에 `[skip ci]`를 넣어 run 자체를 만들지 않는다. 이 변경으로 잃는 검사는 없다. release PR이 바꾸는 것은 Manifest의 SHA뿐이고 그 형식은 release.sh가 같은 jq로 검사한다. 이미지 존재는 앱 CI·게시 job 성공 확인과 deploy.sh의 pull로, 실행은 health 확인·롤백으로 막는다. sources.json·compose·스크립트는 사람 PR의 Validate가 맡는다.

## TD-018 — 배포 사전 검사 복원과 main 전용 배포

**상태:** 채택 (2026-09-30). 실제 EC2 적용은 운영 인수 시험으로 확인한다.

**맥락:** TD-008에서 deploy.sh를 다시 쓰면서 main의 사전 검사 일부가 기록 없이 빠졌다. (1) `/opt/keepgo/tls/fullchain.pem`·`privkey.pem`, `/opt/keepgo/data/uploads` 존재 확인, (2) ai.env의 NAVER_MAP_CLIENT_ID·SECRET 필수 확인. main 안에서도 prepare-runtime.py는 NAVER 키를 선택으로, deploy.sh는 필수로 다뤄 판단이 둘로 나뉘어 있었다. 또 새 workflow에서 EC2는 `origin main`만 fetch하지만, Run workflow에서 다른 브랜치를 고르는 것을 막지 않았다.

**선택:**

- deploy.sh가 Secret 조회·pull 전에 TLS 두 파일(비어 있지 않음)과 `acme`·`data/uploads` 디렉터리를 확인하고, 없으면 아무것도 바꾸지 않고 `host_files_missing`(2)로 끝낸다. main에 없던 `acme`도 같은 이유(bind `create_host_path: false`)로 포함한다.
- NAVER 두 키를 prepare-runtime.py의 `AI_REQUIRED`로 옮긴다. 필수 여부는 한 곳에서만 정한다.
- Deploy production job은 `github.ref == refs/heads/main`일 때만 실행하고, 다른 브랜치 선택은 skip한다.

**판단 이유:** 이 경로들은 bind mount가 `create_host_path: false`라 없으면 컨테이너가 생성되지 않는다. `compose config`로는 드러나지 않고, 교체 중에 실패하면 이전 이미지로의 롤백도 같은 이유로 실패해 서비스가 멈춘 채 `rollback_failed`로 끝날 수 있다. 교체 전에 확인하면 운영 컨테이너를 건드리지 않고 멈춘다. NAVER 키가 없으면 AI는 기동하고 healthcheck도 통과하지만 지도·주소 요청이 모두 실패한다. health로 드러나지 않는 기능 장애이므로 배포 전에 막는다. 운영 Secret은 main 배포에서 이 검사를 통과해 왔으므로 기존 운영에는 영향이 없다.

**감수하는 단점:** 지도 기능이 없어도 되는 시험 환경에서도 NAVER 키가 필요하다. TLS 인증서의 유효 기간·내용은 검사하지 않는다(만료는 외부 Health check의 HTTPS 실패로 드러난다). 다른 브랜치에서 Run workflow를 누르면 실패가 아니라 skip으로 표시된다.

**검증:** prepare-runtime 단위 시험(NAVER 키 누락 시 파일 보존·중단), deploy.sh 회귀 시험(각 경로 누락 시 Secret 조회·Docker 호출 없이 종료). 경로 기준은 `HOST_DIR`(기본 `/opt/keepgo`)로 시험에서만 바꾼다.

**재검토:** 지도 기능을 선택 기능으로 바꾸거나 TLS를 ALB/ACM으로 옮기면 해당 검사를 조정한다.

## TD-019 — AI Secret 키 전달 범위와 SENTRY_DSN

**상태:** 채택 (2026-09-30). 다음 AI 배포부터 적용된다.

**맥락:** prepare-runtime.py는 Secret의 모든 키가 아니라 코드에 적힌 키만 env 파일로 옮긴다. 운영 `Secret-v1-AI`에는 `GOOGLE_MODEL`, `LANGSMITH_API_KEY`, `SENTRY_DSN`이 더 있지만 컨테이너에 전달되지 않았다(main도 동일). 운영 중인 AI `f7476b5`에는 영향이 없었지만, AI 원격 main(`4bd2efc`, 커밋 `8bd3c32`)은 `SENTRY_DSN`이 있을 때만 Sentry를 켜고 설정 주석에 "운영에서는 인프라가 환경변수로 주입한다"고 명시했다. 그대로 두면 자동 배포 후 Sentry가 오류 없이 꺼진 채 운영된다.

| 대안 | 판단 |
| --- | --- |
| Secret의 모든 키를 그대로 전달 | 앱 팀이 키를 추가하면 바로 반영되지만, 의도하지 않은 값(추적 키 등)도 컨테이너에 들어가고 필수 검증이 약해진다 |
| 필요한 키만 목록에 추가 — 채택 | 컨테이너에 들어가는 값을 Cloud 저장소에서 검토할 수 있다. 앱이 새 키를 요구하면 이 목록도 바꿔야 한다 |

**선택:** `SENTRY_DSN`을 `AI_OPTIONAL`에 추가한다. 없으면 배포 로그에 경고만 남기고 계속한다. `LANGSMITH_API_KEY`는 AI 코드·의존성에서 쓰지 않고(v2 예정), LangChain 추적은 `LANGSMITH_TRACING=true`도 필요하므로 전달하지 않는다. 켜면 프롬프트·사용자 입력이 외부로 전송되므로 AI 팀과 별도로 결정한다. `GOOGLE_MODEL`은 비밀값이 아니며 compose.yaml(`gemini-3.8-flash`)에서 관리한다. Secret의 값은 쓰이지 않으므로 AI 팀과 확인 후 Secret에서 제거하는 것을 권장한다.

**감수하는 단점:** 앱이 새 환경변수를 요구할 때마다 Cloud 저장소의 목록 변경이 필요하다. 목록에 없는 키는 조용히 무시된다.

**재검토:** LangSmith 추적을 켜기로 하거나 앱이 Secret 기반 설정을 더 늘리면, 전달 목록을 앱 계약 문서와 함께 다시 정한다.

**후속 (2026-09-30):** AI 파트가 PR #22(`dice/ai-observability`)로 LangSmith 추적을 켰다. `LANGSMITH_API_KEY`를 `AI_OPTIONAL`에 추가하고 compose에 `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=keepgo`를 넣었다. 운영 AI 요청의 프롬프트·입력이 LangSmith로 전송된다.

## TD-020 — production Environment 승인 제거

**상태:** 채택 (2026-09-30, 사용자 결정·설정 변경 완료).

**맥락:** main 병합 후 첫 수동 배포(Deploy production #13)가 production Environment의 Required reviewers(팀원 1명) 승인 대기에서 멈췄다. 기존 main의 수동 배포부터 걸려 있던 GitHub 설정이며, 이번 workflow 변경으로 생긴 것은 아니다. 이 설정이 있으면 Auto release가 Manifest를 병합해도 배포가 매번 승인 대기에서 멈춰 TD-008·009의 전 서비스 자동 배포가 반자동이 된다.

| 대안 | 판단 |
| --- | --- |
| 승인자 유지 | 배포 전 사람이 한 번 더 확인한다. 승인자가 자리에 없으면 앱 팀의 main 병합이 운영에 반영되지 않고 밀린다 |
| 승인자 제거 — 채택 | 설계 의도대로 앱 main 병합 → 10분 안에 배포된다 |

**선택:** production Environment의 Required reviewers를 제거한다. 배포 안전장치는 deploy.sh의 사전 검사, health·연결 확인, 자동 롤백, 실패 이미지 차단과 Discord 알림이다(TD-012·013·018). 배포 시작 여부는 `AUTO_DEPLOY_ENABLED` 변수로 제어한다.

**감수하는 단점:** 앱 팀의 main 병합이 사람 확인 없이 운영에 나간다. health로 드러나지 않는 기능 오류는 배포 후에야 발견된다. main 보호 규칙도 없으므로(TD-017) 수동 Run workflow도 누구나 즉시 운영 배포할 수 있다.

**재검토:** 기능 오류가 자동 배포로 반복해서 나가거나 팀이 배포 시간대를 통제해야 하면, 승인자를 다시 두거나 배포 가능 시간대·스테이징 단계를 추가한다.

## TD-021 — 배포 변경 감지를 적용 기록 기준으로

**상태:** 채택 (2026-09-30). TD-012의 변경 감지 방식을 보완한다. 경위는 [트러블슈팅 사례](troubleshooting/2026-09-30-env-file-services-recreated-every-deploy.md)에 있다.

**맥락:** TD-012는 컨테이너의 `com.docker.compose.config-hash` 라벨과 `docker compose config --hash`를 비교해 바뀐 서비스를 찾았다. 운영(Compose 2.40.3)에서 env_file을 쓰는 backend·ai-api는 방금 만든 컨테이너도 두 값이 달라, 변경이 없어도 배포마다 재생성됐다.

| 대안 | 판단 |
| --- | --- |
| 라벨 해시를 Compose와 같은 방식으로 직접 계산 | Compose 내부 구현에 묶여 버전이 바뀌면 다시 깨진다 |
| `compose up --dry-run` 출력으로 재생성 여부 판단 | 출력 문구를 파싱해야 해 버전 변화에 약하다 |
| 마지막 배포가 적용한 `config --hash`를 직접 기록해 비교 — 채택 | 우리가 쓴 값끼리 비교하므로 Compose 내부와 무관하다. TD-016의 Secret 적용 기록과 같은 방식이다 |

**선택:** 배포·복구 성공 후 교체한 서비스마다 `/opt/keepgo/state/applied-config-<서비스>`에 `컨테이너ID 설정해시`를 저장한다. 다음 배포는 컨테이너 ID가 같을 때 기록한 해시와 비교하고, 기록이 없거나 컨테이너가 바뀌었을 때만 라벨과 비교한다. env·JWT 내용 변경은 TD-016의 적용 기록이 계속 잡는다.

**감수하는 단점:** 도입 직후 첫 배포에서 backend·ai-api가 한 번 더 재생성된다. state 파일이 사라지면 같은 방식으로 한 번 재생성된다. 누가 EC2에서 compose를 직접 바꿔 컨테이너를 재생성하면 라벨 비교로 돌아간다.

**재검토:** Compose가 env_file을 포함한 해시를 CLI로 제공하거나, 배포 대상을 여러 호스트로 늘려 상태 저장 위치를 바꿀 때.

## TD-022 — GitHub schedule 대신 EventBridge로 주기 실행

**상태:** 채택 (2026-09-30, 운영 적용). TD-009의 "Cloud가 10분마다 조회한다"는 결정은 유지하고, 그 **실행 수단**만 GitHub `on.schedule`에서 AWS EventBridge로 바꾼다. 경위는 [트러블슈팅](troubleshooting/2026-09-30-actions-schedule-not-running.md)에 있다.

**맥락:** main 병합(07:12 UTC) 후 Auto release(10분)·Health check(5분)의 schedule 실행이 한 번도 생기지 않았다. 기본 브랜치·workflow 상태·파일 문법·커밋 계정·GitHub 장애 여부는 모두 정상이었고, Disable/Enable과 cron 값 변경(#24)으로 재등록해도 0건이었다. 설정을 모두 뺀 최소 workflow(`schedule-probe.yaml`, #25)도 수동 실행은 되고 schedule은 23분간 0건이어서, 레포 또는 조직(100-hours-a-week) 차원에서 schedule 이벤트가 발생하지 않는 것으로 판단했다. 정확한 원인은 조직 관리 권한이 필요해 확인하지 못했다.

GitHub 밖에서 workflow를 실행하려면 어떤 방식이든 Cloud 레포의 workflow 실행 권한을 가진 **토큰이 필요**하다. 이 점이 대안 비교의 전제다.

| 대안 | 장점 | 단점 | 판단 |
| --- | --- | --- | --- |
| 조직 관리자 답변을 기다림 | 추가 구성 없음 | 언제 해결될지 모름. 그동안 자동 배포·외부 감시가 멈춤 | 병행(문의)만 한다 |
| 앱 CI가 이미지 게시 직후 Cloud를 dispatch로 호출(push) | 즉시 반영. 새 버전이 있을 때만 실행돼 기록이 쌓이지 않음 | 같은 팀의 BE·FE·AI 파트 CI 3곳을 고치고 토큰을 3곳에 등록·교체해야 함. 호출이 한 번 실패하면 그 버전은 다음 커밋까지 누락되므로 결국 조회 방식 보조가 필요 | 보류. 반영 지연이 불편해지면 도입 |
| 앱 CI가 Cloud에 Manifest PR을 직접 생성 | 즉시 반영. PR 토큰이 GITHUB_TOKEN이 아니라 Validate도 돈다 | 앱 레포 3곳에 Cloud **쓰기** 권한 토큰이 필요. 두 앱이 동시에 올리면 Manifest PR끼리 충돌. 운영 버전 결정권이 여러 레포로 흩어져 중앙 CD의 이점이 약해짐 | 기각 |
| EC2 cron이 GitHub API 호출 | 가장 단순 | 운영 서버에 토큰을 둠. EC2가 멈추면 외부 감시도 같이 멈춰 감시 목적과 모순 | 기각 |
| EventBridge Scheduler + Lambda | Scheduler 자체 기능이 풍부 | Scheduler는 외부 HTTP를 직접 호출하지 못해 Lambda 코드·배포·권한이 추가됨 | 기각 |
| **EventBridge 예약 규칙 + API destination** — 채택 | Lambda 없이 AWS 리소스만으로 HTTP 호출. 토큰은 EventBridge 연결(Secrets Manager)에 암호화 저장. 앱 레포 수정 없음. 호출이 실패해도 다음 주기에 다시 조회해 스스로 복구. CloudFormation 한 파일(`infrastructure/github-dispatch.yaml`)로 재현 가능 | 아래 "감수하는 단점" | 채택 |

**선택:** `keepgo-v1-github-dispatch` 스택으로 EventBridge 규칙 2개(`rate(10 minutes)`, `rate(5 minutes)`)가 각 workflow의 `workflow_dispatch` API(`{"ref":"main"}`)를 호출한다. 토큰은 Cloud 레포 하나에 Actions Read and write만 가진 fine-grained PAT이며 NoEcho 파라미터로만 받는다. workflow 로직은 바꾸지 않는다. 배포 여부는 여전히 `AUTO_DEPLOY_ENABLED`가 결정한다. `on.schedule` 설정은 남겨 두며, 조직 문제가 풀려 schedule이 살아나도 concurrency 때문에 겹쳐 실행되지는 않는다.

**비용:** 규칙 실행 무료, API destination 월 약 13,000회(100만 회당 $0.20)로 월 $0.01 미만, 연결 비밀 최대 월 $0.40. Actions는 public 레포라 무료.

**감수하는 단점:**

- **토큰이 개인 계정에 묶이고 만료된다.** TD-017에서 개인 PAT을 피한 이유와 같다. 권한을 workflow 실행으로만 좁혀 위험 범위를 줄였다. 만료·권한 회수 시 호출이 조용히 실패하므로 `AlertsTopicArn`으로 실패 알람을 연결해야 한다(모니터링 스택 생성 후, 현재 미연결).
- **실행 기록이 쌓인다.** Health check 하루 288건, Auto release 하루 144건. schedule이 동작했어도 같았을 조회 방식 자체의 특성이다. 배포·릴리스·장애는 Deploy production 목록, release PR, Discord, EC2 `history.log`에서 따로 확인한다.
- **"Manually run by (토큰 소유자)"로 표시된다.** 사람이 누른 실행과 목록에서 구분되지 않는다. 주기(5·10분 간격)나 EventBridge 규칙의 모니터링 지표로 구분한다.
- **최대 10분 반영 지연.** push 방식보다 느리다.
- 외부 감시(Health check)를 CI 도구로 돌리는 구조가 그대로 남는다. 감시 전용 서비스가 더 적합하다. 교체 판단과 제약은 [TD-023](#td-023--외부-감시-유지-sentry-uptime으로-이전).

**재검토:**

- 조직에서 schedule이 복구되면 EventBridge 규칙을 끄고(스택 삭제) `on.schedule`로 돌아간다. 그 전에 probe로 실제 실행을 확인한다.
- 반영 지연·기록 누적이 불편해지면 앱 CI의 dispatch 호출(push)을 추가하고 EventBridge 주기를 1시간 보조로 늘린다.
- TD-023을 적용하면 Health check 규칙을 스택에서 빼고 EventBridge는 Auto release만 실행한다.
- 토큰 만료 전(발급 시 정한 만료일)에 새 토큰으로 스택을 다시 배포한다. 절차는 [운영 절차](v1-operations.md) 11절.

## TD-023 — 외부 감시: 유지, Sentry Uptime으로 이전

**상태:** 결정 (2026-10-01), 적용 대기. 설정값·적용 순서·확인 항목은 [Sentry 사용 정리](v1-sentry.md)에서 관리한다. 같은 날 처음에는 Route 53 헬스 체크로 정했다가 **Sentry Uptime Monitoring으로 변경**했다(변경 이유는 아래). 팀이 Sentry 계정 하나를 함께 쓰기로 한 것이 전제다. Actions Health check(TD-022의 EventBridge 실행)는 아래 "적용 순서"를 마칠 때까지 유지한다.

**맥락:** CloudWatch·PG를 붙이면서 Actions Health check가 따로 필요한지 다시 검토했다. Health check는 schedule 장애 때문에 EventBridge와 개인 PAT로 돌고 있고, 하루 288건의 실행 기록이 쌓인다. 중복 알림은 직전 실행 결과를 비교하는 방식으로 막고 있어 알림이 누락될 수 있다([장애 알림](v1-alerting.md) 8-3).

**일반적인 구성과 비교:** 보통 감시를 세 층으로 나눈다.

| 층 | 하는 일 | 우리 구성 |
| --- | --- | --- |
| 배포 시 health 확인 | 새 버전이 **그 순간** 떴는지 확인하고 실패하면 롤백 | deploy.sh |
| 내부 모니터링 (white-box) | 서버·앱 안의 지표로 **원인**을 찾음 | CloudWatch + Prometheus·Grafana |
| 외부 감시 (black-box) | 사용자 입장에서 밖에서 접속해 **증상**을 잡음 | Actions Health check |

배포 시 확인은 배포가 끝난 뒤의 인증서 만료·보안 그룹 변경·EC2 정지를 보지 못한다. 외부 감시는 보통 가동 감시 서비스(UptimeRobot·Better Stack·Sentry 등)나 클라우드 기능(Route 53·Synthetics)으로 두며, CI 도구의 cron으로 돌리는 경우는 드물다. 우리는 "추가 서버·비용 없이"를 우선해 Actions를 골랐고, schedule 장애로 그 단점이 드러났다.

**관측 범위 비교:**

| 감시 | 보는 곳 | 못 보는 곳 |
| --- | --- | --- |
| blackbox → Prometheus → Grafana | Docker 내부망 주소로 서비스 4개의 health | DNS·TLS 인증서·보안 그룹·Nginx 443 설정. 같은 EC2에 있어 EC2·Docker가 멈추면 함께 멈춤 |
| CloudWatch | EC2 상태 검사, 디스크·메모리, Agent 지표 누락, RDS | HTTP 응답. EC2는 살아 있는데 Nginx·인증서·보안 그룹이 잘못된 경우 |
| Actions Health check | 사용자와 같은 경로: DNS → TLS(curl이 인증서 검증) → 보안 그룹 → Nginx → Frontend·Backend | 서비스별 내부 상태 |

공개 경로의 장애는 다른 감시로 대체되지 않는다. 인증서를 EC2에서 ACME로 직접 갱신하므로 갱신 실패도 밖에서만 보인다. 외부 감시는 유지하고 **실행 수단만 바꾼다.**

| 대안 | 장점 | 단점 | 판단 |
| --- | --- | --- | --- |
| 외부 감시 제거, CloudWatch·PG만 사용 | 구성이 단순해지고 EventBridge 규칙이 하나 준다 | DNS·인증서·보안 그룹·Nginx 공개 설정 장애와 Grafana 자체 장애를 못 잡는다 | 기각 |
| Actions + EventBridge 유지 — 현재 | 이미 동작한다. 인증서까지 검증하고 구간별 응답 코드로 원인 구간을 보여 준다. Discord로 알린다 | 개인 PAT에 의존하고 기록이 쌓인다. 상태 비교 방식이라 알림이 누락될 수 있다. GitHub 장애 때 함께 멈춘다 | 적용 순서를 마칠 때까지 유지 |
| Route 53 헬스 체크 + CloudWatch 알람 | AWS가 여러 지역에서 확인한다. 알람이 상태를 관리한다. CloudFormation으로 관리한다 | 인증서를 검증하지 않는다([AWS 문서](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover-determining-health-of-endpoints.html)). 지표가 us-east-1에만 생겨 알람·SNS를 별도 리전 스택으로 만들어야 한다([AWS 문서](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/monitoring-health-checks.html)). SNS는 Discord를 직접 호출하지 못해 알림이 이메일로 바뀐다. 헬스 체크마다 월 요금이 있다 | 처음 채택했다가 변경 |
| **Sentry Uptime Monitoring** — 채택 | Sentry 서버가 여러 지역에서 확인한다. 모든 요금제에 1개 포함이라 `/healthz` 하나는 무료다. 기존 Sentry의 Discord 연동으로 알린다. AWS·GitHub·EC2와 독립이다. 이미 AI가 쓰는 도구라 새 서비스가 늘지 않는다 | 아래 "감수하는 단점" | 채택 |
| CloudWatch Synthetics canary | 스크립트로 여러 경로·응답 본문·인증서를 검사할 수 있다 | 실행마다 과금되고 canary 런타임을 관리해야 한다 | 로그인 같은 업무 흐름 검사가 필요해지면 검토 |
| 다른 가동 감시 SaaS | 무료 요금제와 Discord 연동이 있다 | 팀이 쓰지 않는 계정이 하나 더 생긴다 | 기각 (Sentry로 같은 효과) |

**변경 이유 (Route 53 → Sentry):** 둘 다 공개 경로를 밖에서 확인한다는 핵심은 같다. Route 53은 us-east-1 별도 스택, 이메일 알림, 월 요금, 인증서 보완을 모두 더 해야 했다. Sentry는 팀이 계정을 함께 쓰기로 하면서 이 부담 없이 Discord 알림까지 받을 수 있다. 처음 "외부 SaaS"를 기각한 이유는 팀 밖 계정 관리였는데, Sentry는 이미 팀이 쓰는 계정이라 해당하지 않는다. 인프라 코드로 남지 않는 점은 감수한다.

**Sentry Uptime 동작 (2026-10-01 공식 문서·요금표 확인):**

- 확인 주기: 1분·5분·10분·20분·30분·1시간 중 선택
- 정상 기준: 2xx만 정상. 3xx는 따라가서 최종 응답이 2xx여야 한다. 10초 안에 응답이 없거나 DNS 오류면 실패
- 장애 판정: 기본 3번 연속 실패 시 이슈 생성(조정 가능). 알림 규칙에서 이메일·Slack·Discord 등 연동으로 보낸다
- 비용: 모든 요금제에 1개 포함, 추가는 1개당 월 $1. 무료 Developer 요금제는 사용자 1명
- SDK가 필요 없고 URL만 등록한다

출처: [Sentry Uptime Monitoring 문서](https://docs.sentry.io/product/monitors-and-alerts/monitors/uptime-monitoring/), [Sentry 요금표](https://sentry.io/pricing/)

**선택:** Sentry Uptime에 공개 주소 `/healthz`를 **1분 주기**로 등록해 입구(DNS·TLS 연결·보안 그룹·Nginx)를 본다. 기본 3번 연속 실패 기준이면 약 3분 안에 감지한다(5분 주기면 약 15분). 알림은 기존 Discord 채널로 보낸다. 서비스별 상태는 blackbox 내부 프로브(Grafana)가 맡는다.

**적용 순서:**

1. Sentry Uptime에 `/healthz`를 등록하고 Discord 알림을 연결한다. Actions Health check와 겹쳐도 문제없으므로 바로 해도 된다.
2. 인증서 검증 여부를 시험한다. `https://expired.badssl.com/`을 잠깐 등록해 실패로 잡히는지 보고 지운다. 잡히지 않으면 blackbox에 공개 주소 HTTPS 프로브와 `probe_ssl_earliest_cert_expiry` 기준 만료 임박 알림을 추가한다.
3. 모니터링 스택(TD-015)을 설치하고 Grafana의 서비스별 알림을 시험한다.
4. `health-check.yaml`과 EventBridge의 Health check 규칙을 삭제한다. EventBridge는 Auto release만 실행한다.

**감수하는 단점:**

- **Backend는 외부에서 직접 보지 못한다.** Sentry는 2xx만 정상으로 보므로 401을 돌려주는 `/api`를 감시 대상으로 쓸 수 없다. Backend 장애는 Grafana 내부 알림에 맡긴다. 그래서 **3단계 전에 Actions Health check를 지우면 Backend가 죽어도 Nginx가 응답해 알림이 오지 않는다.** Nginx → Backend 공개 라우팅(rewrite) 오류는 외부에서 직접 잡지 못한다.
- **인증서 검증 여부가 문서에 없다.** 2단계 시험 결과에 따라 blackbox 보완이 필요할 수 있다.
- **구간별 응답 코드가 사라진다.** 지금 알림은 `nginx=… frontend=… backend=…`로 원인 구간을 보여 준다. Sentry 알림은 `/healthz`의 정상·장애만 알려 주므로 Grafana의 서비스별 알림과 함께 본다.
- **설정이 인프라 코드에 남지 않는다.** 등록한 URL·주기·실패 기준·알림 대상을 [운영 절차](v1-operations.md)나 이 문서에 기록하고, 바꿀 때 팀에 공유한다.
- **계정을 공유한다.** 무료 요금제는 사용자 1명이라 로그인 정보를 함께 쓴다. 비밀번호·2단계 인증 관리자를 정하고, 계정 담당이 바뀌면 감시도 함께 넘긴다. 계정 접근을 잃으면 외부 감시도 함께 잃는다.
- **Sentry 장애 때 외부 감시가 멈춘다.** GitHub에 의존하던 것이 Sentry로 옮겨 갈 뿐이다. CloudWatch(EC2 상태)·Grafana(서비스별)는 계속 동작한다.

**재검토:**

- 팀이 Sentry 계정을 함께 쓰지 않게 되거나 무료 한도가 바뀌면 Route 53 안(위 표)을 다시 검토한다.
- 로그인 같은 업무 흐름 검사가 필요해지면 Synthetics를 검토한다.
- V2(ECS)에서 ALB를 쓰면 대상 그룹 health check와 정상 호스트 수·5xx 알람, ACM 인증서 자동 갱신으로 범위가 바뀌므로 외부 감시 구성을 다시 정한다.

## 이후 기록 양식

새 결정은 위 목록에 번호를 추가하고 이 파일 아래에 기록한다: 날짜/상태 → 맥락 → 대안 비교 → 선택·판단 이유 → 감수하는 단점 → 재검토 조건. 운영 명령의 상세는 Runbook에 두고 결정 이유는 이 문서에서 찾을 수 있게 한다.
