import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HealthEvidenceTable } from './HealthEvidenceTable'
import type { HealthEvidenceItem } from '../types/deploymentDetail'

describe('HealthEvidenceTable', () => {
  it('colors a decrease (improvement) green and an increase (degradation) red', () => {
    const evidence: HealthEvidenceItem[] = [
      { metric: 'error_rate', baseline: 0.05, post: 0.02, change_pct: -60 },
      { metric: 'latency_p99', baseline: 100, post: 150, change_pct: 50 },
    ]
    render(<HealthEvidenceTable evidence={evidence} />)
    expect(screen.getByText('-60%')).toHaveClass('text-healthy')
    expect(screen.getByText('+50%')).toHaveClass('text-failed')
  })

  it('renders friendly metric labels', () => {
    const evidence: HealthEvidenceItem[] = [{ metric: 'restarts', baseline: 0, post: 0, change_pct: null }]
    render(<HealthEvidenceTable evidence={evidence} />)
    expect(screen.getByText('Restarts')).toBeInTheDocument()
  })
})
