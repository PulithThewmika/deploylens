import { useQuery } from '@tanstack/react-query'
import type { Deployment } from '../types/deployment'

async function fetchDeployments(service: string): Promise<Deployment[]> {
  const res = await fetch(`/api/deployments?service=${encodeURIComponent(service)}&limit=10`)
  if (!res.ok) {
    throw new Error(`Failed to fetch deployments: ${res.status}`)
  }
  return res.json()
}

export function useDeployments(service: string) {
  return useQuery({
    queryKey: ['deployments', service],
    queryFn: () => fetchDeployments(service),
    enabled: Boolean(service),
    refetchInterval: 30_000,
  })
}
