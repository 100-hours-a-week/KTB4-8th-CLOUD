# 챗봇·코스 추천 변경 사항 공유 (BE·AI)

2026-10-02~03 챗봇과 코스 추천 장애를 고치면서 Cloud가 BE·AI 저장소에 직접 올린 변경을 공유하고, 조사 중 발견한 수정 필요 사항을 전달하는 문서다. 각 팀은 자기 절(3장 BE, 4장 AI)과 2장(BE↔AI 계약)만 보면 된다.

| 항목 | 내용 |
| --- | --- |
| 기준 배포 | BE `9914e9e`, AI `6e9c5cf`, FE `79dbf79` |
| 현재 상태 | 챗봇 여러 턴 대화, 의도 카드, 코스 추천이 운영 화면에서 동작한다 (10-03 02:16 KST 확인) |
| 임시 운영 | 코스 추천이 **사용자 저장 데이터 대신 대화 조건 + Gemini 웹검색**으로 동작한다. 되돌리는 방법은 3-2, 4-2 |
| 관련 PR | BE #79, #80, #81 / AI #39, #40, #41 |

## 1. 팀별 할 일 요약

| 팀 | 우선순위 | 할 일 | 자세히 |
| --- | --- | --- | --- |
| BE | 높음 | 영상 분석 결과 중 장소명 null을 저장하지 않기, 기존 데이터 정리 | 3-3-2 |
| BE | 높음 | 로그인 중복 콜백 실패 처리 | 3-3-1 |
| BE | 높음 | 배포 때마다 전원 로그아웃되는 문제 (리프레시 토큰 메모리 캐시) | 3-3 |
| BE | 중간 | 추천 취소 연결, 장소 상세, 추천 응답 항목 정리 | 3-3 |
| BE | 낮음 | dev 브랜치에 main 병합 (`7e8b9ad` 대체됨) | 3-4 |
| AI | 중간 | 웹검색 임시 경로를 대체할 정식 후보 탐색 설계 | 4-3 |
| AI | 중간 | 추천 응답 장소에 카테고리 추가 | 4-3 |
| 공통 | 중간 | 장소 좌표 수집 (BE 저장 + AI 계산). 이것이 끝나야 임시조치를 되돌릴 수 있다 | 3-2, 4-2 |

## 2. BE↔AI 계약 (현재 기준)

슬롯 형식이 양쪽에서 달라 챗봇이 실패했다. 지금은 BE가 AI와 통신할 때만 AI 형식으로 변환한다. BE 내부 슬롯(`SlotValue`)은 그대로다.

### 2-1. 슬롯 추출 `POST /v1/extract`

`prev_slot`(요청)과 `slot`(응답)은 같은 형식이다. BE는 `util/dto/AiSlot`로 변환한다.

| 필드 | AI 형식 | BE 내부 (`SlotValue`) | 변환 규칙 |
| --- | --- | --- | --- |
| `origin` | 출발지 이름 (str) | 좌표 `Coordinate` | BE는 보내지 않는다(null). AI 응답 값으로 좌표를 덮어쓰지 않는다 |
| `region` | str | String | 그대로 |
| `datetime` | `"yyyy-MM-dd"` 또는 `"yyyy-MM-dd HH:mm"` | `LocalDateTime` | 시각이 00:00이면 날짜만 보낸다. 날짜만 오면 같은 날짜의 기존 시각을 유지한다 |
| `available_time` | `"180"`·`"360"`·`"540"` (str) | Integer | 세 값만 문자열로. 다른 값은 null |
| `category` | `["카페", …]` (list) | `List<String>` | AI 허용값(카페·팝업·전시·맛집·명소·기타)만 보낸다. 모두 걸러지면 null |

- `prev_query`: BE가 AI 응답의 `query`를 query 캐시(TTL 10분)에 저장해 다음 턴에 보낸다.
- FE로 내려가는 슬롯(`GetReplyResponse.Slot`)은 기존 형식을 유지한다. category는 첫 값 하나만 내려간다.

### 2-2. 코스 추천 `POST /v1/recommend-courses`

| 필드 | 형식 | 비고 |
| --- | --- | --- |
| `query` | str (필수) | 없으면 `""` |
| `candidates` | list | **임시 web 모드에서는 빈 목록**. 비면 AI가 웹검색 경로를 탄다 |
| `history_place_ids` | list | web 모드에서는 빈 목록 |
| `available_time` | `"180"` 등 (str) | 2-1과 같은 규칙 |
| `category` | list | 2-1과 같은 규칙 |
| `datetime` | `"yyyy-MM-dd HH:mm"` 등 | 키 이름이 `date_time`에서 `datetime`으로 바뀌었다 |
| `origin` | `{lat, lng}` | lat·lng 중 하나라도 없으면 null |
| `region` | str (선택, **신규**) | 대화·의도 카드의 지역. 웹검색 기준 |

