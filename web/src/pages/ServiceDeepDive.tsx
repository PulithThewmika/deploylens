import { useParams } from 'react-router-dom'
import { PipelineTimeline } from '../components/PipelineTimeline'
import { useDeployments } from '../hooks/useDeployments'
import { useDORA } from '../hooks/useDORA'
import { useServices } from '../hooks/useServices'
import { formatDuration } from '../lib/timeline'
import type { DORAMetrics } from '../types/dora'

export function ServiceDeepDive() {
  const { name = '' } = useParams<{ name: string }>()
  const { data: deployments, isLoading: deploymentsLoading, isError: deploymentsError } = useDeployments(name)
  const { data: dora } = useDORA(name)
  const { data: services } = useServices()
  const service = services?.find((s) => s.name === name)

  return (
    <div className="flex flex-col gap-6 p-6">
      <ServiceHeader
        name={name}
        status={service?.latest_deploy?.status ?? null}
        environment={service?.namespace ?? null}
        dora={dora}
      />
      <section className="flex flex-col gap-3">
        <h2 className="font-heading text-sm font-semibold text-text">Pipeline timeline</h2>
        {deploymentsError ? (
          <p className="text-sm text-failed">Failed to load deployments. Retrying automatically.</p>
        ) : !deploymentsLoading && deployments?.length === 0 ? (
          <p className="text-sm text-text-muted">No deployments yet for this service.</p>
        ) : deploymentsLoading ? (
          <div className="h-40 animate-pulse rounded-lg border border-border bg-surface" />
        ) : (
          <PipelineTimeline deployments={deployments ?? []} />
        )}
      </section>
    </div>
  )
}

type ServiceHeaderProps = {
  name: string
  status: string | null
  environment: string | null
  dora: DORAMetrics | undefined
}

function ServiceHeader({ name, status, environment, dora }: ServiceHeaderProps) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-heading text-xl font-semibold text-text">{name}</h1>
        {status && (
          <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-muted">{status}</span>
        )}
        {environment && (
          <span className="rounded border border-border px-1.5 py-0.5 text-xs text-text-muted">{environment}</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <DoraStat label="Deploy frequency" value={formatFrequency(dora?.deploy_frequency_per_day)} />
        <DoraStat label="Lead time" value={formatSeconds(dora?.lead_time_avg_s)} />
        <DoraStat label="Change failure rate" value={formatPercent(dora?.change_failure_rate)} />
        <DoraStat label="MTTR" value={formatSeconds(dora?.mttr_s)} />
      </div>
    </div>
  )
}

function DoraStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="font-heading text-lg font-semibold text-text">{value}</div>
    </div>
  )
}

function formatFrequency(perDay: number | null | undefined): string {
  if (perDay === null || perDay === undefined) return '—'
  return `${perDay.toFixed(2)}/day`
}

function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  return formatDuration(seconds)
}

function formatPercent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined) return '—'
  return `${(fraction * 100).toFixed(1)}%`
}
