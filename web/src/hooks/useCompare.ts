import { useQuery } from '@tanstack/react-query'
import type { CompareResult } from '../types/compare'

async function fetchCompare(idA: number, idB: number): Promise<CompareResult> {
  const res = await fetch(`/api/compare?a=${idA}&b=${idB}`)
  if (!res.ok) {
    throw new Error(`Failed to fetch comparison: ${res.status}`)
  }
  return res.json()
}

export function useCompare(idA: number | null, idB: number | null) {
  return useQuery({
    queryKey: ['compare', idA, idB],
    queryFn: () => fetchCompare(idA as number, idB as number),
    enabled: idA !== null && idB !== null,
  })
}
