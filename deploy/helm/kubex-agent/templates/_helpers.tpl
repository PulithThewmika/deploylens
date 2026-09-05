{{/*
Chart name and version, used in the "helm.sh/chart" label.
*/}}
{{- define "deploylens-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels applied to every resource.
*/}}
{{- define "deploylens-agent.labels" -}}
helm.sh/chart: {{ include "deploylens-agent.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Selector labels for a given component (e.g. "prometheus", "fluent-bit").
Deliberately just "name" — "instance" already lives in
deploylens-agent.labels, and every template that needs both concatenates
this with that, so duplicating the key here would produce two
app.kubernetes.io/instance entries in the same labels map.
*/}}
{{- define "deploylens-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ .component }}
{{- end -}}

{{/*
Fully-qualified resource name for a given component.
*/}}
{{- define "deploylens-agent.fullname" -}}
{{ .root.Release.Name }}-{{ .component }}
{{- end -}}
