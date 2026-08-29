import { useParams } from 'react-router-dom'
import { useDeployments } from '../hooks/useDeployments'
import { useDORA } from '../hooks/useDORA'

export function ServiceDeepDive() {
  const { name = '' } = useParams<{ name: string }>()
  const { data: deployments, isLoading: deploymentsLoading } = useDeployments(name)
  const { data: dora } = useDORA(name)

  return (
    <div className="p-6">
      <h1 className="font-heading text-xl font-semibold text-text">{name}</h1>
      {!deploymentsLoading && <p className="text-sm text-text-muted">{deployments?.length ?? 0} deployments loaded</p>}
      {dora && <p className="text-sm text-text-muted">DORA period: {dora.period}</p>}
    </div>
  )
}
