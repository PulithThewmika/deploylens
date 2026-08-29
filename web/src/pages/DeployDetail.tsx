import { useParams } from 'react-router-dom'
import { HealthEvidenceTable } from '../components/HealthEvidenceTable'
import { PipelineTimeline } from '../components/PipelineTimeline'
import { useDeployment } from '../hooks/useDeployment'
import type { Deployment } from '../types/deployment'
import type { DeploymentDetail } from '../types/deploymentDetail'

export function DeployDetail() {
  const { id } = useParams<{ id: string }>()
  const deployId = Number(id)
  const { data: deployment, isLoading, isError } = useDeployment(deployId)

  if (isError) {
    return (
      <div className="p-6">
        <p className="text-sm text-failed">Failed to load deployment.</p>
      </div>
    )
  }

  if (isLoading || !deployment) {
    return (
      <div className="p-6">
        <div className="h-40 animate-pulse rounded-lg border border-border bg-surface" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <DeployMetadata deployment={deployment} />
      <section className="flex flex-col gap-3">
        <h2 className="font-heading text-sm font-semibold text-text">Pipeline timeline</h2>
        <PipelineTimeline deployments={[toDeployment(deployment)]} size="large" />
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="font-heading text-sm font-semibold text-text">Health evidence</h2>
        {deployment.health_assessment && deployment.health_evidence.length > 0 ? (
          <HealthEvidenceTable evidence={deployment.health_evidence} />
        ) : (
          <p className="text-sm text-text-muted">Assessment pending.</p>
        )}
      </section>
    </div>
  )
}

function toDeployment(d: DeploymentDetail): Deployment {
  return {
    id: d.id,
    service_id: d.service_id,
    service_name: d.service?.name ?? '',
    commit_sha: d.commit_sha,
    branch: d.branch,
    author: d.author,
    status: d.status,
    image_tag: d.image_tag,
    started_at: d.started_at,
    finished_at: d.finished_at,
    health: d.health_assessment
      ? { score: d.health_assessment.score, verdict: d.health_assessment.verdict }
      : null,
    timeline: d.timeline,
  }
}

function DeployMetadata({ deployment }: { deployment: NonNullable<ReturnType<typeof useDeployment>['data']> }) {
  const shortSha = deployment.commit_sha ? deployment.commit_sha.slice(0, 7) : null
  const commitUrl =
    deployment.service?.repo && deployment.commit_sha
      ? `https://github.com/${deployment.service.repo}/commit/${deployment.commit_sha}`
      : null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-heading text-xl font-semibold text-text">
          {commitUrl ? (
            <a href={commitUrl} target="_blank" rel="noreferrer" className="hover:text-accent hover:underline">
              {shortSha}
            </a>
          ) : (
            shortSha ?? deployment.status
          )}
        </h1>
        <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-muted">
          {deployment.status}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <MetaField label="Branch" value={deployment.branch} />
        <MetaField label="Author" value={deployment.author} />
        <MetaField label="Environment" value={deployment.service?.namespace ?? null} />
        <MetaField label="Started" value={new Date(deployment.started_at).toLocaleString()} />
        <MetaField
          label="Finished"
          value={deployment.finished_at ? new Date(deployment.finished_at).toLocaleString() : 'in progress'}
        />
      </div>
    </div>
  )
}

function MetaField({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="text-text">{value ?? '—'}</div>
    </div>
  )
}
