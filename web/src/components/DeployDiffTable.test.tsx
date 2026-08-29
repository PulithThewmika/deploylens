import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DeployDiffTable } from './DeployDiffTable'
import type { CompareMetric } from '../types/compare'

describe('DeployDiffTable', () => {
  it('colors a decrease (improvement) green', () => {
    const metrics: CompareMetric[] = [
      { metric: 'error_rate', deploy_a: 0.05, deploy_b: 0.02, change_pct: -60 },
    ]
    render(<DeployDiffTable metrics={metrics} />)
    expect(screen.getByText('-60%')).toHaveClass('text-healthy')
  })

  it('colors an increase (degradation) red', () => {
    const metrics: CompareMetric[] = [
      { metric: 'latency_p99', deploy_a: 100, deploy_b: 150, change_pct: 50 },
    ]
    render(<DeployDiffTable metrics={metrics} />)
    expect(screen.getByText('+50%')).toHaveClass('text-failed')
  })

  it('renders an em dash with muted color when change_pct is unavailable', () => {
    const metrics: CompareMetric[] = [{ metric: 'restarts', deploy_a: null, deploy_b: null, change_pct: null }]
    render(<DeployDiffTable metrics={metrics} />)
    const cells = screen.getAllByText('—')
    expect(cells.some((el) => el.className.includes('text-text-muted'))).toBe(true)
  })
})
