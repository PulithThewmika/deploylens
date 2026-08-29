export type SSEEvent = {
  event: string
  data: string
}

/** Parses a `text/event-stream` body into `event`/`data` frames (`event: X\ndata: Y\n\n`), matching services/ingest/app/chat_engine.py's sse() helper. */
export async function* parseSSEStream(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let sepIndex = buffer.indexOf('\n\n')
      while (sepIndex !== -1) {
        const frame = buffer.slice(0, sepIndex)
        buffer = buffer.slice(sepIndex + 2)
        const parsed = parseFrame(frame)
        if (parsed) yield parsed
        sepIndex = buffer.indexOf('\n\n')
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseFrame(frame: string): SSEEvent | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trim())
    }
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}
