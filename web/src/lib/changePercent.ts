/** Shared coloring/formatting for a metric's percent change, used by DeployDiffTable and HealthEvidenceTable. A decrease is an improvement (green); an increase is a degradation (red). */
export function changePercentColorClass(changePct: number | null): string {
  if (changePct === null) return 'text-text-muted'
  if (changePct < 0) return 'text-healthy'
  if (changePct > 0) return 'text-failed'
  return 'text-text-muted'
}

export function formatChangePercent(changePct: number | null): string {
  if (changePct === null) return '—'
  const sign = changePct > 0 ? '+' : ''
  return `${sign}${changePct}%`
}
