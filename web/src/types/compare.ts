export type CompareMetric = {
  metric: string
  deploy_a: number | null
  deploy_b: number | null
  change_pct: number | null
}

export type CompareResult = {
  deploy_a_id: number
  deploy_b_id: number
  service: string
  metrics: CompareMetric[]
}
