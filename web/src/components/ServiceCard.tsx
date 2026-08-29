import { formatDistanceToNow } from 'date-fns'
import { HealthRing } from './HealthRing'
import type { Service } from '../types/service'

type ServiceCardProps = {
  service: Service
}

export function ServiceCard({ service }: ServiceCardProps) {
  const { name, namespace, latest_deploy, health, active_alert_count } = service
  const shortSha = latest_deploy?.commit_sha ? latest_deploy.commit_sha.slice(0, 7) : null

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 transition-colors hover:border-accent/50">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="font-heading text-base font-semibold text-text">{name}</span>
            {active_alert_count > 0 && (
              <span
                className="flex items-center gap-1 rounded-full bg-failed/10 px-1.5 py-0.5 text-xs font-medium text-failed"
                aria-label={`${active_alert_count} active alert${active_alert_count === 1 ? '' : 's'}`}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-failed" aria-hidden="true" />
                {active_alert_count}
              </span>
            )}
          </div>
          <span className="w-fit rounded border border-border px-1.5 py-0.5 text-xs text-text-muted">
            {namespace}
          </span>
        </div>
        <HealthRing score={health?.score ?? null} verdict={health?.verdict ?? null} size={48} />
      </div>

      <div className="text-xs text-text-muted">
        {shortSha ? (
          <span>
            {shortSha} by {latest_deploy?.author ?? 'unknown'}
            {latest_deploy?.finished_at
              ? ` — ${formatDistanceToNow(new Date(latest_deploy.finished_at), { addSuffix: true })}`
              : ''}
          </span>
        ) : (
          <span>No deploys yet</span>
        )}
      </div>
    </div>
  )
}
