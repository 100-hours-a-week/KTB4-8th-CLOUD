# Backend 중앙 CD 트러블슈팅

코드 기준의 점검 절차이며 실제 장애 발생 이력은 아니다. [운영 절차](v1-operations.md)와 [기술 결정 기록](technical-decisions.md)을 함께 본다.

| 증상 | 확인 및 조치 |
| --- | --- |
| 후보/배포 job이 skipped | CD_SETUP_READY·CD_ENABLED, main 이벤트를 확인한다. 초기 pin·adopt 전에는 보류가 정상이다. |
| digest 또는 CI run_id 누락 | 초기 JSON의 null은 배포 불가다. pin-manifest.py로 실제 ECR·Backend main CI를 조회하고 검토·반영한다. |
| 후보 출처 거부 | CI가 dev인지, workflow 경로와 필수 job 이름이 맞는지, 실패·skip·낡은 SHA인지 확인한다. |
| ECR digest 불일치 | SHA 태그가 PR에 기록된 digest와 달라졌다. 태그 변경/잘못된 registry를 조사하고 검증 없이 덮어쓰지 않는다. |
| Only Backend 오류 | Frontend·Nginx·AI 또는 공유 설정 변경이 섞였다. 이 단계에서는 Backend만 자동 교체한다. |
| 최초 배포 거부 | 기존 스택 adopt가 먼저다. current.json을 임의 생성하지 않는다. |
| adopt config hash 불일치 | 실제 Compose·런타임 파일·이미지 SHA·Compose 버전을 확인한다. 검사를 우회하지 않는다. |
| Runtime files changed | 채택 이후 env/JWT 내용이 달라졌다. Secret 변경과 기존 실행 컨테이너의 차이를 별도 점검한다. |
| Git fetch/archive 실패 | /opt/keepgo/cloud origin·읽기 인증·요청 SHA의 main 포함 여부를 확인한다. S3 버킷은 필요 없다. |
| Backend health/연결 실패 | 컨테이너 로그, RDS/AI 접근, env·JWT mount를 조사한다. TCP 성공이 업무 API 성공은 아니다. |
| SSM timeout | 원격 작업이 계속 실행될 수 있다. invocation과 host journal을 확인한 뒤 recover 여부를 결정한다. |
| rolled_back | 이전 Backend 복구 성공이며 신규 배포 성공이 아니다. 실패 Backend만 Manifest와 current를 정합화한다. |
| rollback_failed / frozen | 후속 배포를 유지 중단하고 실제 상태 확인·recover·정합화·resume 순서를 따른다. state 파일을 임의 삭제하지 않는다. |

조사 기록에는 시간, Cloud/App SHA, digest, CI run ID, SSM command ID, 실제 상태·결과를 남긴다. Secret·환경변수 전체 내용은 공유하지 않는다.
