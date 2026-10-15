# 2026-10-02 로그인 실패 — 같은 증상, 다른 원인 셋

## 🐞 에러 내용

챗봇·추천 핫픽스를 테스트하는 동안 로그인이 세 번 막혔다. 증상은 모두 "로그인했는데 다시 로그인 화면"이었다.

| 시각 (KST) | 증상 | 원인 |
| --- | --- | --- |
| 10-02 22:17~23:00 | 로그인해도 바로 `/login`으로 돌아옴. `/home` 404 | FE `58d7cdb` |
| 10-03 01:31 | Google 화면 뒤 `/login?error` | OAuth 콜백 중복 |
| 10-03 02:10 | 잘 쓰던 세션이 "다시 로그인" | BE 재배포로 리프레시 토큰 유실 |

## 🔍 원인 분석

### 1. FE 커밋이 토큰 수신 페이지를 지움

web 접근 로그(22:51 KST)에서 같은 패턴이 8번 반복됐다.

```
GET /oauth2/authorization/google                          302
GET /login/oauth2/code/google?...                         (BE 처리)
GET /?accessToken=***&expiresIn=1800&initialLogin=false   200   ← BE 로그인 성공
GET /login?_rsc=...                                       200   ← FE가 곧바로 로그인 화면으로
```

- BE는 로그인 성공 뒤 `/?accessToken=...`으로 리다이렉트한다(`OidcLoginSuccessHandler.java:109`).
- 원래 `src/app/page.tsx`가 이 토큰을 세션에 저장했다. `58d7cdb`가 이 파일을 지우고 홈을 `/`로 옮겼다.
- 이제 `/`에서는 `(app)/layout.tsx`가 먼저 실행돼 세션이 없다고 보고 `/login`으로 보냈다.
- 커밋 메시지는 "토큰 처리를 `(app)/layout.tsx`로 합치고 `/home` 참조를 `/`로 수정"이었지만, 실제 커밋에는 파일 2개만 있었다. `/home` 참조 6곳도 그대로였다. 로컬 수정이 커밋에서 빠진 것으로 보인다.

이때 팀에서 "운영 DB에 `oauth2_authorized_client` 테이블이 없어서"라는 분석이 들어왔다. 로그로 확인해 기각했다.
- 같은 시각 BE `OidcLoginSuccessHandler`가 `loadAuthorizedClient` null 검사 뒤의 `name:` 로그를 남겼다. 테이블은 있다.
- 저장소의 오타 경로(`springframwork/.../oauth-client-schema.sql`)는 쓰이지 않는다. yaml이 가리키는 경로는 Spring Security jar 안에 있다.
- 함께 제안된 `spring.sql.init.mode: always`는 위험하다. jar의 스키마가 `IF NOT EXISTS` 없는 `CREATE TABLE`이라, 테이블이 이미 있는 운영 DB에서는 BE가 기동할 때마다 실패한다.

### 2. 같은 state로 콜백이 두 번 들어옴

```
01:31:38  GET /login/oauth2/code/google?state=boac5j…  499   ← 브라우저가 응답 전에 끊음
01:31:39  GET /login/oauth2/code/google?state=boac5j…  302   ← 같은 state, 다른 code
01:31:39  GET /login?error
```

- 첫 요청을 BE가 처리하며 state를 소비했지만, 브라우저가 이미 끊어 토큰이 전달되지 않았다.
- 두 번째 요청은 `authorization_request_not_found`로 실패했다.
- `LoginFilterChainConfig`의 `oauth2Login`에 `failureHandler`가 없어 Spring 기본값 `/login?error`로 갔다.
- 같은 패턴이 01:03(다른 사용자)과 22:54에도 있었다. 다시 시도하면 대부분 성공한다. Google 화면에서 두 번 누르는 경우로 보이지만, 서버 로그만으로는 확정하지 못했다.

### 3. BE 재배포 때마다 전원 로그아웃

BE가 리프레시 토큰 해시를 Caffeine 메모리 캐시(`rtHash`)에 둔다. BE 컨테이너가 바뀌면 모든 리프레시 토큰이 사라지고, 액세스 토큰(30분)이 만료되는 순간 다시 로그인해야 한다. 02:10 BE #81 배포 직후 그대로 일어났다.

## ✅ 해결 방법

1. FE 담당자가 22:48 KST에 `58d7cdb`를 되돌리는 `79dbf79`를 push했다. 22:50 Auto release는 FE CI가 시작한 지 1초 만에 돌아 이미지가 없어 건너뛰었고, 23:00 릴리스에서 배포됐다. 23:03 KST 로그인을 확인했다.
2. 콜백 중복은 TODO로 남겼다. 제안은 실패 사유가 `authorization_request_not_found`면 로그인을 한 번 자동으로 다시 시작하고, 60초 안에 다시 실패하면 `/login?error`로 보내는 것이다([팀 공유 문서](../v1-chatbot-recommendation-hotfix.md) 3-3-1).
3. 리프레시 토큰 저장소 이전(DB 또는 외부 저장소)은 BE 수정 요청으로 넘겼다(같은 문서 3-3).

## 회고

- 같은 증상이라도 원인이 매번 달랐다. 추측 대신 web 접근 로그에서 요청 순서(`/?accessToken=` 뒤 `/login`, 같은 state 두 번)를 보면 몇 분 안에 갈렸다. 로그인 문제는 BE 로그보다 web 접근 로그를 먼저 본다.
- 그럴듯한 분석이라도 운영 로그와 맞지 않으면 적용하지 않는다. 이번에 제안된 `spring.sql.init.mode: always`는 적용했다면 로그인 장애를 BE 기동 실패로 키웠다.
- FE 수정이 push된 뒤에도 CI 완료와 Auto release 주기(10분)가 어긋나면 최대 한 주기를 더 기다린다. 급할 때는 FE CI 완료를 확인하고 Auto release를 수동 실행한다.
- 리프레시 토큰이 메모리에 있는 한 배포는 곧 전원 로그아웃이다. 하루 여러 번 배포하는 지금 구조에서는 사용자 경험에 바로 드러나므로 우선순위를 높게 잡았다.
