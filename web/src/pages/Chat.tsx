import { useState } from 'react'
import { ChatWindow } from '../components/chat/ChatWindow'
import { useChatSession } from '../hooks/useChatSession'

export function Chat() {
  const { messages, isStreaming, error, sendMessage } = useChatSession()
  const [input, setInput] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = input.trim()
    if (!trimmed || isStreaming) return
    setInput('')
    void sendMessage(trimmed)
  }

  return (
    <div className="flex h-full flex-col">
      {error && <div className="border-b border-failed/40 bg-failed/10 px-4 py-2 text-sm text-failed">{error}</div>}
      <ChatWindow messages={messages} />
      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-border p-4">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={isStreaming}
          placeholder="Ask about a deployment, service, or incident…"
          className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-muted disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={isStreaming || !input.trim()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  )
}
