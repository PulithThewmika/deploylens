import { useQuery } from '@tanstack/react-query'
import type { DORAMetrics } from '../types/dora'

async function fetchDORA(service: string): Promise<DORAMetrics> {
  const res = await fetch(`/api/dora?service=${encodeURIComponent(service)}`)
  if (!res.ok) {
    throw new Error(`Failed to fetch DORA metrics: ${res.status}`)
  }
  return res.json()
}

export function useDORA(service: string) {
  return useQuery({
    queryKey: ['dora', service],
    queryFn: () => fetchDORA(service),
    enabled: Boolean(service),
  })
}
