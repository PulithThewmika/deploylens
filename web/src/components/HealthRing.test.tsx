import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HealthRing } from './HealthRing'

describe('HealthRing', () => {
  it('renders a score of 0 as a fully-offset arc', () => {
    render(<HealthRing score={0} verdict="failed" />)
    expect(screen.getByText('0')).toBeInTheDocument()
  })

  it('renders a score of 50', () => {
    render(<HealthRing score={50} verdict="degraded" />)
    expect(screen.getByText('50')).toBeInTheDocument()
  })

  it('renders a score of 100 as a fully-drawn ring', () => {
    render(<HealthRing score={100} verdict="healthy" />)
    expect(screen.getByText('100')).toBeInTheDocument()
  })

  it('renders a null score as a grey ring with an em-dash', () => {
    render(<HealthRing score={null} verdict={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
})
