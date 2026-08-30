import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MessageBubble } from './MessageBubble'
import type { ChatMessage } from '../../types/chat'

describe('MessageBubble', () => {
  it('renders a user message right-aligned', () => {
    const message: ChatMessage = { id: '1', role: 'user', content: 'What deployed today?' }
    render(<MessageBubble message={message} />)
    expect(screen.getByText('What deployed today?').closest('div')?.parentElement).toHaveClass('justify-end')
  })

  it('renders interleaved text and tool_call parts in order', () => {
    const message: ChatMessage = {
      id: '2',
      role: 'assistant',
      parts: [
        { type: 'text', text: 'Let me check.' },
        { type: 'tool_call', tool: 'list_deployments', input: {}, result: '2 deploys', is_error: false },
        { type: 'text', text: 'Both deploys are healthy.' },
      ],
    }
    render(<MessageBubble message={message} />)
    expect(screen.getByText('Let me check.')).toBeInTheDocument()
    expect(screen.getByText('list_deployments')).toBeInTheDocument()
    expect(screen.getByText('Both deploys are healthy.')).toBeInTheDocument()
  })

  it('does not render an empty box for a text part with no text yet', () => {
    const message: ChatMessage = { id: '3', role: 'assistant', parts: [{ type: 'text', text: '' }] }
    const { container } = render(<MessageBubble message={message} />)
    expect(container.querySelectorAll('.bg-surface').length).toBe(0)
  })
})