후보 항목(`candidates[]`) 규칙:
- `place_name`, `summary`, `business_hours`는 AI 필수다. BE는 이름 없는 장소를 빼고, `summary`가 없으면 `""`, `business_hours`가 없으면 `"정보 없음"`을 보낸다.
- `lat`·`lng`는 임시로 선택값이다(4-2).

### 2-3. 계약을 바꿀 때

- BE `AiSlot`, `ExtractSlotRequest`·`ExtractSlotResponse`, `RecommendCourseRequest`와 AI `app/schemas/extract.py`, `recommend_courses.py`를 함께 바꾼다.
- 양쪽 테스트에 계약을 고정해 두었다. BE `AiSlotContractUnitTests`, `RecommendCourseRequestUnitTests`와 AI `tests/test_recommend_web.py`, `test_recommend_without_coords.py`를 같이 고친다.

## 3. BE 팀

### 3-1. 변경 사항

#### 3-1-1. 챗봇 (PR #79)

| 변경 | 동작 변화 |
| --- | --- |
| 응답 조회의 슬롯 병합을 null-safe하게 (`ChatService.mergeSlot`) | 날짜가 비어 있어도 500이 나지 않는다. 값이 있는 필드만 덮어쓴다 |
| AI 형식 변환 (`AiSlot`, 2-1) | AI 422와 역직렬화 실패가 없어졌다 |
| AI 호출 실패 처리 (`GetReplyWorker`, `GetReplyCacheService`) | 실패하면 에러 로그를 남기고 **폴링이 502**를 준다. 이전에는 끝까지 IN_PROGRESS였다 |
| AI RestClient read timeout 130초 | AI가 응답하지 않으면 워커 스레드가 풀린다. 영상 분석(120초)보다 길게 잡았다 |
| 대화 초기화 시 슬롯·query·대기 응답 삭제 | 새 대화가 이전 조건을 물려받지 않는다 |
| query 캐시 구현 (`CacheConfig`에 `query` 등록) | 정성 조건이 다음 턴과 추천에 전달된다 |
| 새 채팅마다 응답 캐시 초기화 (`putIfAbsent` → `put`) | 이전 채팅의 결과가 새 채팅으로 나가지 않는다 |

#### 3-1-2. 코스 추천 (PR #79·#80·#81)

| 변경 | 동작 변화 |
| --- | --- |
| `OutingCollectionPrivate.createdAt`을 `@PrePersist`로 기록 | 추천 NPE 해결. 기존 null 데이터는 오늘 날짜로 보낸다 |
| 슬롯은 `getSlot()`으로 읽음. `SlotCacheService.read()` 스텁 삭제 | 슬롯이 없으면 **400** ("의도 카드를 먼저 저장") |
| 후보와 취향 이력 분리 (`OutingGuideRepository` 신규) | 후보는 전체 장소 중 이름 있는 최근 50곳, 이력은 회원 저장 장소(중복 제거, 50곳) |
| 요청을 AI 형식으로 (2-2) | AI 422 해결 |
| 응답 장소를 후보의 guide id로 매핑, `OutingGuide`로 다룸 | 엉뚱한 장소 조회와 이벤트 장소 ClassCastException이 없어졌다 |
| **`RequestRecommendationResponse.from()` 구현** | 9/17 작성 이후 `return null`이라 추천 결과가 늘 빈 본문이었다. 이제 응답으로 나간다 |
| 후보 출처 설정 `keepgo.recommendation.candidate-source` | 3-2 참고 |

#### 3-1-3. 테스트

- `src/test/java/eightjbbm/keepgo/unit/`에 6개 파일, 23개 테스트를 추가했다.
  - `AiSlotContractUnitTests`
  - `ChatServiceSlotMergeUnitTests`
  - `GetReplyFailureUnitTests`
  - `RecommendHistoryPlaceUnitTests`
  - `RecommendCourseRequestUnitTests`
  - `RequestRecommendationResponseUnitTests`
- 실행: `./gradlew test --tests 'eightjbbm.keepgo.unit.*'` (JDK 25 필요)
- `ChatIntegrationTests.test3_1`의 mock이 null 대신 실제 AI 응답을 돌려주도록 고쳤다. 통합 테스트는 DB가 필요해 Cloud에서 실행하지 못했다.

