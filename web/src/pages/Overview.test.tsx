import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Overview } from './Overview'
import type { Service } from '../types/service'

function makeService(overrides: Partial<Service> = {}): Service {
  return {
    id: 1,
    name: 'orders',
    namespace: 'deploylens',
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

function renderOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/services/:name" element={<div>Deep Dive Page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Overview page', () => {
  it('renders loading skeletons while fetching', async () => {
    let resolveFetch!: (res: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn().mockReturnValue(new Promise<Response>((resolve) => (resolveFetch = resolve))),
    )

    const { container } = renderOverview()

    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)

    resolveFetch(new Response(JSON.stringify([]), { status: 200 }))
    await waitFor(() => expect(container.querySelectorAll('.animate-pulse').length).toBe(0))
  })

  it('renders service cards after a successful fetch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify([makeService()]), { status: 200 })),
    )

    renderOverview()

    expect(await screen.findByText('orders')).toBeInTheDocument()
    expect(screen.getByText('deploylens')).toBeInTheDocument()
  })

  it('renders a message when the API returns no services', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 })))

    renderOverview()

    expect(await screen.findByText(/no services registered yet/i)).toBeInTheDocument()
  })

  it('renders a failure message on API error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 500 })))

    renderOverview()

    expect(await screen.findByText('Failed to load services. Retrying automatically.')).toBeInTheDocument()
  })

  it('navigates to /services/:name when a service card is clicked', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify([makeService({ name: 'payments' })]), { status: 200 })),
    )

    renderOverview()

    const card = await screen.findByText('payments')
    fireEvent.click(card)

    expect(await screen.findByText('Deep Dive Page')).toBeInTheDocument()
  })
})
