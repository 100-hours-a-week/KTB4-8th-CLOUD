# 2026-10-14 개발 CI 실패로 V2 배포 후보가 생성되지 않음

작성: 2026-10-15. 상태: CI 브랜치 연결은 완료, 앱 빌드·FE 준비는 별도 후속 작업. 아래 SHA와 실행 상태는 당시 확인 기록이다.

## 🐞 에러 내용

V2 인프라와 중앙 CD가 준비돼 있어도 모든 앱이 배포 대상에 나타나지는 않았다. 초기에는 CI 브랜치 조건이 실제 개발 브랜치와 달랐고, 이를 수정한 뒤에는 앱 자체의 빌드 실패·소스 준비 상태가 드러났다.

| 대상 | 확인한 상태 |
| --- | --- |
| BE 초기 연결 | 기존 CI가 삭제된 `dev`를 대상으로 하며 실제 개발 브랜치는 `develop` |
| AI 초기 연결 | 기존 CI가 develop 이미지 게시를 실행하지 않음 |
| BE 후속 커밋 | compileJava 실패로 ECR 게시 단계까지 진행하지 못함 |
| FE 초기 연결 | develop에 앱 소스가 없어 `Check frontend source`에서 실패 |

## 🔍 원인 분석

**CI 연결 문제:** CI 파일이 없는 것이 아니라 기존 trigger/게시 조건을 실제 브랜치에 맞춰야 했다. BE·AI `develop`의 게시 job은 중앙 CD가 확인하는 `Dev - Build and Push Image` 이름과 일치해야 한다.

**BE 앱 빌드 문제:** CI 수정 PR 병합 후 첫 develop 빌드·게시에는 성공했다. 이후 앱 커밋에서 다음 오류가 발생했다.

```text
src/main/java/eightjbbm/keepgo/util/dto/RecommendCourseRequest.java:45:
error: incompatible types: BusinessHours cannot be converted to String
    place.getBusinessHours()
```

[run 38513646928](https://github.com/100-hours-a-week/KTB4-8th-BE/actions/runs/38513646928), SHA `466a61b312f3dd9115e48a78e41966c88ed1025a`의 로그에서 확인했다. 이후 확인한 `2f49aaa3c2c830c3b600e4bbfa78bce4755f456b`도 [CI 실패](https://github.com/100-hours-a-week/KTB4-8th-BE/actions/runs/38515211101) 상태였다. 후속 커밋의 원인은 그 실행 로그를 다시 확인해야 한다.

실패 단계는 AWS OIDC 인증보다 앞선 애플리케이션 빌드다. IAM을 넓혀도 컴파일 오류는 해결되지 않는다. 중앙 CD는 최신 개발 커밋의 성공한 게시 CI만 선택하므로 다음과 같이 후보 없음으로 처리한다.

```text
backend: no successful development image publishing run
```

**FE 준비 문제:** [CI run 38510126659](https://github.com/100-hours-a-week/KTB4-8th-FE/actions/runs/38510126659)는 `Detect application source`에서 실패했고 품질 검사·이미지 게시 job은 skipped였다. CI 추가만으로 앱 소스나 정적 배포 산출물이 생기지는 않는다.

FE 작업 초기에 `feat/v1` 기반 브랜치를 develop으로 비교했을 때 CI 외 V1 앱 코드 87개 파일이 포함되는 문제도 발견했다. 이를 병합하지 않고 develop 기준 CI 파일 하나만 바꾸는 브랜치를 새로 구성했다. 실제로 앱 코드를 잘못 병합한 사고는 아니다.

## ✅ 해결 방법

CI 연결은 아래 PR로 완료했다. 각 앱 PR은 CI 파일 하나만 수정했다.

- [BE #171](https://github.com/100-hours-a-week/KTB4-8th-BE/pull/171): develop push와 게시 job 이름 수정.
- [AI #45](https://github.com/100-hours-a-week/KTB4-8th-AI/pull/45): develop push 게시·PR 검사 연결.
- [FE #9](https://github.com/100-hours-a-week/KTB4-8th-FE/pull/9): develop 품질 검사 trigger와 소스 부재 실패 처리. 이미지 게시 조건은 기존 main 유지.

BE 오류를 건너뛰거나 실패한 커밋을 Manifest에 강제로 넣지 않았다. 앱 담당자가 타입 계약을 맞춘 후 새 develop 커밋의 CI와 ECR 게시 성공을 확인해야 한다. 자동화는 이미 활성화돼 있으므로 성공한 새 후보가 생기면 중앙 CD가 이를 조회해 배포한다.

AI는 별도로 성공한 후보를 검증해 [최초 V2 배포를 완료](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38579911433)했다. BE 실패 때문에 정상 AI 후보까지 막지는 않았다.

FE는 develop의 앱 준비와 S3 정적 export 가능 여부, API/OAuth 라우팅을 확인한 후 S3/CloudFront 배포를 연결해야 한다. 이번 CI 변경에는 S3 게시 job이 포함되지 않는다. 후속 앱 소스 반영 여부는 해당 브랜치의 최신 상태를 기준으로 다시 확인한다.

## 회고

문제를 trigger 미실행, 앱 빌드 실패, 이미지 게시 실패, 중앙 후보 제외, ECS 배포 실패 단계로 나누면 불필요한 IAM/CD 수정을 줄일 수 있다. CI가 성공했다는 사실도 실제 수행한 검사 범위와 함께 기록해야 한다.

FE처럼 운영·개발 브랜치의 이력이 다를 때는 PR 대상 브랜치를 먼저 확정하고 변경 파일 목록을 확인한다. 이전 성공 CI를 최신 개발 커밋의 성공으로 대신 취급하지 않는다.
