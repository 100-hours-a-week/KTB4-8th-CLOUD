# 2026-10-01 Backend 무응답 — `docker attach`가 보낸 SIGHUP과 막힌 stdout

> 시각은 모두 KST다. 로그·Docker 기록은 UTC(`Z`)라 9시간을 더해 읽는다.

## 요약

- **영향:** 23:02:44부터 23:58까지 약 55분 동안 Backend가 요청에 응답하지 않았다. 컨테이너와 JVM은 살아 있었다(`Up (unhealthy)`, CPU 0%).
- **직접 원인:** 22:35에 BE 팀원이 로그를 보려고 SSM 세션에서 `sudo docker attach keepgo-v1-backend-1`을 실행했다. 이 attach가 두 가지 문제를 차례로 일으켰다.
  1. **22:53 무렵** attach 클라이언트가 출력을 읽지 않게 됐고, 약 10분 뒤인 **23:02:44** attach 버퍼가 가득 찼다. Docker가 attach를 기다리느라 **컨테이너 stdout이 막혔고**, 로그를 쓰던 스레드가 멈춰 응답이 끊겼다. ← 장애 시작
  2. **23:14:08** SSM 세션이 끝나면서 SIGHUP이 attach를 거쳐 **Backend JVM에 전달**됐다. JVM이 종료를 시도했지만 종료 로그를 쓰다 같은 곳에서 멈췄다.

  결국 요청도 처리하지 못하고 프로세스도 끝나지 않는 상태로 굳었다. attach를 끊자 출력이 풀리면서 미뤄진 종료가 실행됐다(exit 129).
- **키운 요인:** BE `374cfd4`의 root 로그 레벨이 TRACE(기본값)라 로그 양이 매우 많았다. 그래서 버퍼가 빨리 찼다.
- **복구:** attach 클라이언트를 `kill -9` → JVM이 남은 종료 절차를 마치고 exit 129로 종료 → `docker start`로 복구.
- **재발 방지:** 운영 컨테이너 `docker attach` 금지, `LOGGING_LEVEL_ROOT=INFO`, 헬스체크 `timeout` 래핑.

## 🐞 에러 내용

Grafana 알림 `KeepGo internal service unhealthy`가 발생했다(대상 `http://backend:8080/actuator/health`, 3분 이상 실패).

| 확인 항목 | 결과 |
| --- | --- |
| `docker ps` | `keepgo-v1-backend-1` `Up`, `unhealthy` |
| Docker health | `FailingStreak: 53`, `Health check exceeded timeout (3s)` |
| 직접 연결 | 8081 `Connection refused`(이미지에 관리 포트 없음), 8080은 **연결은 되지만 응답 없음** |
| Blackbox | `context deadline exceeded`, `probe_duration_seconds ≈ 5.0`, DNS 정상 |
| `docker stats` | CPU 0.10%, 메모리 353.7 MiB / 1 GiB, PIDS 149 |
| 앱 로그 | 23:15 이후 ERROR·WARN·Exception·Hikari가 하나도 없음 |
| 컨테이너 안 | 헬스체크의 `bash`와 `grep`이 15초마다 하나씩 생기고 사라지지 않음 |
| `kill -QUIT 7` | 성공했지만 `docker logs`에 스레드 덤프가 나오지 않음 |

## 시간순 정리

