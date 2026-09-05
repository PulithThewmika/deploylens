{{/*
Chart name and version, used in the "helm.sh/chart" label.
*/}}
{{- define "kubex-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels applied to every resource.
*/}}
{{- define "kubex-agent.labels" -}}
helm.sh/chart: {{ include "kubex-agent.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Selector labels for a given component (e.g. "prometheus", "fluent-bit").
Deliberately just "name" — "instance" already lives in
kubex-agent.labels, and every template that needs both concatenates
this with that, so duplicating the key here would produce two
app.kubernetes.io/instance entries in the same labels map.
*/}}
{{- define "kubex-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ .component }}
{{- end -}}

{{/*
Fully-qualified resource name for a given component.
*/}}
{{- define "kubex-agent.fullname" -}}
{{ .root.Release.Name }}-{{ .component }}
{{- end -}}
