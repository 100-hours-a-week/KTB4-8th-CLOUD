# Spring 서비스 공통 values

Spring 7개(auth·member·youtube·worker·wishlist·chat·recommend)는 같은 `keepgo-backend` 이미지를 쓴다.
ApplicationSet(`argocd/applicationsets/apps-<env>.yaml`)이 Spring 서비스에만 아래 순서로 values를 겹친다. 뒤 파일이 이긴다.

1. `_shared/spring.yaml` — 환경 공통
2. `_shared/spring-<env>.yaml` — 환경별(**이미지 태그는 여기 한 곳**, DB·Redis·Secret 경로)
3. `<namespace>/<서비스>/values.yaml`
4. `<namespace>/<서비스>/values-<env>.yaml`

이미지 태그를 한 곳에 두는 이유: 7개 서비스가 같은 이미지라 태그가 어긋나면 서비스마다 다른 코드가 돈다.
코드가 서비스별로 나뉘면 서비스 `values-<env>.yaml`에 `image.tag`를 적어 덮어쓴다.