### 3-2. 임시조치 (되돌릴 것)

| 위치 | 현재 임시 동작 | 되돌리는 방법 | 되돌릴 조건 |
| --- | --- | --- | --- |
| `application.yaml` `keepgo.recommendation.candidate-source` | `web`(기본): 후보·이력을 비워 보내고 대화 조건만 전달 | 환경변수 `KEEPGO_RECOMMENDATION_CANDIDATE_SOURCE=saved` 또는 yaml 기본값 변경. 코드 수정 없음 | 장소명 null 저장 중단과 데이터 정리(3-3-2), 장소 좌표 수집 |
| `RecommendationService.candidatePlaces` (`saved` 모드) | 반경 필터 없이 이름 있는 최근 50곳 | 출발지 반경 필터로 교체 | 장소 좌표 수집 |
| `RecommendHistoryPlaceId.from` | `createdAt` null이면 오늘 날짜 | null 분기 제거 | 기존 데이터 `created_at` 보정 |
| `AiSlot.filterCategories` | AI가 모르는 FE 라벨(디저트·술집·편집샵·공연·산책)을 버림 | 필터 제거 | FE·AI 카테고리 집합 통일 |
| `GetReplyResponse.Slot.category` | 첫 카테고리 하나만 FE로 | 배열로 변경 | FE가 배열을 받게 되면 |
| `RequestRecommendationResult` (BE 기존 임시조치, 10-02) | `lat`·`lng`를 `0.0`으로 하드코딩, `description`에 이동 시간 | 실제 좌표와 설명으로 | 장소 좌표 수집 |
| `OutingPlace` 좌표 필드 (BE 기존 임시조치, 10-02) | 주석 처리 | 복구 | 장소 좌표 수집 |

### 3-3. 수정 요청

| 우선순위 | 항목 | 현재 | 제안 |
| --- | --- | --- | --- |
| 높음 | 로그인 중복 콜백 | Google 화면에서 두 번 누르면 `/login?error` | 3-3-1 |
| 높음 | 장소명 null 저장 | 영상 분석 결과를 이름 없이 저장 | 3-3-2 |
| 높음 | 배포 때 전원 로그아웃 | 리프레시 토큰 해시가 Caffeine 메모리 캐시(`rtHash`) | DB 또는 외부 저장소로 이전 |
| 중간 | 추천 취소 미동작 | `createJob(memberId, 0L)`로 jobId 0. AI에 `X-Request-Id`를 보내지 않아 AI가 취소 대상을 못 찾음 | 요청 ID를 만들어 추천과 취소에 같이 보냄 |
| 중간 | 추천 중 AI 오류가 500 | 동기 추천 경로에서 RestClient 예외를 그대로 던짐 | 502와 오류 코드로 변환 |
| 중간 | 장소 상세 API 미구현 | `GET /places/{id}`, `/events/{id}`가 미구현 응답. "요즘 뜨는 곳"도 stub | 구현하거나, 추천 응답 항목에 summary·영업시간·이유를 추가 |
| 중간 | 추천 응답 항목 | sequence가 0부터. 웹 장소 category null이라 FE가 전부 "카페"로 표시 | sequence 1부터. AI 카테고리 반영(4-3) |
| 중간 | 영상 분류 반전 | `MemberService.isPlaceOrEvent`가 팝업·전시를 Place로, 나머지를 Event로 저장 | 조건 반전 수정 |
| 중간 | 의도 카드 지오코딩 분기 | `ChatService.updateSlot`의 `Optional.equals(Coordinate)`가 항상 false. 슬롯이 비었을 때만 지오코딩 | 좌표 비교 수정. 운영 `VWORLD_API_KEY` 설정 확인 |
| 낮음 | OAuth client id·secret 기본값 (`application.yaml`, 9/15 `fe71e02`) | 이미 폐기된 값. 운영은 재발급 값을 Secret으로 주입 중 | 저장소에서 기본값 삭제 |
| 낮음 | 스키마 오타 파일 | `resources/org/springframwork/.../oauth-client-schema.sql` 미사용 | 삭제. `spring.sql.init.mode: always`는 운영 DB에 테이블이 이미 있어 기동이 실패하므로 쓰지 않음 |
| 낮음 | 로그 | 한글 깨짐(System.out 인코딩), 기본 `LOGGING_LEVEL` TRACE | stdout UTF-8, 운영은 INFO |
| 낮음 | CI | `bootJar`만 실행하고 테스트는 건너뜀 | 단위 테스트 단계 추가 |

