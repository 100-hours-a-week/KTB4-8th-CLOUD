# 2026-11-04 Grafana 고정 IP가 반납돼 grafana.keepgo.kr 접속 불가

## 🐞 에러 내용

`https://grafana.keepgo.kr`이 열리지 않았다. 브라우저는 응답 없이 시간 초과로 끝났다.

```
curl: (28) Connection timed out after 15001 milliseconds
```

- DNS는 `3.34.14.66`을 돌려줬다. 그런데 모니터링 EC2(`i-0e2b9ff8599ff8023`)의 공인 IP는 `3.39.187.112`였다.
- 수집·경보는 정상이었다. Prometheus·Grafana·Caddy 컨테이너도 떠 있었다. 바깥에서 들어오는 길만 끊겼다.
- 기간: 11-04 15:25 ~ 17:20쯤(KST), 약 2시간.

## 🔍 원인 분석

- **고정 IP가 반납됐다.** CloudTrail을 보니 15:25에 IAM 사용자 `dice_terraform`이 aws-cli(macOS)로 Elastic IP 3개를 연결 해제(`DisassociateAddress`)하고 반납(`ReleaseAddress`)했다. 그중 `eipalloc-0f96396d1f9c3e131`이 Grafana용 `3.34.14.66`("for grafana")이었다. 10-01 할당·연결 기록으로 확인했다.
  - 같은 시각에 반납된 `3.34.10.134`는 곧바로 `dev3-nat-eip-a`로 다시 할당돼 새 NAT에 쓰였다. 다른 환경(dev3)의 IP를 정리하다가 Grafana IP까지 같이 반납한 것으로 보인다.
- **소유자 표시가 없었다.** 이 IP는 [TD-025](../technical-decisions.md)에서 일부러 스택 밖 자원으로 콘솔에서 만들었다. Terraform·CloudFormation 어디에도 없고, 태그도 `Name` 하나뿐이었다. 그래서 다른 사람이 보기에 "주인 없는 IP"였다.
- **EIP가 빠지면 공인 IP가 바뀐다.** EIP가 떨어지면 EC2는 자동 공인 IP를 새로 받는다. DNS는 옛 IP를 그대로 가리키므로 접속이 끊긴다.
- **같은 IP는 되찾지 못했다.** 반납한 EIP는 다른 계정이 가져가기 전이면 `allocate-address --address`로 되찾을 수 있다. 이번에는 `InvalidAddress.NotFound`로 실패했다. 이미 다른 곳에 넘어간 것이다.

## ✅ 해결 방법

1. 새 EIP `15.164.83.230`(`eipalloc-045167d2e768f4ee5`)을 할당했다. 태그는 `Name=for grafana`, `Keep=grafana-dns`를 붙였다. 그다음 모니터링 EC2에 연결했다.
2. 가비아 DNS에서 `grafana` A 레코드를 `15.164.83.230`으로 바꿨다(TTL 300).
3. `nslookup grafana.keepgo.kr 8.8.8.8` 결과 새 IP가 나왔다. `https://grafana.keepgo.kr/api/health`는 `200`을 줬고 인증서 검증도 정상이었다. 인증서는 Caddy 데이터 볼륨에 있어 재발급이나 재시작이 필요 없었다.
4. 문서와 템플릿 주석의 IP를 새 값으로 고쳤다.

## 회고

- 콘솔에서 만든 자원은 다른 사람 눈에 주인 없는 자원이다. IaC 밖에 두기로 했으면 **누가 왜 쓰는지 태그로 남긴다.** 이번에 `Keep=grafana-dns`를 붙였다.
- 공용 계정에서 EIP·NAT 같은 자원을 정리할 때는 연결된 대상(`InstanceId`·`NetworkInterfaceId`)과 태그를 먼저 확인하고, 팀 채널에 알린 뒤 반납한다.
- 바깥 접속 장애는 앱 경보로 잡히지 않는다. Grafana가 멀쩡해도 길이 끊기면 아무도 모른다. 사용자가 접속해 보고서야 알았다([구성](../v1-monitoring.md) 7절의 "Grafana 단독 장애는 자동 통보 못 함"과 같은 한계).
