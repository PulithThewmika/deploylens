import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ServiceDeepDive } from './ServiceDeepDive'
import { jsonResponse, makeService, stubRoutedFetch } from '../test/fixtures'
import type { Deployment } from '../types/deployment'
import type { DORAMetrics } from '../types/dora'

function makeDeployment(overrides: Partial<Deployment> = {}): Deployment {
  return {
    id: 10,
    service_id: 1,
    service_name: 'orders',
    commit_sha: 'abc123def',
    branch: 'main',
    author: 'alice',
    status: 'deployed',
    image_tag: 'v1.2.3',
    started_at: '2026-08-29T09:55:00Z',
    finished_at: '2026-08-29T10:00:00Z',
    health: { score: 92, verdict: 'healthy' },
    timeline: [
      { stage: 'build', at: '2026-08-29T09:56:00Z', status: 'completed', duration_s: 60 },
      { stage: 'deploy', at: '2026-08-29T10:00:00Z', status: 'completed', duration_s: 240 },
    ],
    ...overrides,
  }
}

function makeDora(overrides: Partial<DORAMetrics> = {}): DORAMetrics {
  return {
    deploy_frequency_per_day: 4.2,
    lead_time_avg_s: 1380,
    change_failure_rate: 0.12,
    mttr_s: 2700,
    period: '30d',
    service: 'orders',
    ...overrides,
  }
}

const DEFAULT_ROUTES = {
  '/api/services': () => jsonResponse([makeService()]),
  '/api/deployments': () => jsonResponse([makeDeployment()]),
  '/api/dora': () => jsonResponse(makeDora()),
  '/api/grafana/proxy': () => new Response(null, { status: 200 }),
}

function renderServiceDeepDive(name = 'orders') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/services/${name}`]}>
        <Routes>
          <Route path="/services/:name" element={<ServiceDeepDive />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('ServiceDeepDive page', () => {
  it('renders the service name, status, and environment from API data', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)

    renderServiceDeepDive()

    expect(await screen.findByRole('heading', { name: 'orders' })).toBeInTheDocument()
    expect(await screen.findByText('deployed')).toBeInTheDocument()
    expect(await screen.findByText('deploylens')).toBeInTheDocument()
  })

  it('renders DORA mini-stats: deploy frequency, lead time, change failure rate, and MTTR', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)

    renderServiceDeepDive()

    expect(await screen.findByText('4.20/day')).toBeInTheDocument()
    expect(screen.getByText('Deploy frequency')).toBeInTheDocument()
    expect(screen.getByText('Lead time')).toBeInTheDocument()
    expect(screen.getByText('Change failure rate')).toBeInTheDocument()
    expect(screen.getByText('12.0%')).toBeInTheDocument()
    expect(screen.getByText('MTTR')).toBeInTheDocument()
  })

  it('renders the pipeline timeline with deployments', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)

    renderServiceDeepDive()

    expect(await screen.findByText('abc123d')).toBeInTheDocument()
  })

  it('shows the "Compare deployments" button once deployments have loaded', async () => {
    stubRoutedFetch({
      ...DEFAULT_ROUTES,
      '/api/deployments': () => jsonResponse([makeDeployment(), makeDeployment({ id: 11 })]),
    })

    renderServiceDeepDive()

    expect(await screen.findByRole('button', { name: 'Compare deployments' })).toBeInTheDocument()
  })

  it('renders an error state for an unknown service whose deployments fail to load', async () => {
    stubRoutedFetch({
      ...DEFAULT_ROUTES,
      '/api/services': () => jsonResponse([]),
      '/api/deployments': () => new Response(null, { status: 500 }),
      '/api/dora': () => new Response(null, { status: 500 }),
    })

    renderServiceDeepDive('does-not-exist')

    expect(await screen.findByRole('heading', { name: 'does-not-exist' })).toBeInTheDocument()
    expect(await screen.findByText('Failed to load deployments. Retrying automatically.')).toBeInTheDocument()
  })
})
