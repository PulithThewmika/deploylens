import { useQuery } from '@tanstack/react-query'
import type { Service } from '../types/service'

async function fetchServices(): Promise<Service[]> {
  const res = await fetch('/api/services')
  if (!res.ok) {
    throw new Error(`Failed to fetch services: ${res.status}`)
  }
  return res.json()
}

export function useServices() {
  return useQuery({
    queryKey: ['services'],
    queryFn: fetchServices,
    refetchInterval: 30_000,
  })
}
