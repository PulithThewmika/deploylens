import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ToolCallChip } from './ToolCallChip'

describe('ToolCallChip', () => {
  it('starts collapsed and expands on click to show input and result', () => {
    render(
      <ToolCallChip tool="list_deployments" input={{ service: 'orders' }} result="3 deployments found" isError={false} />,
    )
    expect(screen.queryByText('Input')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button'))

    expect(screen.getByText('Input')).toBeInTheDocument()
    expect(screen.getAllByText('3 deployments found').length).toBeGreaterThan(0)
  })

  it('renders error styling for a failed tool call', () => {
    render(<ToolCallChip tool="get_dora_metrics" input={{}} result="MCP server unavailable" isError={true} />)
    expect(screen.getByText('get_dora_metrics')).toHaveClass('text-failed')
  })
})
