import { vi } from 'vitest'
import type { Service } from '../types/service'
import type { DeploymentDetail } from '../types/deploymentDetail'

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

export function stubRoutedFetch(routes: Record<string, () => Response>) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input.toString()
      for (const [prefix, respond] of Object.entries(routes)) {
        if (url.startsWith(prefix)) return Promise.resolve(respond())
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

export function makeService(overrides: Partial<Service> = {}): Service {
  return {
    id: 1,
    name: 'orders',
    namespace: 'kubex',
    repo: 'org/orders',
    argocd_app: 'orders',
    latest_deploy: {
      commit_sha: 'abc123def',
      author: 'alice',
      status: 'deployed',
      finished_at: '2026-08-29T10:00:00Z',
    },
    health: { score: 92, verdict: 'healthy' },
    active_alert_count: 0,
    ...overrides,
  }
}

export function makeDeploymentDetail(overrides: Partial<DeploymentDetail> = {}): DeploymentDetail {
  return {
    id: 42,
    service_id: 1,
    commit_sha: 'abc123def',
    branch: 'main',
    author: 'alice',
    status: 'deployed',
    image_tag: 'v1.2.3',
    started_at: '2026-08-29T09:55:00Z',
    finished_at: '2026-08-29T10:00:00Z',
    commit_at: '2026-08-29T09:50:00Z',
    build_status: 'completed',
    build_duration_s: 60,
    sync_status: 'completed',
    workflow_run_id: 100,
    argocd_revision: 'def456',
    created_at: '2026-08-29T09:50:00Z',
    health_assessment: null,
    service: {
      id: 1,
      name: 'orders',
      repo: 'org/orders',
      argocd_app: 'orders',
      namespace: 'kubex',
      created_at: '2026-01-01T00:00:00Z',
    },
    timeline: [],
    health_evidence: [],
    ...overrides,
  }
}
