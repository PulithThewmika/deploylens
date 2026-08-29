export type DORAMetrics = {
  deploy_frequency_per_day: number | null
  lead_time_avg_s: number | null
  change_failure_rate: number | null
  mttr_s: number | null
  period: string
  service: string | null
}
