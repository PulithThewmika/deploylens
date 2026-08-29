import type { HealthSummary } from './service'

export type TimelineStage = {
  stage: string
  at: string | null
  status: string
  duration_s: number | null
}

export type Deployment = {
  id: number
  service_id: number
  service_name: string
  commit_sha: string | null
  branch: string | null
  author: string | null
  status: string
  image_tag: string | null
  started_at: string
  finished_at: string | null
  health: HealthSummary | null
  timeline: TimelineStage[]
}
