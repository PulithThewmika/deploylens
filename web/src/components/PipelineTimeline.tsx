import type { Deployment } from '../types/deployment'

type PipelineTimelineProps = {
  deployments: Deployment[]
}

export function PipelineTimeline({ deployments }: PipelineTimelineProps) {
  const last10 = deployments.slice(0, 10)

  return (
    <div className="flex flex-col gap-2">
      {last10.map((deployment) => (
        <div key={deployment.id}>{deployment.id}</div>
      ))}
    </div>
  )
}
