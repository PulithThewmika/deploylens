import type { TimelineStage } from './deployment'

export type ServiceInfo = {
  id: number
  name: string
  repo: string | null
  argocd_app: string | null
  namespace: string
  created_at: string
}

export type HealthAssessment = {
  id: number
  deployment_id: number
  score: number
  verdict: string
  error_rate_base: number | null
  error_rate_post: number | null
  latency_p99_base_ms: number | null
  latency_p99_post_ms: number | null
  restarts_base: number | null
  restarts_post: number | null
  assessed_at: string | null
}

export type HealthEvidenceItem = {
  metric: string
  baseline: number | null
  post: number | null
  change_pct: number | null
}

export type DeploymentDetail = {
  id: number
  service_id: number
  commit_sha: string | null
  branch: string | null
  author: string | null
  status: string
  image_tag: string | null
  started_at: string
  finished_at: string | null
  commit_at: string | null
  build_status: string | null
  build_duration_s: number | null
  sync_status: string | null
  workflow_run_id: number | null
  argocd_revision: string | null
  created_at: string
  health_assessment: HealthAssessment | null
  service: ServiceInfo | null
  timeline: TimelineStage[]
  health_evidence: HealthEvidenceItem[]
}
