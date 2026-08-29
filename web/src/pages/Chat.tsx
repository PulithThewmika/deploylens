import { useState } from 'react'
import { ChatWindow } from '../components/chat/ChatWindow'
import type { ChatMessage } from '../types/chat'

export function Chat() {
  const [messages] = useState<ChatMessage[]>([])

  return (
    <div className="flex h-full flex-col">
      <ChatWindow messages={messages} />
    </div>
  )
}
