{{/*
리소스 이름. 기본은 릴리스 이름(auth-api 등)이다.
쿠버네티스 이름 길이 제한(63자)에 맞춰 자른다.
*/}}
{{- define "app.fullname" -}}
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
{{- define "app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "app.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
모든 리소스에 붙이는 공통 라벨
*/}}
{{- define "app.labels" -}}
{{ include "app.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | toString | trunc 63 | trimSuffix "-" | quote }}
app.kubernetes.io/component: {{ .Values.component }}
app.kubernetes.io/part-of: keepgo
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/*
ServiceAccount 이름
*/}}
{{- define "app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- .Values.serviceAccount.name | default (include "app.fullname" .) -}}
{{- else -}}
{{- .Values.serviceAccount.name | default "default" -}}
{{- end -}}
{{- end -}}

{{/*
이미지 주소. repository·tag가 비어 있으면 렌더링을 멈춰 잘못된 배포를 막는다.
*/}}
{{- define "app.image" -}}
{{- $repo := required "image.repository 값이 필요합니다" .Values.image.repository -}}
{{- $tag := required "image.tag 값이 필요합니다" .Values.image.tag -}}
{{- printf "%s:%s" $repo (toString $tag) -}}
{{- end -}}

{{/*
HTTP 헬스체크 하나를 그린다. 인자: probe 설정 맵
*/}}
{{- define "app.httpProbe" -}}
httpGet:
  path: {{ .path }}
  port: {{ .port }}
{{- with .initialDelaySeconds }}
initialDelaySeconds: {{ . }}
{{- end }}
periodSeconds: {{ .periodSeconds }}
timeoutSeconds: {{ .timeoutSeconds }}
failureThreshold: {{ .failureThreshold }}
{{- end -}}
