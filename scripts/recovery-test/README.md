# V2 BE 복구 시험 도구

BE task가 교체되거나 죽을 때 사용자 요청이 얼마나 실패하는지, 어떤 경보가 반응하는지 기록한다. 스크립트는 조회만 한다. 재배포·task 중지는 사람이 별도 명령으로 실행한다.

| 파일 | 역할 |
|---|---|
| `probe.py` | 1초마다 CloudFront 경유 요청. Spring 401 JSON이면 성공 |
| `recorder.py` | 약 6초마다 배포·task·ALB 대상 상태 기록 |
| `collect.py` | 시험 후 ECS 이벤트, CloudWatch 경보 이력, ALB 지표, Prometheus `up`·`ALERTS` 수집(SSM 읽기 curl) |
| `summarize.py` | 위 기록을 `summary.md` 시간축으로 정리 |

원본 기록은 `.artifacts/recovery-test/<run>/`에 저장되며 git에 올라가지 않는다(내부 IP·task ID 포함).

## 실행 순서 (로컬 PowerShell, 터미널 2개)

```
cd scripts/recovery-test
python probe.py 20261022-a      # 터미널 1
python recorder.py 20261022-a   # 터미널 2
```

1. 둘 다 2분 이상 정상으로 기록되는지 본다.
2. 조작한다. 시험 A는 `aws ecs update-service --cluster keepgo-v2 --service keepgo-v2-backend --force-new-deployment`, 시험 B는 `aws ecs stop-task --cluster keepgo-v2 --task <BE task ID> --reason recovery-test`.
3. 배포가 COMPLETED되고 대상이 healthy가 된 뒤 3분 더 기록하고 Ctrl+C로 끝낸다.
4. 10분 뒤 `python collect.py 20261022-a`와 `python summarize.py 20261022-a`를 실행한다. 10분을 기다리는 이유는 경보 평가가 끝나야 해서다.
5. Discord 개발 알림 채널의 수신 여부와 시각을 `summary.md`에 직접 적는다.

15분 안에 복구되지 않거나 롤백이 일어나면 시험을 멈추고 ECS 서비스 이벤트를 확인한다.
