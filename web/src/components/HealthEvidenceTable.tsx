import { changePercentColorClass, formatChangePercent } from '../lib/changePercent'
import type { HealthEvidenceItem } from '../types/deploymentDetail'

type HealthEvidenceTableProps = {
  evidence: HealthEvidenceItem[]
}

const METRIC_LABELS: Record<string, string> = {
  error_rate: 'Error rate',
  latency_p99: 'p99 latency',
  restarts: 'Restarts',
}

export function HealthEvidenceTable({ evidence }: HealthEvidenceTableProps) {
  return (
    <table className="w-full overflow-hidden rounded-lg border border-border text-sm">
      <thead>
        <tr className="border-b border-border bg-surface text-left text-xs text-text-muted">
          <th className="px-3 py-2 font-medium">Metric</th>
          <th className="px-3 py-2 font-medium">Baseline</th>
          <th className="px-3 py-2 font-medium">Post-deploy</th>
          <th className="px-3 py-2 font-medium">Change</th>
        </tr>
      </thead>
      <tbody>
        {evidence.map((item) => (
          <tr key={item.metric} className="border-b border-border last:border-0">
            <td className="px-3 py-2 text-text">{METRIC_LABELS[item.metric] ?? item.metric}</td>
            <td className="px-3 py-2 text-text-muted">{item.baseline ?? '—'}</td>
            <td className="px-3 py-2 text-text-muted">{item.post ?? '—'}</td>
            <td className={`px-3 py-2 font-medium ${changePercentColorClass(item.change_pct)}`}>
              {formatChangePercent(item.change_pct)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