#### 3-3-1. 로그인 중복 콜백 처리

**증상.** Google 계정 선택·권한 동의 화면에서 버튼을 두 번 누르면 로그인에 실패하고 `/login?error`로 돌아온다. 다시 시도하면 대부분 성공한다.

**근거 (web 접근 로그, 10-03 01:31 KST).**

```
GET /login/oauth2/code/google?state=boac5j…  499   ← 브라우저가 응답 전에 끊음
GET /login/oauth2/code/google?state=boac5j…  302   ← 같은 state, 다른 code
GET /login?error
```

**원인.**
1. 같은 state로 콜백이 두 번 들어온다.
2. 첫 요청을 BE가 처리하면서 state를 소비하지만, 브라우저가 이미 끊어 토큰이 전달되지 않는다.
3. 두 번째 요청은 `authorization_request_not_found`로 실패한다.
4. `LoginFilterChainConfig`의 `oauth2Login`에 `failureHandler`가 없어 Spring 기본값인 `/login?error`로 간다.

**제안.**
- `OAuth2LoginFailureHandler`를 추가하고 `.failureHandler(...)`로 등록한다.
- 실패 사유가 `authorization_request_not_found`면 `/oauth2/authorization/google`로 보내 로그인을 한 번 자동으로 다시 시작한다. 이미 동의한 계정은 Google이 바로 넘겨준다.
- 세션에 재시도 시각을 기록하고, 60초 안에 다시 실패하면 `/login?error`로 보낸다(반복 방지).
- 그 밖의 실패는 지금처럼 `/login?error`로 보낸다.

#### 3-3-2. 장소명 null 저장

**현상.** 유튜브 좋아요 영상 27개 중 26개가 `placeName=null`로 분석됐다. 장소와 무관한 영상(게임, 코딩, 공연 등)이다. `MemberService`는 이를 그대로 저장하는데, `outingPlaceRepository.findByName(null)` 때문에 모두 이름 없는 장소 하나(id 353)에 묶였다.

**영향.** 이름 없는 장소가 추천 후보에 섞이면 AI가 422를 낸다. 지금은 후보에서 빼서 막고 있다(`652815a`). 저장 데이터로는 추천할 장소가 사실상 없어 web 모드로 임시 운영 중이다.

**제안.**
- 분석 결과의 장소명이 null이거나 빈 값이면 저장하지 않는다.
- 이미 저장된 이름 없는 guide와 저장 장소를 정리한다.

### 3-4. 브랜치 정리

