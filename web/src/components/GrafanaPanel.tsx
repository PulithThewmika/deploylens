import { useEffect, useState } from 'react'

type GrafanaPanelProps = {
  uid: string
  panelId: number
  service: string
  from?: string
  to?: string
  title: string
}

export function GrafanaPanel({ uid, panelId, service, from = 'now-6h', to = 'now', title }: GrafanaPanelProps) {
  const [status, setStatus] = useState<'loading' | 'loaded' | 'error'>('loading')

  const params = new URLSearchParams({
    uid,
    panelId: String(panelId),
    'var-service': service,
    from,
    to,
    theme: 'dark',
  })
  const src = `/api/grafana/proxy?${params.toString()}`

  useEffect(() => {
    setStatus('loading')
    let cancelled = false
    // <iframe onError> only fires on network-level failures — a 502 from
    // the proxy (e.g. Grafana unreachable) still "loads" its error body
    // successfully and fires onLoad, never onError. A GET preflight lets
    // us catch real backend failures the iframe itself can't detect.
    // (The route is GET-only — HEAD returns 405 — so this duplicates the
    // iframe's own request; acceptable for two lightweight panels a page.)
    fetch(src)
      .then((res) => {
        if (!cancelled && !res.ok) setStatus('error')
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [src])

  return (
    <div className="relative h-64 overflow-hidden rounded-lg border border-border bg-surface">
      {status === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-text-muted">
          Loading {title}…
        </div>
      )}
      {status === 'error' && (
        <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-sm text-failed">
          Failed to load {title} panel.
        </div>
      )}
      <iframe
        title={title}
        src={src}
        className={`h-full w-full border-0 ${status === 'loaded' ? '' : 'invisible'}`}
        onLoad={() => setStatus((s) => (s === 'error' ? s : 'loaded'))}
        onError={() => setStatus('error')}
      />
    </div>
  )
}
