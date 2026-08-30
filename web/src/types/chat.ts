export type MessagePart =
  | { type: 'text'; text: string }
  | { type: 'tool_call'; tool: string; input: unknown; result: string; is_error: boolean }

export type ChatMessage =
  | { id: string; role: 'user'; content: string }
  | { id: string; role: 'assistant'; parts: MessagePart[] }

/** Wire format for POST /api/chat — the backend only accepts plain string content. */
export type ChatRequestMessage = {
  role: 'user' | 'assistant'
  content: string
}
