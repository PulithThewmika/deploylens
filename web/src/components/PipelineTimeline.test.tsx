import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PipelineTimeline } from './PipelineTimeline'
import type { Deployment } from '../types/deployment'

function makeDeployment(overrides: Partial<Deployment> = {}): Deployment {
  return {
    id: 1,
    service_id: 1,
    service_name: 'orders',
    commit_sha: 'abc1234def',
    branch: 'main',
    author: 'pulith',
    status: 'assessed',
    image_tag: null,
    started_at: '2026-08-29T10:00:00Z',
    finished_at: '2026-08-29T10:02:00Z',
    health: { score: 92, verdict: 'healthy' },
    timeline: [
      { stage: 'commit', at: '2026-08-29T10:00:00Z', status: 'completed', duration_s: null },
      { stage: 'build', at: '2026-08-29T10:00:05Z', status: 'success', duration_s: 95 },
      { stage: 'sync', at: null, status: 'Synced', duration_s: null },
      { stage: 'deploy', at: '2026-08-29T10:02:00Z', status: 'completed', duration_s: null },
      { stage: 'assess', at: '2026-08-29T10:17:00Z', status: 'completed', duration_s: null },
    ],
    ...overrides,
  }
}

describe('PipelineTimeline', () => {
  it('renders a row per deployment with its short SHA', () => {
    render(<PipelineTimeline deployments={[makeDeployment({ id: 1, commit_sha: 'abc1234def' })]} />)
    expect(screen.getByText('abc1234')).toBeInTheDocument()
  })

  it('caps rendering at the last 10 deployments', () => {
    const deployments = Array.from({ length: 15 }, (_, i) =>
      makeDeployment({ id: i, commit_sha: `sha${i.toString().padStart(4, '0')}` }),
    )
    render(<PipelineTimeline deployments={deployments} />)
    expect(screen.getAllByText(/^sha0\d{3}$/)).toHaveLength(10)
  })

  it('orders rows by most-recent-first regardless of input order', () => {
    const older = makeDeployment({ id: 1, commit_sha: 'older111', started_at: '2026-08-29T08:00:00Z' })
    const newer = makeDeployment({ id: 2, commit_sha: 'newer222', started_at: '2026-08-29T12:00:00Z' })
    render(<PipelineTimeline deployments={[older, newer]} />)
    const shas = screen.getAllByText(/^(older|newer)/).map((el) => el.textContent)
    expect(shas).toEqual(['newer22', 'older11'])
  })

  it('pads an in-flight deployment with pending stages instead of crashing', () => {
    const inFlight = makeDeployment({
      id: 2,
      commit_sha: 'fed9876cba',
      timeline: [{ stage: 'commit', at: '2026-08-29T11:00:00Z', status: 'completed', duration_s: null }],
    })
    render(<PipelineTimeline deployments={[inFlight]} />)
    expect(screen.getByText('fed9876')).toBeInTheDocument()
  })
})
