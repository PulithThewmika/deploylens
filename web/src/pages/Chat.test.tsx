import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Chat } from './Chat'

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  })
  return new Response(stream, { status: 200 })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Chat page', () => {
  it('disables the input while streaming and re-enables it once the response finishes', async () => {
    let resolveFetch!: (res: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn().mockReturnValue(new Promise<Response>((resolve) => (resolveFetch = resolve))),
    )

    render(<Chat />)
    const input = screen.getByPlaceholderText(/ask about/i)
    fireEvent.change(input, { target: { value: 'What deployed today?' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() => expect(input).toBeDisabled())

    resolveFetch(sseResponse(['event: text\ndata: {"text":"Nothing today."}\n\n']))

    await waitFor(() => expect(input).not.toBeDisabled())
    expect(screen.getByText('Nothing today.')).toBeInTheDocument()
  })

  it('shows an error banner when the chat service is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })))

    render(<Chat />)
    const input = screen.getByPlaceholderText(/ask about/i)
    fireEvent.change(input, { target: { value: 'hello' } })
    fireEvent.submit(input.closest('form')!)

    expect(await screen.findByText('Unable to reach the chat service.')).toBeInTheDocument()
  })

  it('populates the input when a suggested prompt chip is clicked, without sending it', () => {
    vi.stubGlobal('fetch', vi.fn())
    render(<Chat />)

    fireEvent.click(screen.getByText('What deployed today?'))

    expect(screen.getByPlaceholderText(/ask about/i)).toHaveValue('What deployed today?')
    expect(fetch).not.toHaveBeenCalled()
  })
})
