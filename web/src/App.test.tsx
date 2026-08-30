import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { DeploymentDetail } from './types/deploymentDetail'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function makeDeploymentDetail(overrides: Partial<DeploymentDetail> = {}): DeploymentDetail {
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
    service: { id: 1, name: 'orders', repo: 'org/orders', argocd_app: 'orders', namespace: 'deploylens', created_at: '2026-01-01T00:00:00Z' },
    timeline: [],
    health_evidence: [],
    ...overrides,
  }
}

function stubRoutedFetch(routes: Record<string, () => Response>) {
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

const DEFAULT_ROUTES = {
  '/api/services': () => jsonResponse([]),
  '/api/deployments/': () => jsonResponse(makeDeploymentDetail()),
  '/api/deployments': () => jsonResponse([]),
  '/api/dora': () => jsonResponse({ deploy_frequency_per_day: null, lead_time_avg_s: null, change_failure_rate: null, mttr_s: null, period: '30d', service: null }),
  '/api/grafana/proxy': () => new Response(null, { status: 200 }),
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('App routing', () => {
  it('renders Overview at /', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('renders ServiceDeepDive at /services/:name', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/services/orders')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'orders' })).toBeInTheDocument()
  })

  it('renders DeployDetail at /deployments/:id', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/deployments/42')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Health evidence' })).toBeInTheDocument()
  })

  it('renders Chat at /chat', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/chat')

    render(<App />)

    expect(await screen.findByPlaceholderText(/ask about/i)).toBeInTheDocument()
  })

  it('falls through gracefully on an unknown route without crashing', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/this-route-does-not-exist')

    const { container } = render(<App />)

    // No route (not even the AppLayout wrapper) matches an unregistered
    // path today, so nothing renders — the important thing is it doesn't throw.
    expect(screen.queryByRole('heading', { name: 'Overview' })).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/ask about/i)).not.toBeInTheDocument()
    expect(container).toBeInTheDocument()
  })
})