| 시각 (KST) | 내용 | 근거 |
| --- | --- | --- |
| 22:10 | BE `374cfd4` 배포(release #49). root 로그 레벨이 TRACE로 바뀐 커밋 포함 | CLOUD `origin/main` Manifest 이력 |
| 22:12:21 | backend 컨테이너 시작 | `State.StartedAt` |
| **22:35:50** | BE 팀원이 SSM 세션에서 `sudo docker attach keepgo-v1-backend-1` 실행 | 호스트 `ps`의 `lstart`, dockerd 고루틴의 attach 대기 75분 |
| **22:53 무렵** | attach 클라이언트가 출력을 읽지 않음. dockerd → 클라이언트 소켓 쓰기가 막힘 | dockerd 고루틴 `stdWriter.Write → net.(*conn).Write` IO wait 57분 |
| **23:02:44** | **stdout 막힘.** Docker 헬스체크의 `/actuator/health` 요청을 처리하던 로그가 정상 전달된 마지막 로그. 이후 응답 없음 | `be-all.txt`: 이 줄 다음부터 Docker 수신 시각이 23:55:36으로 몰림 |
| **23:14:08** | SIGHUP 수신 → `Runtime.exit() called with status: 129` 로그를 쓴 뒤 다음 로그에서 멈춤 | `be-all.txt`의 `[SIGHUP handler]` 앱 시각, 스레드 덤프의 `elapsed=2487.85s` |
| 23:18 무렵 | 헬스체크 timeout 연속을 사람이 확인, Grafana 알림 | Docker health(`FailingStreak: 53`) |
| 23:27 | Blackbox 5초 timeout 확인 | Blackbox probe |
| 23:47 | jhsdb로 스레드 덤프 확보 | `/tmp/td-sa.txt` |
| 23:50 | dockerd 고루틴 덤프 확보 | `goroutine-stacks-2026-10-01T145015Z.log` |
| 23:55:37 | attach 클라이언트 `kill -9` → JVM이 종료 절차를 마치고 exit 129 | `State.FinishedAt` |
| 23:58 | `docker start` → `Up (healthy)` | `docker ps` |

## 🔍 원인 분석

### 1. 로그가 흘러가는 경로

```
Java(logback ConsoleAppender)
   │ write(1, …)                        ← 쓰는 동안 logback 락을 쥔다
   ▼
[stdout 파이프]  커널 버퍼 64KB
   ▼
containerd-shim → dockerd
   ▼
dockerd: 한 덩어리를 읽으면 "모든 구독자"에게 차례로 넘긴 뒤 다음을 읽는다
   ├─① 로그 드라이버 (awslogs, non-blocking → 밀리면 버림)
   └─② attach 클라이언트 (docker attach → 터미널 → 사람)
```

dockerd는 한 덩어리를 ①과 ② **모두에게 넘겨야** 다음 덩어리를 읽는다. ② 쪽 버퍼(약 1MB)가 가득 차면 dockerd는 거기서 기다린다. 그러면 ①에도 넘기지 못하고, 파이프에서 더 읽지도 않는다.

### 2. 실제로 일어난 일

1. 22:35에 attach가 붙었다. 이때부터 Backend 출력이 ②로도 흘렀다.
2. 22:53 무렵 attach 클라이언트가 출력을 읽지 않게 됐다. 브라우저 연결 끊김(노트북 절전, 네트워크)으로 SSM이 터미널 출력을 더 보내지 못한 것으로 추정한다. 이후 약 10분 동안 TRACE 로그가 ② 버퍼(약 1MB)를 채웠고, 23:02:44에 1절의 경로대로 stdout 파이프까지 가득 찼다.
3. 그 순간 로그를 쓰던 **Tomcat Poller**(모든 HTTP 요청을 받아 넘기는 스레드)가 `write()`에서 멈췄다. 다른 스레드는 logback 락을 기다리며 멈췄다. TCP 연결은 받지만 HTTP 응답은 나가지 않게 됐다.
4. 23:14:08 SSM 세션이 끝났다. 터미널이 끊기면 그 터미널의 프로세스에 SIGHUP이 간다. sudo가 이를 `docker attach`로 넘겼고, **`docker attach`는 받은 시그널을 컨테이너로 그대로 전달한다**(기본값 `--sig-proxy=true`).
5. JVM이 SIGHUP을 받고 `SIGHUP handler` 스레드에서 종료를 시작했다. `Runtime.exit() called with status: 129` 한 줄을 남긴 뒤, 다음 로그를 쓰려다 같은 logback 락에서 멈췄다. 이 로그도 막힌 출력 뒤에 쌓였을 뿐 밖으로 나가지 못했다.
6. 결과적으로 응답도 못 하고 종료도 못 하는 상태가 됐다. SIGHUP은 장애의 시작이 아니라, attach를 끊었을 때 컨테이너가 재시작이 아니라 **종료**된 이유다.

### 3. 증거

**JVM 스레드 상태 (`ps -L -o stat,wchan,comm`)**

```
1 Sl   anon_pipe_write   http-nio-8080-P    ← Poller: stdout 쓰기에서 멈춤
1 Sl   anon_pipe_write   VM Thread          ← kill -QUIT의 스레드 덤프 출력에서 멈춤
1 Sl   futex_do_wait     SIGHUP handler     ← SIGHUP을 받았다는 표시
… 나머지 전부 futex_do_wait
```

**jhsdb 스레드 덤프** (`jcmd`는 VM Thread가 멈춰 동작하지 않았다. ptrace로 붙는 `jhsdb jstack`만 성공했다)

```
"http-nio-8080-Poller"  RUNNABLE / _thread_in_native
 - java.io.FileOutputStream.writeBytes
 - java.io.BufferedOutputStream.write   - locked (BufferedOutputStream)
 - java.io.PrintStream.write             - locked (PrintStream)
 - ch.qos.logback.core.joran.spi.ConsoleTarget$1.write
 - ch.qos.logback.core.OutputStreamAppender.writeByteArrayToOutputStreamWithPossibleFlush

"SIGHUP handler"  WAITING (parking)
 - parking to wait for (ReentrantLock$NonfairSync)
 - ch.qos.logback.core.OutputStreamAppender.writeBytes      ← 종료 로그를 쓰려다 대기
```

`Deadlock Detection: No deadlocks found.` DB나 Hikari 대기는 없었다.

**dockerd 고루틴 덤프 (`kill -USR1 $(pidof dockerd)`)**

```
goroutine 854138 [chan receive, 75 minutes]:
daemon.(*Daemon).containerAttach(...)
daemon.(*Daemon).ContainerAttach(..., {0xc00187b337, 0x13}, ...)   ← 이름 길이 19 = keepgo-v1-backend-1
```

dockerd가 실제로 막힌 두 고루틴(덤프 시각 14:50:15 UTC 기준):

```
goroutine 854159 [IO wait, 57 minutes]:                ← 13:53 UTC(22:53 KST)부터: 클라이언트로 쓰기 대기
net.(*conn).Write(...)
daemon/internal/stdcopymux.(*stdWriter).Write(...)
io.CopyBuffer({…}, {…, 0xc009c36820}, …)               ← attach용 버퍼에서 읽어 클라이언트로 보냄

goroutine 846842 [sync.Cond.Wait, 47 minutes]:         ← 14:03 UTC(23:03 KST)부터: 버퍼가 가득 참
daemon/internal/stream/bytespipe.(*BytesPipe).Write(0xc009c36820, …)   ← 위와 같은 attach용 버퍼
daemon/internal/stream.(*unbuffered).Write(...)        ← 컨테이너 stdout을 구독자들에게 나눠 쓰는 단계
```

로그 드라이버 copier 고루틴들은 모두 `BytesPipe.Read`에서 비어 있는 입력을 기다리고 있었다. 1절에서 설명한 대로, 나눠 쓰는 단계가 attach에서 멈춰 로그 드라이버 쪽에는 아무것도 오지 않은 것이다.

**TRACE 로그 양 (`be-all.txt`, 앱 시각 기준 분당 바이트, Docker 시각 접두어 포함)**

```
13:40 180225   13:44 102011   13:48 102470   13:52 102251   13:56 101570   14:00 114697
13:41 119156   13:45 115182   13:49 101346   13:53 101999   13:57 102258
13:42 1119260  13:46 102253   13:50 117842   13:54 310948   13:58 102024
13:43 101300   13:47 101090   13:51 101081   13:55 115094   13:59 104975
```

평소 **분당 약 100KB**(초당 약 1.7KB)가 나왔다. attach 클라이언트가 읽기를 멈춘 13:53부터 14:00까지만 합쳐도 약 1.05MB다. attach용 버퍼(약 1MB)와 소켓·터미널 버퍼가 10분 안에 찬 것과 맞는다. INFO 레벨이었다면 같은 양이 쌓이는 데 며칠이 걸렸을 것이다(단, 23:14의 SIGHUP은 로그 양과 관계없이 전달된다).

**호스트 프로세스**

```
1054692 Thu Oct  1 13:35:50 2026 ?      S    sudo docker attach keepgo-v1-backend-1
1054694 Thu Oct  1 13:35:50 2026 pts/4  Ss   sudo docker attach keepgo-v1-backend-1
1054695 Thu Oct  1 13:35:50 2026 pts/4  Sl+  docker attach keepgo-v1-backend-1
```

**앱 로그 타임스탬프 (`docker logs -t`: 첫 칸은 Docker가 받은 시각, 둘째 칸은 앱이 로그를 만든 시각)**

```
2026-10-01T14:02:44.781609316Z ]                                         ← 정상 전달된 마지막 로그
2026-10-01T14:55:36.067218881Z 2026-10-01T14:02:44.781Z DEBUG … [nio-8080-exec-1] … Parameters : Set query string encoding to UTF-8
2026-10-01T14:55:36.067227015Z 2026-10-01T14:02:44.781Z DEBUG … RemoteIpValve : Incoming request /actuator/health … [127.0.0.1]
                                                                         ← 이후 로그는 모두 14:55:36(attach 종료 후)에 전달됨
2026-10-01T14:55:36.087442338Z 2026-10-01T14:14:08.227Z DEBUG … [ SIGHUP handler] java.lang.Runtime : Runtime.exit() called with status: 129
```

막혀 있던 `kill -QUIT`의 스레드 덤프(`Full thread dump` 1건)도 14:55:36에 함께 나왔다. 덤프 속 `"SIGHUP handler" … elapsed=2487.85s`를 계산하면 14:14:08 + 41분 27.85초 = 14:55:36이다. VM Thread가 막혀 있다가 풀린 순간에 나머지 덤프를 출력했다는 뜻이고, SIGHUP 수신 시각과도 맞는다.

**복구 후 종료 상태**

```
keepgo-v1-backend-1 Exited (129)        ← 128 + 1(SIGHUP)
exited exit=129 fin=2026-10-01T14:55:37Z oom=false
```

attach를 끊자 stdout이 풀렸고, 멈춰 있던 종료 절차가 끝나 JVM이 SIGHUP 종료 코드로 끝났다. 위 원인 설명과 맞는 결과다.

### 4. 헷갈렸던 점

| 의문 | 답 |
| --- | --- |
| awslogs가 `mode: non-blocking`인데 왜 막혔나 | non-blocking은 ① 로그 드라이버가 느릴 때만 로그를 버려서 보호한다. 이번에 막힌 곳은 ②(attach)다. dockerd 고루틴 덤프에서 직접 확인했다. 다른 컨테이너(ai-api·frontend·web)의 `docker logs`는 정상이었다. |
| 왜 CPU가 0%이고 로그가 한 줄도 없었나 | 로그를 쓰려는 모든 스레드가 같은 stdout을 기다리고 있었다. Hikari도 같은 이유로 로그가 없었다. DB와는 관계없다. |
| 왜 `kill -QUIT`의 스레드 덤프가 안 나왔나 | 덤프도 stdout으로 출력된다. VM Thread가 덤프를 쓰다 멈췄고, 이후 safepoint가 필요한 `jcmd`도 동작하지 않았다. |
| 헬스체크 프로세스가 원인이었나 | 아니다. 결과다. 아래 5절 참고. |
| 왜 `restart: unless-stopped`가 다시 띄우지 않았나 | **추정:** attach의 시그널 전달은 `docker kill`과 같은 API를 쓴다. 그래서 Docker가 이를 수동 중지로 기록한 것으로 보인다. dockerd 로그 14:55 UTC 부근의 `hasBeenManuallyStopped`로 확인할 수 있다. |
| attach는 22:35인데 왜 장애는 23:02부터인가 | attach만으로는 문제가 없다. **attach 쪽이 출력을 받아가지 않게 된 시점**(23:02 무렵)부터 문제가 된다. 세션 종료(SIGHUP)는 그보다 11분 뒤인 23:14였다. 브라우저 연결이 먼저 끊기고 SSM 세션이 나중에 종료된 것으로 추정하며, SSM 세션 이력으로 확인할 수 있다(아래 명령). |
| 처음에 알림·확인 시각이 23:18이었는데 | 사람이 상태를 확인한 시각이다. 앱 로그 기준 응답이 멈춘 시각은 23:02:44다. Prometheus `probe_success`의 0 전환 시각으로도 확인할 수 있다. |

SSM 세션 종료 시각 확인(CloudShell):

```sh
aws ssm describe-sessions --state History --max-results 20 \
  --query 'Sessions[].[SessionId,Owner,StartDate,EndDate]' --output table
```

### 5. 헬스체크 프로세스가 쌓인 이유 (2차 증상)

기존 헬스체크는 `( exec 3<>/dev/tcp/… && printf … >&3 && grep -q … <&3 )`였다.

- 정상일 때는 `HTTP/1.0` 요청에 서버가 응답 후 연결을 닫으므로 `grep`이 EOF를 받고 끝난다.
- 이번에는 서버가 연결만 받고 응답하지 않았다. `grep`이 timeout 없이 `read()`에서 계속 기다렸다.
- Docker는 3초 시간 초과 때 하위 프로세스를 정리하지 않는다. 서브셸과 `grep`이 컨테이너의 PID 1(docker-init)로 옮겨진 채 남았다.

WSL에서 재현했다. 응답하지 않는 서버를 상대로 기존 스크립트를 3번 실행하고 3초 뒤 바깥 bash를 `kill -9`하면 `grep`이 3개 남는다. 수정 후 스크립트는 같은 조건에서 2초 만에 실패(`rc=1`)하고 남는 프로세스가 0개다.

### 6. 조사 중 시행착오

- **`kill -QUIT`이 상황을 더 굳혔다.** 덤프를 쓰던 VM Thread까지 stdout에서 멈춰 JVM 전체가 safepoint에 묶였다. stdout 경로가 의심될 때는 SIGQUIT보다 `jhsdb jstack`(ptrace)을 먼저 쓴다.
- **런타임 이미지가 JRE라 `jcmd`·`jstack`이 없다.** 같은 버전 JDK 이미지를 `--pid=container:<이름>`으로 붙여 실행했다. 사이드카 출력은 `--log-driver json-file`로 awslogs를 피했다.
- **"awslogs blocking 모드" 가설은 틀렸다.** `HostConfig.LogConfig`가 non-blocking이었다. 막힌 지점을 dockerd 고루틴 덤프로 확인한 뒤에야 attach를 찾았다.
- **`SIGHUP handler` 스레드를 처음 목록에서 놓쳤다.** 이 이름은 JVM이 SIGHUP을 받았을 때만 생긴다. attach를 끊으면 JVM이 종료될 것을 미리 알 수 있었다.
- **SSM 셸에서 여러 줄 명령이 사라졌다.** `sudo` 줄 뒤에 붙여 넣은 줄을 sudo가 입력으로 가져갔다. 먼저 `sudo -i`로 root 셸에 들어간 뒤 실행했다.

## ✅ 해결 방법

### 복구 (2026-10-01 23:55~23:58)

```sh
sudo -i
kill -9 1054695                      # docker attach 클라이언트. 반드시 -9
docker start keepgo-v1-backend-1     # exit 129로 멈춰 있었음
docker ps --filter name=backend --format '{{.Status}}'   # Up … (healthy)
```

`kill`(SIGTERM)이나 Ctrl+C를 쓰면 `docker attach`가 그 시그널을 컨테이너로 전달해 Java가 종료된다. sudo 프로세스에 보내도 sudo가 docker attach로 넘긴다.

### 재발 방지 (Cloud 저장소)

| 변경 | 위치 | 효과 |
| --- | --- | --- |
| `LOGGING_LEVEL_ROOT: INFO` | `compose.yaml` backend `environment` | BE `application.yaml`의 `root: ${LOGGING_LEVEL:TRACE}`를 덮어쓴다. Spring 표준 키라 BE가 변수 이름을 바꿔도 적용된다. |
| 헬스체크 시도마다 `timeout -k 1 2 bash -c '…' $port`, docker `timeout: 5s` | `compose.yaml` backend `healthcheck` | 앱이 응답하지 않아도 프로세스가 쌓이지 않는다. GNU `timeout`은 자기 프로세스 그룹(bash·grep)을 모두 종료한다. 8081 → 8080 순서는 그대로 둔다. |
| 운영 컨테이너 `docker attach` 금지, 로그는 `docker logs -f` | [운영 절차](../v1-operations.md) 5절 | `docker logs`는 로컬 캐시를 읽으므로 컨테이너 출력을 막지 않고 시그널도 전달하지 않는다. |

두 compose 변경은 backend 설정을 바꾸므로, 처음 배포될 때 이미지가 같아도 **backend가 한 번 재생성된다.**

### BE 팀에 요청

- [ ] `application.yaml`의 `logging.level.root` 기본값을 `INFO`로 바꾼다. 디버깅용 TRACE는 패키지 단위로 짧게만 켠다. TRACE는 SQL 바인딩 값·요청 헤더(토큰)를 CloudWatch로 보낼 수 있다.
- [ ] `application.yaml`에 Google OAuth client secret이 실제 값으로 들어 있다. 키를 교체(rotation)하고 기본값을 지운다.
- [ ] 관리 포트를 쓰려면 `management.server.port: 8081`을, Prometheus 지표를 받으려면 `micrometer-registry-prometheus`를 추가한다([체크리스트](../v1-remaining-checklist.md) 7절).

### 증거 보관 위치

앱 EC2의 `/opt/keepgo/state/incident-20261001/`(SSM → `sudo -i` → `ls -l /opt/keepgo/state/incident-20261001`)에 둔다.

| 파일 | 내용 |
| --- | --- |
| `td-sa.txt` | jhsdb Java 스레드 덤프 |
| `dds.log` | dockerd 고루틴 덤프 |
| `hc.json` | 장애 중 Docker health 기록 |
| `dockerd.txt` | dockerd journal (13:00 UTC 이후) |
| `be-all.txt` | 장애 컨테이너의 전체 `docker logs` (TRACE) |

- `be-all.txt`는 TRACE 로그라 토큰·개인정보가 섞여 있을 수 있다. **원문을 공유하지 말고**, 회고가 끝나면 지운다.
- EC2 디스크에만 있으므로 인스턴스를 교체하면 사라진다.
- CloudWatch `/keepgo/v1/application`의 `keepgo-v1-backend-1` 스트림도 14일 보관이지만, 막혀 있던 동안의 로그는 빠져 있다.

### 남은 할 일 (TODO)

- [x] **main PR 병합:** #52(`fix/backend-log-level-healthcheck`, 코드만, prep `4a20e13`과 같은 내용). 2026-10-02 00:35 KST 병합. `compose.yaml` 변경이라 Deploy production이 자동 실행되고 backend가 한 번 재생성된다.
- [ ] **배포 결과 확인:** 다음 두 가지를 확인한다.
  - `docker inspect -f '{{json .Config.Healthcheck}}' keepgo-v1-backend-1`에 `timeout -k 1 2`가 있는지
  - `docker logs --since 5m keepgo-v1-backend-1 | wc -c`로 로그 양이 크게 줄었는지
- [ ] **증거 파일을 PC로 받기:** 위 4개 파일(`be-all.txt` 제외). PC의 AWS CLI로 앱 EC2 포트 포워딩을 시도하면 403이 났다. 먼저 `--region ap-northeast-2`를 넣어 다시 시도하고, 안 되면 CloudShell에서 터널을 연 뒤 Actions → Download file로 받는다. 받은 뒤 EC2의 `be-all.txt`와 `/tmp` 사본을 지운다.
- [ ] **BE 팀 공유:** 운영 컨테이너 `docker attach` 금지(로그는 `docker logs -f`), 로그 레벨 기본값 TRACE → INFO, Google OAuth secret 교체. 위 「BE 팀에 요청」 참고.
- [ ] **PC AWS CLI 권한 확인:** PC CLI 사용자가 앱 EC2에 `ssm:StartSession`을 할 수 있는지 확인한다(`aws sts get-caller-identity`로 사용자 확인).
- [ ] (선택) **SSM 세션 경위:** 앱 EC2의 `/var/log/amazon/ssm/amazon-ssm-agent.log`에서 13:35~14:15 UTC 기록을 보거나, CloudShell에서 `aws ssm describe-sessions --state History`를 실행한다. 22:53 출력 중단과 23:14 세션 종료의 원인을 확인한다.
- [ ] (선택) **재시작 정책 미동작 이유:** `journalctl -u docker -S '2026-10-01 14:54' -U '2026-10-01 15:00'`(root)에서 backend의 `hasBeenManuallyStopped`나 `restart canceled`를 확인한다. 확인되면 4절 표의 "추정"을 지운다.

## 회고

- **`docker attach`는 "로그 보기" 명령이 아니다.** 컨테이너의 stdin·stdout·시그널에 직접 연결된다. 세션이 끊기면 SIGHUP이 앱으로 가고, 읽지 않는 클라이언트는 앱의 출력을 막는다. 같은 목적이면 `docker logs -f`를 쓴다. 부득이하게 attach해야 하면 `--sig-proxy=false --no-stdin`으로 붙고 `Ctrl+P Ctrl+Q`로 분리한다.
- **로그 레벨은 장애 범위를 바꾸지만 막지는 못한다.** TRACE가 아니었다면 버퍼가 차는 데 훨씬 오래 걸렸을 것이다. 하지만 INFO였어도 23:14의 SIGHUP은 그대로 전달된다. 그러면 JVM은 막힘 없이 바로 종료(exit 129)하고, 재시작 정책이 다시 띄우지 않으면 `Exited` 상태로 서비스가 멈춘다. **핵심 대책은 attach 금지**이고 로그 레벨 고정은 보조 대책이다.
- **"살아 있는데 응답이 없다"면 스레드가 어디서 멈췄는지부터 본다.** `ps -L -o wchan`은 JDK 없이 바로 쓸 수 있고, 이번에는 `anon_pipe_write` 하나로 방향이 정해졌다. 이어서 dockerd 고루틴 덤프로 반대편(누가 읽지 않는가)을 확인했다.
- **진단 명령도 상태를 바꾼다.** `kill -QUIT`은 VM Thread를 묶었고, attach 종료는 미뤄져 있던 JVM 종료를 실행시켰다. 되돌리기 어려운 조작 전에는 스레드 목록에서 예상 결과(이번에는 `SIGHUP handler`)를 먼저 확인한다.
- **헬스체크도 실패 모드를 견뎌야 한다.** 기존 검사는 정상일 때만 잘 동작했고, 장애 중에는 프로세스를 계속 쌓았다. 외부 도구 없이 쓰는 검사에는 시간 제한을 직접 넣는다.
