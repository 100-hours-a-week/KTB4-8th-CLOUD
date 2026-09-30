# 자동 CD와 앱 저장소의 약속

앱 CI의 이미지 게시를 Cloud가 조회해 배포한다. 조회 대상의 실제 저장소·브랜치·workflow·job·서비스 매핑은 [sources.json](../deployment/sources.json), 이미지 주소·포트·healthcheck는 [compose.yaml](../compose.yaml)이 기준이다. 이 문서에는 앱 팀과 Cloud가 유지해야 할 계약을 기록한다.

## 책임

| 담당 | 책임 |
| --- | --- |
| BE·FE·AI 팀 | 코드 품질과 CI, 이미지 빌드·게시, health 응답, 기능 검증, 앱 문제 수정 |
| BE 팀 | 직전 버전과 호환되는 DB 변경, 인증·JWT 동작 |
| FE 팀 | frontend·Nginx 이미지의 같은 커밋 게시, proxy 경로와 앱 호환성 |
| Cloud | 조회 대상 설정, Manifest·Compose, 배포·복구 스크립트, AWS 연결, 장애 조사와 알림 |
| 공동 | Secret 변경, 서비스 간 버전 호환성, 기능 장애의 복구 판단 |

앱 CI에 Cloud PR 생성·SSM 배포 단계를 추가할 필요는 없다. Cloud 자동화의 동작은 [전체 설명](v1-design.md)에 있다.

## 유지해야 할 계약

1. **전체 커밋 SHA(40자리)를 태그로 게시하고 같은 태그를 덮어쓰지 않는다.** Cloud는 digest를 고정하지 않으므로 앱 CI와 ECR 태그 정책으로 이 계약을 유지한다.
2. **지정한 브랜치의 push CI에서 지정 게시 job이 성공해야 한다.** workflow 파일명·job 표시 이름·기준 브랜치 변경 시 sources.json도 수정한다. “게시 job 성공”은 필요한 이미지 게시가 실제 완료됐음을 뜻하도록 앱 CI를 구성한다.
3. **FE는 frontend와 Nginx 이미지를 같은 커밋으로 함께 게시한다.** 정상 배포 목표는 같은 SHA다. 실패 중 실제 버전이 달라질 수 있으므로 두 서비스의 전환 중 호환성을 확인한다.
4. **Compose의 healthcheck가 사용할 경로·도구를 이미지에서 유지한다.** 인증 없이 기동 상태를 확인할 수 있어야 한다. Backend Actuator에 포함되는 의존성 검사의 범위는 BE 팀이 관리한다.
5. **DB schema는 직전 이미지와 호환되게 변경한다.** Cloud의 이미지 복구로 DB schema나 데이터는 복구되지 않는다.
6. **기능 버그는 수정 또는 revert 커밋으로 새 SHA를 게시한다.** CI·게시 성공 후 다음 정상 조회에서 후보가 된다. 긴급 복구는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 6절을 따른다.

## 모니터링 추가 계약

CloudWatch + Prometheus + Grafana 구성은 [모니터링 운영 구성](v1-monitoring.md)을 따른다. 다음 항목은 앱 저장소 변경·검증이 필요하며, Cloud 설정만으로 구현 완료되지 않는다.

- **BE:** Micrometer Prometheus registry, `/actuator/prometheus` 노출과 내부 scrape 접근을 준비한다. 기존 `8080/actuator/health`와 DB 장애 시 503 응답을 유지한다. JVM·HTTP 요청 수/오류/latency histogram·DB pool 지표를 확인한다. Actuator 전체를 무분별하게 공개하지 않는다.
- **AI:** 내부 `/metrics`에서 요청 수·오류·latency histogram을 제공한다. 기존 `/health`는 유지하며 health가 확인하는 의존성 범위를 명시한다.
- **FE/Nginx:** `/metrics`, `/actuator/prometheus` 및 `/api` rewrite를 통한 우회 경로로 메트릭이 외부에 노출되지 않도록 차단한다. stdout/stderr로 access/error 로그를 내보내고 요청 본문·인증 헤더·비밀값을 기록하지 않는다.
- **공통:** metric label에는 정규화된 route·method·status처럼 제한된 값을 쓴다. 사용자 ID·원문 URL·토큰을 label로 쓰지 않는다. 앱 로그도 stdout/stderr로 남기며 비밀값·개인정보를 제외한다.
- **Cloud:** 내부 endpoint 응답·공개 경로 차단 확인 후 `monitoring/prometheus/targets/application.json`에 서비스를 등록한다. 앱 지표의 실제 이름·단위를 확인한 뒤 RED/JVM 대시보드·알림 임계치를 추가한다.

## 브랜치 전환과 검사의 한계

FE의 feat/v1 사용은 임시 결정이다. main으로 전환할 때는 main의 소스·CI 게시 결과·두 이미지가 준비됐는지 확인하고 Cloud 조회 설정을 변경한다. 이유와 당시 확인 기록은 [TD-011](technical-decisions.md#td-011--fe-배포-기준-브랜치)에 있다.

2026-09-29 기존 확인 기록상 BE CI의 bootJar 경로는 테스트를 생략했다. 앱 CI는 별도 저장소에서 바뀔 수 있으므로 현재 검사 범위는 해당 CI에서 다시 확인한다. Cloud가 확인하는 “CI·게시 job 성공”만으로 단위 테스트·업무 E2E 통과를 주장하지 않는다.

Cloud 검사의 정확한 범위는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 3절에 둔다. 앱 팀은 그 검사로 잡히지 않는 기능·추론·서비스 간 계약을 별도로 확인한다.
