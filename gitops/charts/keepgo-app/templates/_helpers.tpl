{{/*
리소스 이름. 기본은 릴리스 이름(auth-api 등)이다.
쿠버네티스 이름 길이 제한(63자)에 맞춰 자른다.
*/}}
{{- define "keepgo-app.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else if .Values.nameOverride -}}
{{- .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Pod를 고르는 라벨. 배포 후에는 바꿀 수 없으므로 변하지 않는 값만 넣는다.
*/}}
{{- define "keepgo-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "keepgo-app.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
모든 리소스에 붙이는 공통 라벨
*/}}
{{- define "keepgo-app.labels" -}}
{{ include "keepgo-app.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | toString | trunc 63 | trimSuffix "-" | quote }}
app.kubernetes.io/component: {{ .Values.component }}
app.kubernetes.io/part-of: keepgo
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/*
ServiceAccount 이름. Pod Identity association이 이 이름을 기준으로 IAM 역할을 붙인다.
*/}}
{{- define "keepgo-app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- .Values.serviceAccount.name | default (include "keepgo-app.fullname" .) -}}
{{- else -}}
{{- .Values.serviceAccount.name | default "default" -}}
{{- end -}}
{{- end -}}

{{/*
이미지 주소. repository·tag가 비어 있으면 렌더링을 멈춰 잘못된 배포를 막는다.
*/}}
{{- define "keepgo-app.image" -}}
{{- $repo := required "image.repository 값이 필요합니다" .Values.image.repository -}}
{{- $tag := required "image.tag 값이 필요합니다 (커밋 SHA)" .Values.image.tag -}}
{{- if eq (toString $tag) "latest" -}}
{{- fail "image.tag에 latest는 쓰지 않습니다 (5-4 4.3)" -}}
{{- end -}}
{{- printf "%s:%s" $repo (toString $tag) -}}
{{- end -}}

{{/*
Resources 검사(5-4 7.3, 5-3 3.2). 규칙을 어기면 렌더링을 멈춘다.
  - requests.cpu, requests.memory, limits.memory 필수
  - 메모리는 requests = limits
CPU limit은 기본으로 걸지 않지만, 특정 서비스에 필요하면 허용한다(5-3 3.2).
*/}}
{{- define "keepgo-app.resources" -}}
{{- $r := .Values.resources | default dict -}}
{{- $req := $r.requests | default dict -}}
{{- $lim := $r.limits | default dict -}}
{{- $_ := required "resources.requests.cpu 값이 필요합니다 (5-3 3.3 표 참고)" $req.cpu -}}
{{- $reqMem := required "resources.requests.memory 값이 필요합니다 (5-3 3.3 표 참고)" $req.memory -}}
{{- $limMem := required "resources.limits.memory 값이 필요합니다 (requests.memory와 같은 값)" $lim.memory -}}
{{- if ne (toString $reqMem) (toString $limMem) -}}
{{- fail (printf "메모리는 requests와 limits를 같은 값으로 둡니다 (5-3 3.2): requests=%v, limits=%v" $reqMem $limMem) -}}
{{- end -}}
{{- toYaml $r -}}
{{- end -}}

{{/*
헬스체크 프리셋(5-3 4.3). 서비스 values의 probes.<종류>에 적은 값이 이 기본값을 덮어쓴다.
startup 최대 대기 = periodSeconds × failureThreshold
*/}}
{{- define "keepgo-app.probePresets" -}}
spring:
  # Actuator Probe 그룹. 관리 포트(8081)로만 확인하고 DB 등 외부 의존성은 보지 않는다.
  startup:   {enabled: true, path: /actuator/health/liveness,  port: management, periodSeconds: 5,  timeoutSeconds: 3, failureThreshold: 30}
  readiness: {enabled: true, path: /actuator/health/readiness, port: management, periodSeconds: 10, timeoutSeconds: 3, failureThreshold: 3}
  liveness:  {enabled: true, path: /actuator/health/liveness,  port: management, periodSeconds: 10, timeoutSeconds: 3, failureThreshold: 3}
fastapi:
  # ready는 앱 초기화와 AI 클라이언트 생성 여부만 확인한다(5-3 4.3).
  startup:   {enabled: true, path: /health/live,  port: http, periodSeconds: 5,  timeoutSeconds: 3, failureThreshold: 12}
  readiness: {enabled: true, path: /health/ready, port: http, periodSeconds: 10, timeoutSeconds: 3, failureThreshold: 3}
  liveness:  {enabled: true, path: /health/live,  port: http, periodSeconds: 10, timeoutSeconds: 3, failureThreshold: 3}
nextjs:
  # 전용 헬스 경로가 생기기 전까지 첫 화면으로 확인한다. 3xx(로그인 리다이렉트)도 성공으로 본다.
  startup:   {enabled: true, path: /, port: http, periodSeconds: 5,  timeoutSeconds: 3, failureThreshold: 12}
  readiness: {enabled: true, path: /, port: http, periodSeconds: 10, timeoutSeconds: 3, failureThreshold: 3}
  liveness:  {enabled: true, path: /, port: http, periodSeconds: 10, timeoutSeconds: 3, failureThreshold: 3}
{{- end -}}

{{/*
헬스체크 하나를 그린다. 인자: dict "root" $ "kind" "startup|readiness|liveness"
꺼져 있으면 아무것도 그리지 않는다.
*/}}
{{- define "keepgo-app.probe" -}}
{{- $root := .root -}}
{{- $presets := include "keepgo-app.probePresets" $root | fromYaml -}}
{{- $name := $root.Values.probes.preset | default "spring" -}}
{{- if not (hasKey $presets $name) -}}
{{- fail (printf "probes.preset은 spring, fastapi, nextjs 중 하나입니다: %s" $name) -}}
{{- end -}}
{{- $base := index $presets $name .kind -}}
{{- $override := index $root.Values.probes .kind | default dict -}}
{{- $p := merge (deepCopy $override) $base -}}
{{- /* merge는 false를 빈 값으로 보고 기본값(true)으로 덮으므로 enabled는 따로 읽는다 */ -}}
{{- $enabled := $base.enabled -}}
{{- if hasKey $override "enabled" -}}
{{- $enabled = $override.enabled -}}
{{- end -}}
{{- if $enabled -}}
httpGet:
  path: {{ $p.path }}
  port: {{ $p.port }}
{{- with $p.initialDelaySeconds }}
initialDelaySeconds: {{ . }}
{{- end }}
periodSeconds: {{ $p.periodSeconds }}
timeoutSeconds: {{ $p.timeoutSeconds }}
failureThreshold: {{ $p.failureThreshold }}
{{- end -}}
{{- end -}}
