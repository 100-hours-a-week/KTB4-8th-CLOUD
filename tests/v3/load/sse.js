// V3 SSE 동시 연결 부하(WBS 19, 5-3 5.5·7.1 "SSE Pod Scale-in"). dev EKS에서 사용자가 실행한다.
//   k6 run -e BASE_URL=https://dev3.keepgo.kr -e TOKEN=<access token> -e CONNECTIONS=400 tests/v3/load/sse.js
// k6 기본 http는 응답이 끝날 때까지 기다리므로, 연결 하나 = VU 하나가 스트림 끝(최대 180초)까지 붙잡는다.
// 확인할 것: keepgo_sse_active_connections 증가 → KEDA로 chat/recommend 확장, Scale-in·배포 때 재연결 성공률.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE_URL || "https://dev3.keepgo.kr";
const TOKEN = __ENV.TOKEN || "";
const CONNECTIONS = Number(__ENV.CONNECTIONS || 400);

export const options = {
  scenarios: {
    hold: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { target: CONNECTIONS, duration: "3m" },
        { target: CONNECTIONS, duration: "10m" },
        { target: 0, duration: "1m" },
      ],
    },
  },
  thresholds: {
    // 연결이 ALB idle timeout·Pod 종료로 끊겨도 재연결이 대부분 성공해야 한다
    checks: ["rate>0.95"],
  },
};

export default function () {
  const res = http.post(
    `${BASE}/api/v2/member/chat-messages`,
    JSON.stringify({ message: "성수동 주말 데이트 코스 추천해줘" }),
    {
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      },
      timeout: "200s", // 서버 SSE 타임아웃 180초보다 길게
      tags: { kind: "sse" },
    },
  );
  check(res, { "SSE 정상 종료(2xx)": (r) => r.status >= 200 && r.status < 300 });
  sleep(1);
}
