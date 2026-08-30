import type { TimelineStage } from '../types/deployment'

export type NormalizedStatus = 'success' | 'failure' | 'in-progress' | 'pending'

const SUCCESS_STATUSES = new Set(['success', 'completed', 'synced'])
const FAILURE_STATUSES = new Set(['failure', 'failed', 'build_failed', 'sync_failed'])
const IN_PROGRESS_STATUSES = new Set(['building', 'in_progress', 'outofsync'])

/**
 * The backend's TimelineStage.status vocabulary differs per stage (GitHub
 * Actions conclusions for build, ArgoCD sync states for sync, generic
 * "completed" elsewhere). This collapses all of it into the 4 canonical
 * states the UI renders: success, failure, in-progress, pending.
 */
export function normalizeStageStatus(status: string): NormalizedStatus {
  const s = status.toLowerCase()
  if (SUCCESS_STATUSES.has(s)) return 'success'
  if (FAILURE_STATUSES.has(s)) return 'failure'
  if (IN_PROGRESS_STATUSES.has(s)) return 'in-progress'
  return 'pending'
}

export const STAGE_STATUS_COLORS: Record<NormalizedStatus, string> = {
  success: '#22C55E',
  failure: '#EF4444',
  'in-progress': '#3B82F6',
  pending: '#6B7280',
}

/**
 * Display labels per the spec's stage names (commit/build/sync/rollout/
 * health) mapped from the backend's actual stage keys (commit/build/sync/
 * deploy/assess — see _build_timeline in services/ingest).
 */
export const STAGE_LABELS: Record<string, string> = {
  commit: 'Commit',
  build: 'Build',
  sync: 'Sync',
  deploy: 'Rollout',
  assess: 'Health',
}

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage
}

const CANONICAL_STAGE_ORDER = ['commit', 'build', 'sync', 'deploy', 'assess']

/**
 * A deployment still mid-pipeline only has entries for stages already
 * reached (see _build_timeline in services/ingest) — later stages are
 * simply absent from the array. Fills those in as pending placeholders so
 * every row always renders all 5 canonical stage segments.
 */
export function fillIncompleteTimeline(stages: TimelineStage[]): TimelineStage[] {
  const byStage = new Map(stages.map((s) => [s.stage, s]))
  return CANONICAL_STAGE_ORDER.map(
    (key) => byStage.get(key) ?? { stage: key, at: null, status: 'pending', duration_s: null },
  )
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const remainingS = Math.round(seconds % 60)
  return remainingS > 0 ? `${minutes}m ${remainingS}s` : `${minutes}m`
}

// The gap-to-next-timestamp fallback below assumes the next timestamped
// stage marks the end of this one, which breaks down for "assess": it's a
// background health-check job, not the end of "deploy"/rollout, and can run
// arbitrarily long after finished_at (observed live: 17+ days in seeded
// data, versus the ~15-30min BASELINE/OBSERVATION windows in normal
// operation). Past this ceiling the gap almost certainly isn't a real stage
// duration, so treat it as unknown (minimum-width segment) instead of
// letting one stage's segment swallow the whole row.
const MAX_DERIVED_DURATION_S = 3600

/**
 * Derives each stage's duration in seconds. Uses the backend-supplied
 * duration_s when present; otherwise falls back to the gap between this
 * stage's timestamp and the next stage with a known timestamp (several
 * backend stages, e.g. sync, never carry their own `at`), capped at
 * MAX_DERIVED_DURATION_S.
 */
export function calcStageDurations(stages: TimelineStage[]): number[] {
  return stages.map((stage, i) => {
    if (stage.duration_s !== null) {
      return stage.duration_s
    }
    if (stage.at) {
      const next = stages.slice(i + 1).find((s) => s.at !== null)
      if (next?.at) {
        const diffS = (new Date(next.at).getTime() - new Date(stage.at).getTime()) / 1000
        if (diffS > MAX_DERIVED_DURATION_S) return 0
        return Math.max(diffS, 0)
      }
    }
    return 0
  })
}
