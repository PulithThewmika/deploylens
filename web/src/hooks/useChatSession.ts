import { useState } from 'react'
import { parseSSEStream } from '../lib/sse'
import type { ChatMessage, ChatRequestMessage } from '../types/chat'

function toWireFormat(messages: ChatMessage[]): ChatRequestMessage[] {
  return messages.map((m) =>
    m.role === 'user'
      ? { role: 'user', content: m.content }
      : {
          role: 'assistant',
          content: m.parts
            .filter((p) => p.type === 'text')
            .map((p) => p.text)
            .join(''),
        },
  )
}

function appendText(messages: ChatMessage[], assistantId: string, text: string): ChatMessage[] {
  return messages.map((m) => {
    if (m.id !== assistantId || m.role !== 'assistant') return m
    const lastPart = m.parts[m.parts.length - 1]
    if (lastPart?.type === 'text') {
      return { ...m, parts: [...m.parts.slice(0, -1), { type: 'text', text: lastPart.text + text }] }
    }
    return { ...m, parts: [...m.parts, { type: 'text', text }] }
  })
}

function appendToolCall(
  messages: ChatMessage[],
  assistantId: string,
  data: { tool: string; input: unknown; result: string; is_error: boolean },
): ChatMessage[] {
  return messages.map((m) => {
    if (m.id !== assistantId || m.role !== 'assistant') return m
    return {
      ...m,
      parts: [
        ...m.parts,
        { type: 'tool_call', tool: data.tool, input: data.input, result: data.result, is_error: data.is_error },
      ],
    }
  })
}

export function useChatSession() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function sendMessage(content: string) {
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: 'user', content }
    const historyForRequest = [...messages, userMessage]
    const assistantId = crypto.randomUUID()

    setMessages([...historyForRequest, { id: assistantId, role: 'assistant', parts: [] }])
    setError(null)
    setIsStreaming(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: toWireFormat(historyForRequest) }),
      })

      if (!res.ok || !res.body) {
        setError('Unable to reach the chat service.')
        return
      }

      for await (const evt of parseSSEStream(res.body)) {
        const data = JSON.parse(evt.data)
        if (evt.event === 'text') {
          setMessages((prev) => appendText(prev, assistantId, data.text))
        } else if (evt.event === 'tool_call') {
          setMessages((prev) => appendToolCall(prev, assistantId, data))
        } else if (evt.event === 'error') {
          setError(data.error)
        }
      }
    } catch {
      setError('Connection to the chat service was lost.')
    } finally {
      setIsStreaming(false)
    }
  }

  return { messages, isStreaming, error, sendMessage }
}
