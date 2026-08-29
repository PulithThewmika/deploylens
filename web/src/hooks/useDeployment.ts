import { useQuery } from '@tanstack/react-query'
import type { DeploymentDetail } from '../types/deploymentDetail'

async function fetchDeployment(id: number): Promise<DeploymentDetail> {
  const res = await fetch(`/api/deployments/${id}`)
  if (!res.ok) {
    throw new Error(`Failed to fetch deployment: ${res.status}`)
  }
  return res.json()
}

export function useDeployment(id: number) {
  return useQuery({
    queryKey: ['deployment', id],
    queryFn: () => fetchDeployment(id),
    enabled: Number.isFinite(id),
  })
}
