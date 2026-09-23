{{- define "standard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "standard.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "standard.name" . -}}
{{- if or (eq .Release.Name $name) (hasSuffix (printf "-%s" $name) .Release.Name) -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "standard.configMapName" -}}
{{- printf "%s-config" (include "standard.fullname" . | trunc 56 | trimSuffix "-") -}}
{{- end -}}

{{- define "standard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "standard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "standard.labels" -}}
{{- $labels := mergeOverwrite (deepCopy .Values.commonLabels) (dict "helm.sh/chart" (printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-") "app.kubernetes.io/managed-by" .Release.Service) (include "standard.selectorLabels" . | fromYaml) -}}
{{- toYaml $labels -}}
{{- end -}}

{{- define "standard.podLabels" -}}
{{- toYaml (mergeOverwrite (deepCopy .Values.podLabels) (include "standard.labels" . | fromYaml)) -}}
{{- end -}}

{{- define "standard.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "standard.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "standard.image" -}}
{{- $repository := required "image.repository is required" .Values.image.repository -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" $repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" $repository (required "image.tag or image.digest is required" .Values.image.tag) -}}
{{- end -}}
{{- end -}}

{{- define "standard.singleWriter" -}}
{{- if and .Values.persistence.enabled (not (has "ReadWriteMany" .Values.persistence.accessModes)) -}}true{{- end -}}
{{- end -}}

{{- define "standard.validate" -}}
{{- if and (or .Values.ingress.enabled .Values.serviceMonitor.enabled) (not .Values.service.enabled) -}}
{{- fail "ingress and serviceMonitor require service.enabled=true" -}}
{{- end -}}
{{- if and .Values.autoscaling.enabled (gt (int .Values.autoscaling.minReplicas) (int .Values.autoscaling.maxReplicas)) -}}
{{- fail "autoscaling.minReplicas must be <= autoscaling.maxReplicas" -}}
{{- end -}}
{{- if and (include "standard.singleWriter" .) (or .Values.autoscaling.enabled (ne (int .Values.replicaCount) 1)) -}}
{{- fail "single-writer persistence requires replicaCount=1 and autoscaling.enabled=false; use RWX only if the volume and app support it" -}}
{{- end -}}
{{- $portNames := list "http" -}}
{{- range .Values.service.extraPorts -}}
{{- if has .name $portNames -}}{{- fail (printf "duplicate service port name: %s" .name) -}}{{- end -}}
{{- $portNames = append $portNames .name -}}
{{- end -}}
{{- if and .Values.serviceMonitor.enabled (not (has .Values.serviceMonitor.port $portNames)) -}}
{{- fail "serviceMonitor.port must match a named service port (http or service.extraPorts[].name)" -}}
{{- end -}}
{{- if .Values.serviceMonitor.enabled -}}
{{- $units := dict "ms" 1 "s" 1000 "m" 60000 "h" 3600000 -}}
{{- $interval := mul (int64 (regexFind "^[0-9]+" .Values.serviceMonitor.interval)) (get $units (regexFind "(ms|s|m|h)$" .Values.serviceMonitor.interval)) -}}
{{- $timeout := mul (int64 (regexFind "^[0-9]+" .Values.serviceMonitor.scrapeTimeout)) (get $units (regexFind "(ms|s|m|h)$" .Values.serviceMonitor.scrapeTimeout)) -}}
{{- if gt $timeout $interval -}}{{- fail "serviceMonitor.scrapeTimeout must not exceed interval" -}}{{- end -}}
{{- end -}}
{{- if and (eq .Values.strategy.type "RollingUpdate") (not (include "standard.singleWriter" .)) -}}
{{- if and (has (toString .Values.strategy.rollingUpdate.maxSurge) (list "0" "0%")) (has (toString .Values.strategy.rollingUpdate.maxUnavailable) (list "0" "0%")) -}}
{{- fail "RollingUpdate requires maxSurge or maxUnavailable greater than zero" -}}
{{- end -}}
{{- end -}}
{{- $volumeNames := list -}}
{{- if .Values.tmpVolume.enabled -}}{{- $volumeNames = append $volumeNames "tmp" -}}{{- end -}}
{{- if .Values.persistence.enabled -}}{{- $volumeNames = append $volumeNames "data" -}}{{- end -}}
{{- range .Values.extraVolumes -}}
{{- if has .name $volumeNames -}}{{- fail (printf "duplicate volume name: %s" .name) -}}{{- end -}}
{{- $volumeNames = append $volumeNames .name -}}
{{- end -}}
{{- range .Values.extraVolumeMounts -}}
{{- if not (has .name $volumeNames) -}}{{- fail (printf "volumeMount %s has no matching volume" .name) -}}{{- end -}}
{{- end -}}
{{- end -}}
