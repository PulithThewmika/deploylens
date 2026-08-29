import { MessageBubble } from './MessageBubble'
import type { ChatMessage, MessagePart } from '../../types/chat'

type ChatWindowProps = {
  messages: ChatMessage[]
  isStreaming?: boolean
}

export function ChatWindow({ messages, isStreaming = false }: ChatWindowProps) {
  const lastMessage = messages[messages.length - 1]
  const awaitingFirstToken =
    isStreaming && lastMessage?.role === 'assistant' && !lastMessage.parts.some(hasVisibleContent)

  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      {awaitingFirstToken && <TypingIndicator />}
    </div>
  )
}

function hasVisibleContent(part: MessagePart): boolean {
  return part.type !== 'text' || part.text.length > 0
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-lg border border-border bg-surface px-3 py-2">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted [animation-delay:-0.3s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted" />
      </div>
    </div>
  )
}
