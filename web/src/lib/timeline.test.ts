import { describe, expect, it } from 'vitest'
import { calcStageDurations, fillIncompleteTimeline, formatDuration, normalizeStageStatus } from './timeline'
import type { TimelineStage } from '../types/deployment'

describe('calcStageDurations', () => {
  it('uses duration_s when the backend supplies it', () => {
    const stages: TimelineStage[] = [
      { stage: 'build', at: '2026-08-29T10:00:00Z', status: 'success', duration_s: 42 },
    ]
    expect(calcStageDurations(stages)).toEqual([42])
  })

  it('falls back to the gap to the next timestamped stage', () => {
    const stages: TimelineStage[] = [
      { stage: 'commit', at: '2026-08-29T10:00:00Z', status: 'completed', duration_s: null },
      { stage: 'sync', at: null, status: 'in_progress', duration_s: null },
      { stage: 'deploy', at: '2026-08-29T10:01:30Z', status: 'completed', duration_s: null },
    ]
    expect(calcStageDurations(stages)).toEqual([90, 0, 0])
  })

  it('caps an absurd derived gap (e.g. deploy -> a much-later assess job) at 0 rather than a huge duration', () => {
    const stages: TimelineStage[] = [
      { stage: 'deploy', at: '2026-08-03T19:49:47Z', status: 'completed', duration_s: null },
      { stage: 'assess', at: '2026-08-21T11:06:11Z', status: 'completed', duration_s: null },
    ]
    expect(calcStageDurations(stages)).toEqual([0, 0])
  })

  it('returns 0 for a stage with no timestamp and no later timestamped stage', () => {
    const stages: TimelineStage[] = [
      { stage: 'sync', at: null, status: 'in_progress', duration_s: null },
    ]
    expect(calcStageDurations(stages)).toEqual([0])
  })
})

describe('fillIncompleteTimeline', () => {
  it('fills in missing later stages as pending placeholders', () => {
    const stages: TimelineStage[] = [
      { stage: 'commit', at: '2026-08-29T10:00:00Z', status: 'completed', duration_s: null },
      { stage: 'build', at: '2026-08-29T10:00:05Z', status: 'building', duration_s: null },
    ]
    expect(fillIncompleteTimeline(stages)).toEqual([
      stages[0],
      stages[1],
      { stage: 'sync', at: null, status: 'pending', duration_s: null },
      { stage: 'deploy', at: null, status: 'pending', duration_s: null },
      { stage: 'assess', at: null, status: 'pending', duration_s: null },
    ])
  })

  it('leaves a complete timeline untouched', () => {
    const stages: TimelineStage[] = [
      { stage: 'commit', at: '2026-08-29T10:00:00Z', status: 'completed', duration_s: null },
      { stage: 'build', at: '2026-08-29T10:00:05Z', status: 'success', duration_s: 60 },
      { stage: 'sync', at: null, status: 'Synced', duration_s: null },
      { stage: 'deploy', at: '2026-08-29T10:02:00Z', status: 'completed', duration_s: null },
      { stage: 'assess', at: '2026-08-29T10:17:00Z', status: 'completed', duration_s: null },
    ]
    expect(fillIncompleteTimeline(stages)).toEqual(stages)
  })
})

describe('normalizeStageStatus', () => {
  it.each([
    ['success', 'success'],
    ['completed', 'success'],
    ['Synced', 'success'],
    ['failure', 'failure'],
    ['Failed', 'failure'],
    ['build_failed', 'failure'],
    ['sync_failed', 'failure'],
    ['building', 'in-progress'],
    ['in_progress', 'in-progress'],
    ['OutOfSync', 'in-progress'],
    ['pending', 'pending'],
    ['something_unrecognized', 'pending'],
  ])('normalizes %s to %s', (input, expected) => {
    expect(normalizeStageStatus(input)).toBe(expected)
  })
})

describe('formatDuration', () => {
  it.each([
    [0, '0s'],
    [45, '45s'],
    [90, '1m 30s'],
    [120, '2m'],
  ])('formats %i seconds as %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected)
  })
})
