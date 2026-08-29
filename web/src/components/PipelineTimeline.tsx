import { calcStageDurations } from '../lib/timeline'
import type { Deployment, TimelineStage } from '../types/deployment'

type PipelineTimelineProps = {
  deployments: Deployment[]
}

export function PipelineTimeline({ deployments }: PipelineTimelineProps) {
  const last10 = deployments.slice(0, 10)

  return (
    <div className="flex flex-col gap-2">
      {last10.map((deployment) => (
        <PipelineRow key={deployment.id} deployment={deployment} />
      ))}
    </div>
  )
}

type PipelineRowProps = {
  deployment: Deployment
}

function PipelineRow({ deployment }: PipelineRowProps) {
  const shortSha = deployment.commit_sha ? deployment.commit_sha.slice(0, 7) : deployment.status
  const durationsS = calcStageDurations(deployment.timeline)

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-surface p-3">
      <span className="w-24 shrink-0 truncate font-heading text-sm text-text-muted">{shortSha}</span>
      <div className="flex h-6 flex-1 gap-0.5 overflow-hidden rounded">
        {deployment.timeline.map((stage, i) => (
          <PipelineStage key={stage.stage} stage={stage} durationS={durationsS[i]} />
        ))}
      </div>
    </div>
  )
}

type PipelineStageProps = {
  stage: TimelineStage
  durationS: number
}

function PipelineStage({ stage, durationS }: PipelineStageProps) {
  return <div className="h-full flex-1 bg-border" title={`${stage.stage} (${durationS}s)`} />
}
