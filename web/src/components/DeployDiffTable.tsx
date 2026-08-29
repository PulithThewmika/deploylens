import type { CompareMetric } from '../types/compare'

type DeployDiffTableProps = {
  metrics: CompareMetric[]
}

const METRIC_LABELS: Record<string, string> = {
  error_rate: 'Error rate',
  latency_p99: 'p99 latency',
  restarts: 'Restarts',
}

export function DeployDiffTable({ metrics }: DeployDiffTableProps) {
  return (
    <table className="w-full overflow-hidden rounded-lg border border-border text-sm">
      <thead>
        <tr className="border-b border-border bg-surface text-left text-xs text-text-muted">
          <th className="px-3 py-2 font-medium">Metric</th>
          <th className="px-3 py-2 font-medium">Deploy A</th>
          <th className="px-3 py-2 font-medium">Deploy B</th>
          <th className="px-3 py-2 font-medium">Change</th>
        </tr>
      </thead>
      <tbody>
        {metrics.map((m) => (
          <tr key={m.metric} className="border-b border-border last:border-0">
            <td className="px-3 py-2 text-text">{METRIC_LABELS[m.metric] ?? m.metric}</td>
            <td className="px-3 py-2 text-text-muted">{m.deploy_a ?? '—'}</td>
            <td className="px-3 py-2 text-text-muted">{m.deploy_b ?? '—'}</td>
            <td className={`px-3 py-2 font-medium ${changeColorClass(m.change_pct)}`}>{formatChange(m.change_pct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function changeColorClass(changePct: number | null): string {
  if (changePct === null) return 'text-text-muted'
  if (changePct < 0) return 'text-healthy'
  if (changePct > 0) return 'text-failed'
  return 'text-text-muted'
}

function formatChange(changePct: number | null): string {
  if (changePct === null) return '—'
  const sign = changePct > 0 ? '+' : ''
  return `${sign}${changePct}%`
}
