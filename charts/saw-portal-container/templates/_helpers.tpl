{{/* Registrations predating catalog expansion have a single legacy slot. */}}
{{- define "portal.targets" -}}
{{- $s := .Values.site | default dict -}}
{{- if $s.targets -}}{{ $s.targets | toJson }}{{- else -}}
{{ dict "agent/audited" (dict "workspace" "agent" "sandbox" "audited" "ui" true "base" .Values.owner "relayID" .Values.registration "subjectMap" "saw-portal-relay-subject") | toJson }}
{{- end -}}
{{- end -}}
{{- define "portal.claims" -}}
{{- $claims := list -}}
{{- range $slot := include "portal.targets" . | fromJson -}}
{{- range $prefix := list "workspace-" "saw-gate-" "saw-audit-" -}}
{{- $claims = append $claims (printf "%s%s" $prefix $slot.base) -}}
{{- end -}}{{- end -}}
{{ $claims | toJson }}
{{- end -}}
