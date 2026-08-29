import { describe, expect, it } from 'vitest'
import { parseSSEStream } from './sse'

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let i = 0
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]))
        i++
      } else {
        controller.close()
      }
    },
  })
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const events = []
  for await (const evt of parseSSEStream(stream)) {
    events.push(evt)
  }
  return events
}

describe('parseSSEStream', () => {
  it('parses a single complete frame', async () => {
    const stream = streamFrom(['event: text\ndata: {"text":"hi"}\n\n'])
    expect(await collect(stream)).toEqual([{ event: 'text', data: '{"text":"hi"}' }])
  })

  it('parses multiple frames arriving in one chunk', async () => {
    const stream = streamFrom([
      'event: text\ndata: {"text":"a"}\n\nevent: text\ndata: {"text":"b"}\n\n',
    ])
    expect(await collect(stream)).toEqual([
      { event: 'text', data: '{"text":"a"}' },
      { event: 'text', data: '{"text":"b"}' },
    ])
  })

  it('reassembles a frame split across multiple chunks', async () => {
    const stream = streamFrom(['event: too', 'l_call\ndata: {"to', 'ol":"list_deployments"}\n\n'])
    expect(await collect(stream)).toEqual([{ event: 'tool_call', data: '{"tool":"list_deployments"}' }])
  })

  it('ignores a frame with no data line', async () => {
    const stream = streamFrom([': keepalive\n\nevent: text\ndata: {"text":"hi"}\n\n'])
    expect(await collect(stream)).toEqual([{ event: 'text', data: '{"text":"hi"}' }])
  })
})
