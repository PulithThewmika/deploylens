import { useParams } from 'react-router-dom'
import { useDeployment } from '../hooks/useDeployment'

export function DeployDetail() {
  const { id } = useParams<{ id: string }>()
  const deployId = Number(id)
  const { data: deployment } = useDeployment(deployId)

  return (
    <div className="p-6">
      <h1 className="font-heading text-xl font-semibold text-text">
        Deployment {deployment?.commit_sha?.slice(0, 7) ?? id}
      </h1>
    </div>
  )
}
