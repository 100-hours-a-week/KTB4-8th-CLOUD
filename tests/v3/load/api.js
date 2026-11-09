// V3 일반 API 부하(WBS 19, 5-3 7.1 "이벤트 트래픽"). dev EKS에서 사용자가 실행한다(사용자 할 일 문서).
//   k6 run -e BASE_URL=https://dev3.keepgo.kr -e TOKEN=<access token> -e TARGET_RPS=200 tests/v3/load/api.js
// 목표(5-1): 평시 Peak 200 RPS, 이벤트 Peak 1,600 RPS, Burst 3,200 RPS. dev는 작은 비율로 시작해 HPA·Karpenter 반응을 본다.
// 경로는 같은 이미지라도 HTTPRoute로 서비스가 나뉘므로 서비스별로 고르게 섞는다.
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE_URL || "https://dev3.keepgo.kr";
const TOKEN = __ENV.TOKEN || "";
const TARGET = Number(__ENV.TARGET_RPS || 200);

export const options = {
  scenarios: {
    ramp: {
      executor: "ramping-arrival-rate",
      startRate: Math.max(1, Math.floor(TARGET / 10)),
      timeUnit: "1s",
      preAllocatedVUs: 50,
      maxVUs: 500,
      stages: [
        { target: TARGET, duration: "3m" },   // 확장 반응(HPA 60초 안정화 + 노드 생성)
        { target: TARGET, duration: "10m" },  // 유지
        { target: 0, duration: "2m" },        // 축소(5분 안정화 후 1개씩)
      ],
    },
  },
  thresholds: {
    // 5-3 7.2 지표. SLO 미정이라 알림 기준(5xx 5%, p95 1초)을 그대로 쓴다.
    http_req_failed: ["rate<0.05"],
    "http_req_duration{kind:api}": ["p(95)<1000"],
  },
};

const headers = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
const paths = [
  "/api/v1/user",                              // member-api
  "/api/v1/places",                            // recommend-api
  "/api/v2/member/outing-wishlist/places",     // wishlist-api
  "/api/v2/member/external-connections",       // youtube-api
];

export default function () {
  const p = paths[Math.floor(Math.random() * paths.length)];
  const res = http.get(`${BASE}${p}`, { headers, tags: { kind: "api", path: p } });
  check(res, { "5xx 아님": (r) => r.status < 500 });
}
