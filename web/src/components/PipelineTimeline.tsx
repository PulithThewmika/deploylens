import {
  calcStageDurations,
  fillIncompleteTimeline,
  formatDuration,
  normalizeStageStatus,
  stageLabel,
  STAGE_STATUS_COLORS,
} from '../lib/timeline'
import { useElementWidth } from '../hooks/useElementWidth'
import { useEffect, useState } from 'react'
import type { Deployment, TimelineStage } from '../types/deployment'

type PipelineSize = 'compact' | 'large'

type PipelineTimelineProps = {
  deployments: Deployment[]
  size?: PipelineSize
}

export function PipelineTimeline({ deployments, size = 'compact' }: PipelineTimelineProps) {
  const last10 = [...deployments]
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
    .slice(0, 10)

  return (
    <div className="flex flex-col gap-2">
      {last10.map((deployment) => (
        <PipelineRow key={deployment.id} deployment={deployment} size={size} />
      ))}
    </div>
  )
}

type PipelineRowProps = {
  deployment: Deployment
  size: PipelineSize
}

function PipelineRow({ deployment, size }: PipelineRowProps) {
  const shortSha = deployment.commit_sha ? deployment.commit_sha.slice(0, 7) : deployment.status
  const timeline = fillIncompleteTimeline(deployment.timeline)
  const durationsS = calcStageDurations(timeline)
  const trackHeight = size === 'large' ? 'h-12' : 'h-6'

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-surface p-3">
      <span className="w-24 shrink-0 truncate font-heading text-sm text-text-muted">{shortSha}</span>
      <div className={`flex ${trackHeight} flex-1 gap-0.5 overflow-hidden rounded`}>
        {timeline.map((stage, i) => (
          <PipelineStage key={stage.stage} stage={stage} durationS={durationsS[i]} size={size} />
        ))}
      </div>
    </div>
  )
}

type PipelineStageProps = {
  stage: TimelineStage
  durationS: number
  size: PipelineSize
}

const MIN_SEGMENT_WEIGHT_S = 10
const MIN_SEGMENT_WIDTH_PX = 24

const MIN_WIDTH_FOR_TEXT_PX = 44

function PipelineStage({ stage, durationS, size }: PipelineStageProps) {
  const flexGrow = Math.max(durationS, MIN_SEGMENT_WEIGHT_S)
  const status = normalizeStageStatus(stage.status)
  const timestamp = stage.at ? new Date(stage.at).toLocaleString() : 'not yet reached'
  const { ref, width } = useElementWidth<HTMLDivElement>()
  const showDurationText = durationS > 0 && width >= MIN_WIDTH_FOR_TEXT_PX
  const textSize = size === 'large' ? 'text-xs' : 'text-[10px]'

  const [filled, setFilled] = useState(false)
  useEffect(() => {
    const frame = requestAnimationFrame(() => setFilled(true))
    return () => cancelAnimationFrame(frame)
  }, [])

  return (
    <div
      ref={ref}
      className="group relative h-full"
      style={{ flexGrow, flexBasis: 0, minWidth: MIN_SEGMENT_WIDTH_PX }}
    >
      <div
        className={`flex h-full w-full items-center justify-center overflow-hidden ${status === 'in-progress' ? 'animate-pulse' : ''}`}
        style={{
          backgroundColor: STAGE_STATUS_COLORS[status],
          transform: filled ? 'scaleX(1)' : 'scaleX(0)',
          transformOrigin: 'left',
          transition: 'transform 0.4s ease-out',
        }}
      >
        {showDurationText && (
          <span className={`truncate px-1 ${textSize} font-medium text-black/70`}>
            {formatDuration(durationS)}
          </span>
        )}
      </div>
      <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 hidden -translate-x-1/2 whitespace-nowrap rounded border border-border bg-surface px-2 py-1 text-xs text-text shadow-lg group-hover:block">
        <div className="font-medium">{stageLabel(stage.stage)}</div>
        <div className="text-text-muted">{timestamp}</div>
      </div>
    </div>
  )
}
