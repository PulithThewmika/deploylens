import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChatSession } from './useChatSession'

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

describe('useChatSession', () => {
  it('appends a user message immediately and streams text into a new assistant message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse([
          'event: text\ndata: {"text":"The "}\n\n',
          'event: text\ndata: {"text":"deploy is healthy."}\n\n',
        ]),
      ),
    )

    const { result } = renderHook(() => useChatSession())

    await act(async () => {
      await result.current.sendMessage('Is the deploy healthy?')
    })

    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false)
    })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0]).toMatchObject({ role: 'user', content: 'Is the deploy healthy?' })
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      parts: [{ type: 'text', text: 'The deploy is healthy.' }],
    })
  })

  it('renders a tool_call event as its own part, not merged with text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse([
          'event: text\ndata: {"text":"Checking."}\n\n',
          'event: tool_call\ndata: {"tool":"list_deployments","input":{},"result":"2 found","is_error":false}\n\n',
          'event: text\ndata: {"text":"Both are healthy."}\n\n',
        ]),
      ),
    )

    const { result } = renderHook(() => useChatSession())
    await act(async () => {
      await result.current.sendMessage('status?')
    })

    const assistant = result.current.messages[1]
    expect(assistant.role).toBe('assistant')
    if (assistant.role === 'assistant') {
      expect(assistant.parts).toEqual([
        { type: 'text', text: 'Checking.' },
        { type: 'tool_call', tool: 'list_deployments', input: {}, result: '2 found', is_error: false },
        { type: 'text', text: 'Both are healthy.' },
      ])
    }
  })

  it('sends the full message history (flattened to plain text) on the second turn', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sseResponse(['event: text\ndata: {"text":"First answer."}\n\n']))
      .mockResolvedValueOnce(sseResponse(['event: text\ndata: {"text":"Second answer."}\n\n']))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChatSession())
    await act(async () => {
      await result.current.sendMessage('first question')
    })
    await act(async () => {
      await result.current.sendMessage('second question')
    })

    const secondCallBody = JSON.parse(fetchMock.mock.calls[1][1].body)
    expect(secondCallBody.messages).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'assistant', content: 'First answer.' },
      { role: 'user', content: 'second question' },
    ])
  })

  it('does not drop the first message when sendMessage is called twice before the first one commits', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(['event: text\ndata: {"text":"ok"}\n\n'])))

    const { result } = renderHook(() => useChatSession())

    await act(async () => {
      await Promise.all([result.current.sendMessage('first'), result.current.sendMessage('second')])
    })

    const userMessages = result.current.messages.filter((m) => m.role === 'user')
    expect(userMessages.map((m) => m.content)).toEqual(['first', 'second'])
  })

  it('sets an error and stops streaming when the initial fetch is not ok', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })))

    const { result } = renderHook(() => useChatSession())
    await act(async () => {
      await result.current.sendMessage('hello')
    })

    expect(result.current.error).toBe('Unable to reach the chat service.')
    expect(result.current.isStreaming).toBe(false)
  })

  it('sets an error from an event: error frame mid-stream', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(sseResponse(['event: error\ndata: {"error":"LLM service unavailable"}\n\n'])),
    )

    const { result } = renderHook(() => useChatSession())
    await act(async () => {
      await result.current.sendMessage('hello')
    })

    expect(result.current.error).toBe('LLM service unavailable')
  })
})
