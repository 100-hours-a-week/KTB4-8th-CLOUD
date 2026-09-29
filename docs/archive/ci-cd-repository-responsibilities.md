# Repository별 CI/CD 구성 및 책임

> **보관 기록 — 현재 실행 지침 아님.** 아래 내용은 당시의 제안·관찰·미완료 작업을 보존한 것이다. 현재 전 서비스 자동 CD의 [전체 설명](../v1-design.md)과 [운영 절차](../v1-operations.md)를 우선한다. 대체 이유는 [TD-008](../technical-decisions.md#td-008--최소-구성으로-재작성-전-서비스-자동-cd)에 있다.


## 1. 문서 목적

현재 Frontend, Backend, AI, Cloud가 각각 별도 Repository로 관리되고 있으며, 기존의 중앙 집중식 CD를 애플리케이션별 독립 CD로 전환한다.

기본 원칙은 다음과 같다.

1. 각 애플리케이션 팀은 자신의 소스, 이미지, 배포 시점을 책임진다.
2. Cloud 팀은 각 팀이 안전하게 배포할 수 있는 공용 배포 플랫폼을 책임진다.
3. `compose.yaml`과 EC2 내부 배포 구현은 Cloud Repository에서 한 벌만 관리한다.
4. 일반적인 애플리케이션 배포에서는 전체 Compose를 다시 올리지 않고 변경된 서비스만 교체한다.
5. 전체 릴리스, 장애복구 및 공용 설정 변경은 Cloud Repository에서 수행한다.

## 2. Repository별 최종 책임

| Repository | 최종 책임 |
| --- | --- |
| Frontend | Frontend 품질, Web 이미지, Web 단독 배포, 외부 화면 확인 |
| Backend | API/Worker 품질, DB Migration, Backend·Worker 이미지 및 배포 |
| AI | AI API 품질, AI 이미지 및 배포, AI 기능 확인 |
| Cloud | AWS 인프라, Compose, 공용 배포·롤백, 모니터링, 운영환경 안정성 |

전체 배포 흐름은 다음과 같다.

```text
Application Main Merge
        ↓
각 Application Repository에서 테스트
        ↓
Docker Image Build 및 ECR Push
        ↓
AWS SSM으로 EC2에 서비스 배포 요청
        ↓
Cloud가 관리하는 deploy-service.sh 실행
        ↓
해당 Container만 교체
        ↓
Health Check 및 Smoke Test
```

## 3. Frontend Repository

### 3.1 권장 파일 구조

```text
frontend/
├── .github/
│   └── workflows/
│       ├── pr-ci.yml
│       └── production-cd.yml
├── Dockerfile
├── .dockerignore
├── nginx/
│   └── default.conf
├── scripts/
│   └── smoke-test.sh
├── src/
├── package.json
├── package-lock.json
├── tsconfig.json
├── eslint.config.js
└── README.md
```

### 3.2 파일별 역할

| 파일 | 내용 | 책임 |
| --- | --- | --- |
| `.github/workflows/pr-ci.yml` | ESLint, Type Check, Test, Frontend Build, Docker Build | Main에 깨진 코드가 들어오는 것 차단 |
| `.github/workflows/production-cd.yml` | Main 검증, ECR Push, SSM 배포 요청, Smoke Test | Frontend 운영 배포 |
| `Dockerfile` | Frontend 정적 파일 빌드 및 Nginx 이미지 생성 | 재현 가능한 Web 이미지 생성 |
| `.dockerignore` | `node_modules`, 테스트 결과 등 이미지 제외 | 빌드 속도와 이미지 크기 관리 |
| `nginx/default.conf` | SPA Routing, Backend Reverse Proxy, Cache 설정 | Web Container 동작 정의 |
| `scripts/smoke-test.sh` | 운영 URL 호출 및 HTTP 상태 확인 | 배포 후 외부 접근 검증 |
| `package.json` | `lint`, `typecheck`, `test`, `build` 명령 표준화 | CI가 사용할 명령 계약 |
| `README.md` | Local 실행, 환경변수, CI/CD 및 배포 절차 | Frontend 운영 문서 |

### 3.3 PR CI

```text
npm ci
→ npm run lint
→ npm run typecheck
→ npm test
→ npm run build
→ docker build
```

PR에서는 이미지를 ECR에 Push하지 않는다.

### 3.4 Main CI/CD

```text
Test 및 Build 재검증
→ keepgo-web:${GITHUB_SHA} Build
→ ECR Push
→ deploy-service.sh web ${GITHUB_SHA}
→ 운영 URL Smoke Test
```

### 3.5 Frontend 책임 범위

- Frontend 소스 품질
- Nginx 애플리케이션 설정
- `/api` Proxy 경로 요구사항
- Web 이미지 정상 실행
- Browser에서 접근 가능한지 확인
- 배포 실패 시 Frontend 이미지 Rollback 요청

AWS Network, EC2 및 TLS 인증서 자체 관리는 Cloud 책임이다.

## 4. Backend Repository

### 4.1 권장 파일 구조

```text
backend/
├── .github/
│   └── workflows/
│       ├── pr-ci.yml
│       └── production-cd.yml
├── Dockerfile
├── Dockerfile.worker
├── .dockerignore
├── gradlew
├── gradlew.bat
├── build.gradle
├── settings.gradle
├── src/
│   ├── main/
│   │   ├── java/
│   │   └── resources/
│   │       ├── application.yml
│   │       ├── application-prod.yml
│   │       ├── application-worker.yml
│   │       └── db/migration/
│   └── test/
├── scripts/
│   ├── smoke-test.sh
│   └── worker-health-check.sh
└── README.md
```

Worker가 Backend와 동일 이미지이고 실행 Profile만 다르면 `Dockerfile.worker`는 생략할 수 있다. 현재처럼 ECR 이미지가 분리되어 있다면 별도 Dockerfile 또는 Docker Build Target을 사용할 수 있다.

### 4.2 파일별 역할

| 파일 | 내용 | 책임 |
| --- | --- | --- |
| `.github/workflows/pr-ci.yml` | Unit Test, Spring Build, Docker Build | Backend 코드·Artifact·이미지 검증 |
| `.github/workflows/production-cd.yml` | Backend/Worker 이미지 Push 및 개별 배포 | Backend 운영 배포 |
| `Dockerfile` | Backend API 이미지 생성 | API 실행환경 정의 |
| `Dockerfile.worker` | Worker 이미지 생성 | Worker 실행환경 정의 |
| `application-prod.yml` | 운영 API 설정 | Backend 운영 Profile |
| `application-worker.yml` | Worker 설정 | Worker 운영 Profile |
| `db/migration/` | Flyway/Liquibase Migration | DB Schema 버전 관리 |
| `scripts/smoke-test.sh` | Nginx를 통한 Backend API 요청 | 외부 요청 경로 검증 |
| `scripts/worker-health-check.sh` | Worker Process 및 작업 상태 확인 | Worker 배포 검증 |
| `README.md` | Profile, Secret, Migration 및 배포 방법 | Backend 운영 문서 |

### 4.3 PR CI

```text
./gradlew test
→ ./gradlew bootJar
→ Backend Docker Build
→ Worker Docker Build
```

DB 관련 장애가 반복되면 Testcontainers 기반 Integration Test를 추가한다.

### 4.4 Main CI/CD

```text
Test 및 Build 재검증
→ Backend/Worker 이미지 Build
→ ECR Push
→ DB Migration
→ Backend 배포
→ Backend Health Check
→ Worker 배포
→ Worker 상태 확인
→ 외부 Smoke Test
```

권장 배포 순서는 다음과 같다.

```text
Migration → Backend → Health Check → Worker → Worker Check
```

### 4.5 Backend 책임 범위

- API Logic과 Test
- Backend/Worker 실행 Profile
- DB Migration 작성 및 호환성
- Actuator Health Endpoint
- Backend와 AI 간 Request/Response Schema
- Worker Batch Size와 Concurrency 요구사항
- Backend/Worker 이미지 Rollback 가능 여부

Cloud는 DB Network와 Secret 접근 권한을 담당하지만, DB Schema와 Migration 내용은 Backend 책임이다.

## 5. AI Repository

### 5.1 권장 파일 구조

```text
ai/
├── .github/
│   └── workflows/
│       ├── pr-ci.yml
│       └── production-cd.yml
├── Dockerfile
├── .dockerignore
├── pyproject.toml
├── uv.lock
├── api/
│   └── main.py
├── tests/
├── scripts/
│   └── smoke-test.sh
└── README.md
```

`requirements.txt`를 사용하는 프로젝트라면 `pyproject.toml`, `uv.lock` 대신 기존 의존성 관리 방식을 유지해도 된다.

### 5.2 파일별 역할

| 파일 | 내용 | 책임 |
| --- | --- | --- |
| `.github/workflows/pr-ci.yml` | Ruff Lint, Format Check, Pytest, Docker Build | Python 코드와 실행환경 검증 |
| `.github/workflows/production-cd.yml` | AI 이미지 Push 및 AI API 배포 | AI 운영 배포 |
| `Dockerfile` | Uvicorn 기반 AI API 이미지 생성 | AI 실행환경 정의 |
| `.dockerignore` | Cache, Model 임시 파일, 테스트 결과 제외 | 이미지 크기 관리 |
| `pyproject.toml` | Python 의존성, Ruff, Pytest 설정 | 개발·CI 설정 단일화 |
| `uv.lock` | 의존성 버전 고정 | 재현 가능한 이미지 생성 |
| `api/main.py` | FastAPI 진입점과 `/health` 제공 | Container 기동 및 상태 확인 |
| `scripts/smoke-test.sh` | 운영 AI API 호출 | 배포 후 실제 동작 검증 |
| `README.md` | Model, Provider, Secret 및 API 계약 | AI 운영 문서 |

### 5.3 PR CI

```text
ruff check
→ ruff format --check
→ pytest
→ docker build
```

AI 인원이 2명이므로 Lint와 Format Check를 CI에서 강제한다.

### 5.4 Main CI/CD

```text
Test 재검증
→ keepgo-ai:${GITHUB_SHA} Build
→ ECR Push
→ deploy-service.sh ai-api ${GITHUB_SHA}
→ /health 확인
→ 필요 시 간단한 추론 Smoke Test
```

### 5.5 AI 책임 범위

- AI API 코드와 Test
- `/health` Endpoint
- Model Provider 설정 요구사항
- Backend와의 Request/Response Schema
- LLM 장애 시 오류 처리
- API 이미지 정상 기동
- AI 기능 Smoke Test

Cloud는 Gemini Secret 접근 권한을 제공하고, Secret에 필요한 필드와 사용 방법은 AI가 정의한다.

## 6. Cloud Repository

### 6.1 권장 파일 구조

```text
cloud/
├── .github/
│   └── workflows/
│       ├── pr-ci.yml
│       ├── deploy-platform.yml
│       └── deploy-full-release.yml
├── compose.yaml
├── .env.example
├── scripts/
│   ├── validate-compose.py
│   ├── deploy-service.sh
│   ├── deploy-full-release.sh
│   ├── rollback-service.sh
│   ├── bootstrap-server.sh
│   └── health-check.sh
├── deployment/
│   └── release-manifest.example.yaml
├── infrastructure/
│   ├── environments/
│   │   └── production/
│   └── modules/
├── monitoring/
│   ├── cloudwatch/
│   └── alarms/
├── docs/
│   ├── deployment.md
│   ├── rollback.md
│   └── incident-response.md
└── README.md
```

Terraform을 아직 사용하지 않는다면 `infrastructure/`는 나중에 추가할 수 있다.

### 6.2 파일별 역할

| 파일 | 내용 | 책임 |
| --- | --- | --- |
| `.github/workflows/pr-ci.yml` | Compose Validation, Shell Syntax, IaC Validation | 잘못된 운영 설정 Merge 방지 |
| `.github/workflows/deploy-platform.yml` | Compose·Script 변경을 EC2에 반영 | 배포 Platform 업데이트 |
| `.github/workflows/deploy-full-release.yml` | 전체 서비스 일괄 배포 | 정식 Release·장애복구 |
| `compose.yaml` | 서비스, Network, 환경변수, Log 정의 | 운영 Container 구성의 원본 |
| `.env.example` | 필요한 Tag와 Account 변수 목록 | 운영 환경변수 계약 |
| `scripts/validate-compose.py` | Compose 구조와 필수 설정 검사 | 설정 정합성 검증 |
| `scripts/deploy-service.sh` | 특정 서비스만 안전하게 배포 | 독립 CD 공용 Interface |
| `scripts/deploy-full-release.sh` | 전체 서비스를 지정 버전으로 배포 | 전체 Release 및 복구 |
| `scripts/rollback-service.sh` | 특정 서비스를 이전 버전으로 복구 | 장애 대응 |
| `scripts/bootstrap-server.sh` | 신규 EC2에 Docker, 경로, 권한 설정 | Server 초기 구성 |
| `scripts/health-check.sh` | 공통 Container 상태 검사 | 배포 성공 판정 |
| `deployment/release-manifest.example.yaml` | 전체 Release 버전 형식 예시 | 재해복구 및 Snapshot |
| `infrastructure/` | IAM, ECR, EC2, SSM, Security Group, Log Group | AWS 인프라 관리 |
| `monitoring/` | CloudWatch Metric·Alarm 정의 | 운영 관측성 |
| `docs/` | 배포·Rollback·장애 대응 Runbook | 운영 지식 관리 |

### 6.3 기존 파일 처리

| 현재 파일 | 처리 |
| --- | --- |
| `compose.yaml` | 유지 |
| `scripts/deploy.sh` | `deploy-service.sh`, `deploy-full-release.sh`로 분리 |
| `scripts/validate-manifest.py` | `validate-compose.py` 중심으로 변경 |
| `deployment/production-manifest.yaml` | 일상 배포에서 제외하고 전체 Release Snapshot으로만 사용 |
| `.github/workflows/validate.yaml` | Cloud PR CI로 유지 |
| `.github/workflows/deploy-production.yaml` | 전체 Release 또는 Platform 배포용으로 축소 |
| `README.md` | Server 구조·배포 Interface·복구 절차 추가 |

### 6.4 Cloud PR CI

```text
docker compose config --quiet
→ ShellCheck
→ bash -n scripts/*.sh
→ Python Validation Test
→ Terraform fmt/validate
```

### 6.5 Cloud Main CD

Cloud Main Merge가 애플리케이션 이미지를 새로 배포하면 안 된다.

```text
Compose/Script/IaC 검증
→ EC2의 Cloud Repository 업데이트
→ 변경된 Platform 설정 반영
→ 기존 서비스 Health Check
```

`compose.yaml` 수정으로 Container 재생성이 필요한 경우에만 영향받는 서비스를 명시적으로 반영한다.

## 7. `deploy-service.sh` 계약

각 Application Repository는 SSM을 통해 이 Script만 호출한다.

```bash
deploy-service.sh <service> <commit-sha>
```

사용 예시는 다음과 같다.

```bash
deploy-service.sh web abcdef0123456789abcdef0123456789abcdef01
deploy-service.sh backend abcdef0123456789abcdef0123456789abcdef01
deploy-service.sh worker abcdef0123456789abcdef0123456789abcdef01
deploy-service.sh ai-api abcdef0123456789abcdef0123456789abcdef01
```

내부 서비스 Mapping은 Cloud가 관리한다.

| 입력 서비스 | ECR Repository | Compose 서비스 | Tag 변수 |
| --- | --- | --- | --- |
| `web` | `keepgo-web` | `web` | `WEB_IMAGE_TAG` |
| `backend` | `keepgo-backend` | `backend` | `BACKEND_IMAGE_TAG` |
| `worker` | `keepgo-worker` | `worker` | `WORKER_IMAGE_TAG` |
| `ai-api` | `keepgo-ai` | `ai-api` | `AI_IMAGE_TAG` |

`deploy-service.sh`는 다음 작업을 수행해야 한다.

1. 서비스 이름 Allowlist 검사
2. Commit SHA 형식 검사
3. 서버 전체 배포 Lock 획득
4. 이전 이미지 Tag 저장
5. ECR Login
6. 대상 이미지 Pull
7. Runtime `.env`를 임시 파일로 수정
8. `.env`를 원자적으로 교체
9. 대상 서비스만 `up -d --no-deps`로 반영
10. Health Check 수행
11. 실패하면 이전 Tag로 Rollback
12. 배포 이력 기록

개별 배포에서는 다음 명령을 사용하지 않는다.

```bash
docker compose up -d --remove-orphans
```

대신 대상을 명시한다.

```bash
docker compose up -d --no-deps backend
```

## 8. 운영 상태 파일

운영 중인 이미지 Tag는 Git이 아니라 EC2 Runtime 경로에서 관리한다.

```text
/opt/keepgo/
├── cloud/
│   ├── compose.yaml
│   └── scripts/
└── runtime/
    ├── production.env
    ├── deployment.lock
    └── history/
```

`production.env` 예시는 다음과 같다.

```dotenv
AWS_ACCOUNT_ID=123456789012

WEB_IMAGE_TAG=<40자리 SHA>
BACKEND_IMAGE_TAG=<40자리 SHA>
WORKER_IMAGE_TAG=<40자리 SHA>
AI_IMAGE_TAG=<40자리 SHA>
```

이 파일에는 이미지 Tag와 비밀이 아닌 설정만 저장한다. DB Password, JWT Secret 및 Gemini Key 등은 AWS Secrets Manager에 저장한다.

## 9. 동시 배포 제어

GitHub Actions의 `concurrency`는 서로 다른 Repository 사이에서 공유되지 않는다. 따라서 Frontend와 Backend가 동시에 EC2 배포를 시작할 수 있으므로 EC2에서 Host 단위 Lock을 사용해야 한다.

```bash
flock /opt/keepgo/runtime/deployment.lock \
  /opt/keepgo/cloud/scripts/deploy-service.sh backend "$IMAGE_TAG"
```

실제 구현에서는 `deploy-service.sh` 내부에서 Lock을 획득하도록 한다.

Cloud 팀은 다음을 책임진다.

- 배포 Lock
- `.env` 동시 수정 방지
- 원자적 파일 교체
- 배포 Timeout
- 자동 Rollback 처리

각 Application 팀은 같은 서비스의 중복 배포를 방지한다.

```yaml
concurrency:
  group: frontend-production
  cancel-in-progress: false
```

## 10. GitHub Environment와 AWS 권한

각 Application Repository에는 `production` Environment를 구성한다.

### 10.1 GitHub Variables

```text
AWS_REGION
AWS_DEPLOY_ROLE_ARN
PRODUCTION_EC2_INSTANCE_ID
ECR_REPOSITORY
PRODUCTION_BASE_URL
```

장기 AWS Access Key는 저장하지 않고 GitHub OIDC를 통해 IAM Role을 Assume한다.

### 10.2 권한 분리

| Role | 권한 |
| --- | --- |
| Frontend Deploy Role | `keepgo-web` ECR Push, Web 배포 SSM 실행 |
| Backend Deploy Role | Backend/Worker ECR Push, Backend/Worker SSM 실행 |
| AI Deploy Role | `keepgo-ai` ECR Push, AI 배포 SSM 실행 |
| Cloud Deploy Role | EC2/SSM/IAM/Compose/전체 배포 관리 |

가능하면 SSM Document에서 허용된 서비스 이름만 입력받도록 제한한다.

## 11. 검증 Matrix

| 시점 | 대상 | 수행 검증 | 확인 목적 | 왜 여기서 하는가 | 책임 |
| --- | --- | --- | --- | --- | --- |
| 개발자 Local | 각 Repository | 필요 시 Lint / Format / Unit Test | PR 전 빠른 오류 확인 | 개발자가 가장 빠르게 수정 가능 | 각 개발자 |
| PR CI | Frontend | ESLint → Type Check → Test → Frontend Build → Docker Build | Source와 Image 생성 확인 | 깨진 Frontend의 Main Merge 차단 | Frontend |
| PR CI | Backend | Unit Test → BootJar → Backend/Worker Docker Build | Logic, Compile, Artifact, Image 확인 | Backend 오류의 Main 유입 차단 | Backend |
| PR CI | AI | Ruff Lint → Format Check → Pytest → Docker Build | 코드 품질과 실행환경 확인 | AI 병렬 작업 시 품질 통일 | AI |
| PR CI | Cloud | Compose Validation → ShellCheck → Script Syntax → IaC Validation | 배포 설정 문법 확인 | 운영 설정 오류 차단 | Cloud |
| Main CI | Frontend | PR 검증 재실행 → Image Build | 운영 후보 Source 확정 | Merge된 Commit 기준 재검증 | Frontend |
| Main CI | Backend | Test → BootJar → Image Build | 운영 Artifact 확정 | Merge된 Commit 기준 재검증 | Backend |
| Main CI | AI | Ruff → Pytest → Image Build | 운영 AI Artifact 확정 | Merge된 Commit 기준 재검증 | AI |
| Main CI | Application | Commit SHA 이미지 ECR Push | 불변 이미지 게시 | 검증된 Main Commit만 배포 가능 | 해당 Application 팀 |
| CD | Application | SSM 단일 서비스 배포 요청 | 해당 서비스만 교체 | 다른 팀 배포를 기다리지 않음 | 해당 Application 팀 |
| CD 내부 | EC2 | Lock → Pull → Container 교체 | 안전한 Compose 반영 | 공용 서버 동시 변경 방지 | Cloud Platform |
| 배포 후 | 각 Container | Health Check | Process 정상 기동 확인 | 실제 EC2에서만 판정 가능 | Application + Cloud |
| 배포 후 | Nginx → Backend | 외부 Smoke Test | Proxy, TLS, Port, API 경로 검증 | 전체 요청 경로 확인 | Frontend/Backend, Cloud 협업 |
| 배포 후 | AI API | `/health` 및 최소 추론 Test | AI Container와 Provider 확인 | 실제 운영환경 검증 | AI |
| 배포 실패 | 대상 서비스 | 이전 SHA Rollback | 장애 영향 최소화 | 배포 Platform이 일관되게 처리 | Cloud 자동화, Application 판단 |
| 향후 | Backend ↔ PostgreSQL | Integration Test | Query와 Migration 확인 | DB 장애가 반복될 때 추가 | Backend |
| 향후 | Worker ↔ PostgreSQL | Integration Test | Job Claim과 상태 변경 확인 | Worker DB 장애가 반복될 때 추가 | Backend |
| 향후 | Backend ↔ AI | Contract Test | API Schema 일치 확인 | 양 팀 변경 충돌 방지 | Backend + AI |
| 현재 제외 | 전체 시스템 | 전체 E2E Test | 로그인 → Sync → 추천 전체 흐름 | 현재 규모 대비 구축·유지 비용이 큼 | 추후 공동 결정 |

## 12. 장애별 최종 책임

| 장애 | 1차 책임 | 협업 |
| --- | --- | --- |
| ESLint, TypeScript 오류 | Frontend | 없음 |
| Spring Compile, Unit Test 오류 | Backend | 없음 |
| Ruff, Pytest 오류 | AI | 없음 |
| Dockerfile Build 오류 | 해당 Application 팀 | Cloud 자문 |
| ECR Push 권한 오류 | Cloud | 해당 Application 팀 |
| SSM 호출 실패 | Cloud | 해당 Application 팀 |
| Container 즉시 종료 | 해당 Application 팀 | Cloud Log 제공 |
| Compose/Network 오류 | Cloud | 해당 Application 팀 |
| Nginx 설정 오류 | 설정 성격에 따라 Frontend 또는 Cloud | 공동 |
| Backend API 500 | Backend | Cloud Log 제공 |
| AI API 500 | AI | Cloud Log 제공 |
| DB Migration 실패 | Backend | Cloud DB 접근 확인 |
| TLS, DNS, Security Group | Cloud | 없음 |
| CloudWatch Log 미수집 | Cloud | 해당 Application의 Log 형식 확인 |
| 이미지 Rollback 결정 | 해당 Application 팀 | Cloud 자동화 실행 |
| 전체 장애 복구 | Cloud | 모든 Application 팀 |

## 13. 적용 우선순위

### 1단계: 독립 이미지 생성

- 각 Application Repository에 PR CI 구성
- 각 Application Repository에서 Main Commit SHA 이미지 생성
- 각 Application Repository에서 ECR Push

### 2단계: 독립 서비스 배포

- Cloud Repository에 `deploy-service.sh` 구현
- EC2 배포 Lock 구현
- Application별 SSM 배포 요청 구성
- 서비스별 Health Check 구현

### 3단계: 안전장치

- 자동 Rollback
- 배포 이력 관리
- CloudWatch Alarm
- GitHub Production Environment 승인 규칙

### 4단계: 확장 검증

- DB Integration Test
- Backend-AI Contract Test
- 장애 빈도에 따라 필요한 E2E Test 추가

## 14. 핵심 원칙 요약

1. 각 Application 팀은 자신의 이미지를 만들고 자신의 서비스 배포를 시작한다.
2. Cloud 팀은 모든 서비스가 사용하는 안전한 배포 Interface를 만든다.
3. Application Repository는 공용 `compose.yaml`이나 EC2 내부 구현을 직접 소유하지 않는다.
4. 일반 배포는 `--no-deps`로 대상 서비스만 교체한다.
5. 전체 배포와 장애복구는 Cloud Repository에서 수행한다.
6. 배포 상태와 비밀정보는 Git에 Commit하지 않는다.
