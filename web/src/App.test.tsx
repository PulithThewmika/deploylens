import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { jsonResponse, makeDeploymentDetail, stubRoutedFetch } from './test/fixtures'

// App.tsx builds its QueryClient as a module-level singleton, so importing
// it fresh per test (via resetModules) keeps each test's react-query cache
// isolated — otherwise all 5 cases here would share one cache instance.
async function renderApp() {
  vi.resetModules()
  const { default: App } = await import('./App')
  return render(<App />)
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

    await renderApp()

    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('renders ServiceDeepDive at /services/:name', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/services/orders')

    await renderApp()

    expect(await screen.findByRole('heading', { name: 'orders' })).toBeInTheDocument()
  })

  it('renders DeployDetail at /deployments/:id', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/deployments/42')

    await renderApp()

    expect(await screen.findByRole('heading', { name: 'Health evidence' })).toBeInTheDocument()
  })

  it('renders Chat at /chat', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/chat')

    await renderApp()

    expect(await screen.findByPlaceholderText(/ask about/i)).toBeInTheDocument()
  })

  it('falls through gracefully on an unknown route without crashing', async () => {
    stubRoutedFetch(DEFAULT_ROUTES)
    window.history.pushState({}, '', '/this-route-does-not-exist')

    const { container } = await renderApp()

    // No route (not even the AppLayout wrapper) matches an unregistered
    // path today, so nothing renders — the important thing is it doesn't throw.
    expect(screen.queryByRole('heading', { name: 'Overview' })).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/ask about/i)).not.toBeInTheDocument()
    expect(container).toBeInTheDocument()
  })
})
