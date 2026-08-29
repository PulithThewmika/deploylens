import { MessageBubble } from './MessageBubble'
import type { ChatMessage } from '../../types/chat'

type ChatWindowProps = {
  messages: ChatMessage[]
}

export function ChatWindow({ messages }: ChatWindowProps) {
  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
    </div>
  )
}
