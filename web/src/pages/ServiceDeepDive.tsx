import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { DeployDiffTable } from '../components/DeployDiffTable'
import { GrafanaPanel } from '../components/GrafanaPanel'
import { PipelineTimeline } from '../components/PipelineTimeline'
import { useCompare } from '../hooks/useCompare'
import { useDeployments } from '../hooks/useDeployments'
import { useDORA } from '../hooks/useDORA'
import { useServices } from '../hooks/useServices'
import { formatDuration } from '../lib/timeline'
import type { Deployment } from '../types/deployment'
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
      <section className="flex flex-col gap-3">
        <h2 className="font-heading text-sm font-semibold text-text">Metrics</h2>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <GrafanaPanel uid="deploy-timeline" panelId={1} service={name} title="Error Rate" />
          <GrafanaPanel uid="deploy-timeline" panelId={2} service={name} title="p99 Latency" />
        </div>
      </section>
      {deployments && deployments.length > 0 && <CompareSection deployments={deployments} />}
    </div>
  )
}

type CompareSectionProps = {
  deployments: Deployment[]
}

function CompareSection({ deployments }: CompareSectionProps) {
  const [active, setActive] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const { data: compareResult, isLoading: compareLoading, isError: compareError } = useCompare(
    selected[0] ?? null,
    selected[1] ?? null,
  )

  function toggle(id: number) {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((s) => s !== id)
      if (prev.length >= 2) return prev
      return [...prev, id]
    })
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-sm font-semibold text-text">Compare</h2>
        <button
          type="button"
          onClick={() => {
            setActive((a) => !a)
            setSelected([])
          }}
          className="rounded border border-border px-3 py-1 text-xs text-text-muted hover:border-accent/50 hover:text-text"
        >
          {active ? 'Cancel' : 'Compare deployments'}
        </button>
      </div>
      {active && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-text-muted">Select two deployments to compare ({selected.length}/2).</p>
          {deployments.map((d) => {
            const shortSha = d.commit_sha ? d.commit_sha.slice(0, 7) : d.status
            const checked = selected.includes(d.id)
            const disabled = !checked && selected.length >= 2
            return (
              <label
                key={d.id}
                className={`flex items-center gap-2 rounded border border-border bg-surface px-3 py-2 text-sm ${disabled ? 'opacity-50' : ''}`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => toggle(d.id)}
                />
                <span className="font-heading text-text">{shortSha}</span>
                <span className="text-text-muted">{d.author ?? 'unknown'}</span>
              </label>
            )
          })}
          {selected.length === 2 && (
            <>
              {compareError && <p className="text-sm text-failed">Failed to load comparison.</p>}
              {compareLoading && <div className="h-32 animate-pulse rounded-lg border border-border bg-surface" />}
              {compareResult && <DeployDiffTable metrics={compareResult.metrics} />}
            </>
          )}
        </div>
      )}
    </section>
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
