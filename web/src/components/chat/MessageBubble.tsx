import { ToolCallChip } from './ToolCallChip'
import type { ChatMessage } from '../../types/chat'

type MessageBubbleProps = {
  message: ChatMessage
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg bg-accent/10 px-3 py-2 text-sm text-text">{message.content}</div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="flex max-w-[80%] flex-col gap-2">
        {message.parts.map((part, i) =>
          part.type === 'text' ? (
            part.text.length > 0 && (
              <div key={i} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text">
                {part.text}
              </div>
            )
          ) : (
            <ToolCallChip
              key={i}
              tool={part.tool}
              input={part.input}
              result={part.result}
              isError={part.is_error}
            />
          ),
        )}
      </div>
    </div>
  )
}