- 이번 핫픽스는 `main`에서 바로 작업했다(#79~#81).
- `dev`의 `7e8b9ad`("좌표 정보 임시조치", datetime을 LocalDate로 보냄)는 #79가 대체한다. 이 커밋을 그대로 배포하면 날짜 없는 슬롯에서 POST 단계 NPE가 난다.
- `main`을 `dev`로 병합하고, 충돌하면 `main` 쪽을 기준으로 정리해 주면 된다.

## 4. AI 팀

### 4-1. 변경 사항

| PR | 변경 | 동작 변화 |
| --- | --- | --- |
| #39 `a503aca` | `RecommendCandidate.lat`·`lng`를 선택값으로. `course_builder`의 거리 정렬·구간·규칙 조합과 프롬프트 좌표 표기를 None-safe하게 | 좌표 없는 후보는 모델 순서를 유지하고 이동 0분. 좌표가 있으면 기존대로 |
| #40 `d53fd56` | 후보가 비면 `services/recommend_web.py`로 웹검색 추천. 프롬프트 `recommend_web_search.yaml`·`recommend_web_structure.yaml` 신규, 요청 `region` 필드 | 2-2 참고 |
| #41 `515dcf7` | 웹 경로 thinking 512, 코스 2개 × 3곳, `TIMEOUT_RECOMMEND_WEB` 90초, 취소돼도 소요 시간 로그 | 웹 경로 전체 약 15초 (검색 11~12초, 구조화 약 3초) |

웹 경로 흐름은 다음과 같다.
1. `google_search` 그라운딩으로 조건에 맞는 코스를 자유 텍스트로 작성한다.
2. `WebCoursesLLM`으로 구조화한다.
3. 기존 `course_builder.build_course`로 도착 시각, 총 소요 시간, 외출 가능 시간을 맞춘다.
4. 기존 `RecommendCoursesData` 형식으로 응답한다.

- 검색과 구조화를 나눈 이유는 verify-place와 같다. 랭체인에서 두 가지를 함께 쓰면 그라운딩이 빠진다.
- 실패하거나 시간을 넘기면 `courses=[]`를 반환한다.
- 바꾸지 않은 것: verify-place(스키마·프롬프트·서비스), 후보가 있는 기존 추천 경로, 응답 스키마
- 테스트: `tests/test_recommend_without_coords.py`, `tests/test_recommend_web.py`, 전체 19개

### 4-2. 임시조치 (되돌릴 것)

| 위치 | 현재 임시 동작 | 되돌리는 방법 | 되돌릴 조건 |
| --- | --- | --- | --- |
| `recommend_courses.recommend_courses`의 빈 후보 분기와 `recommend_web.py` | 대화 조건으로 웹검색해 코스 생성. 장소 검증 없음, 이동·체류는 모델 추정, 좌표 없음 | BE를 `saved`로 바꾸면 타지 않는다. 완전 제거는 #40·#41 revert | 정식 후보 탐색(4-3)이나 저장 데이터 기반 추천이 준비되면 |
| `RecommendCandidate.lat`·`lng` 선택값 (#39) | 좌표 없는 후보 허용 | #39 revert로 필수 복귀 | BE가 장소 좌표를 다시 보내면 |

**웹 경로 비용.**
- Gemini 3.x Google 검색 그라운딩은 실행한 검색 쿼리 단위로 과금된다. 월 5,000회 무료, 이후 1,000회당 14달러다.
- 운영 모델은 환경변수로 `gemini-3.8-flash`가 설정돼 있다(코드 기본값은 flash-lite).
- 추천 1회당 검색 횟수는 LangSmith `grounding_metadata.web_search_queries`로 확인할 수 있다.

### 4-3. 수정 요청

| 우선순위 | 항목 | 제안 |
| --- | --- | --- |
| 중간 | 정식 후보 탐색 | 장소 검증과 좌표를 포함한 탐색 기능을 설계해 4-2 웹 경로를 대체 |
| 중간 | 응답 장소 카테고리 | `CoursePlace`에 category 추가. 지금은 웹 장소의 카테고리가 FE에서 전부 "카페"로 보인다 |
| 낮음 | 취소된 LLM 호출의 트레이스 | 제한 시간으로 취소된 호출이 LangSmith에 출력 없는 미완료로 남는다. 종료 기록 처리 확인 |
| 낮음 | `course_builder.default_stay` | TODO(human) 남아 있음. 카테고리별 기본 체류 시간 |

## 5. FE 관련 참고

이번에 Cloud가 FE 코드를 바꾸지는 않았다. BE·AI 변경과 맞물려 FE에서 손볼 항목만 적는다(FE 팀 전달용).

| 항목 | 현재 | 제안 |
| --- | --- | --- ㅊ
| 추천 대기 | 약 15초 | 진행 표시. 취소 버튼은 BE 취소 연결(3-3) 뒤 동작 |
| 추천 장소 상세 | 코스 상세에서 장소를 누를 수 없음. 장소 ID가 가짜(`be-candidate-*`) | BE 장소 상세(3-3)와 함께 연결 |
| 지도 마커 | BE가 좌표를 0,0으로 보내 위치가 틀림 | 좌표 복구 전에는 지도 숨김 |
| 카테고리 | 대화에서 여러 개가 나와도 카드에 하나만 반영 | 배열 지원 (BE 3-2와 함께) |
| 라우트 변경 | `58d7cdb`가 BE 로그인 리다이렉트(`/?accessToken=`)를 받던 페이지를 지워 로그인 장애 (`79dbf79`로 되돌림) | 루트 경로를 바꿀 때 토큰 수신 코드를 함께 옮김 |

## 6. 확인 방법

- **로그:** CloudWatch `/keepgo/v1/application`. 스트림 `keepgo-v1-backend-1`, `keepgo-v1-ai-api-1`, `keepgo-v1-web-1`
  - BE `RestClient request body`: AI로 보낸 요청 원문
  - BE `AI 슬롯 추출 실패`: 챗봇 AI 호출 실패(3-1-1)
  - AI `extract prev_slot raw`, `validation_error`: 422 사유
  - AI `llm_call endpoint=recommend-courses:web:*`, `웹검색 추천 …s, 코스 N개`: 웹 경로 소요 시간
- **LangSmith:** 프로젝트 `keepgo`. 제한 시간으로 취소된 호출은 출력 없이 미완료로 보일 수 있다.
- **배포 버전:** Cloud 저장소 `deployment/production-manifest.json`
