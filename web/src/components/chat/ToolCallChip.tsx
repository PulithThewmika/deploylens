import { useState } from 'react'

type ToolCallChipProps = {
  tool: string
  input: unknown
  result: string
  isError: boolean
}

export function ToolCallChip({ tool, input, result, isError }: ToolCallChipProps) {
  const [expanded, setExpanded] = useState(false)
  const summary = result.length > 80 ? `${result.slice(0, 80)}…` : result

  return (
    <div
      className={`rounded-lg border text-xs ${isError ? 'border-failed/40 bg-failed/5' : 'border-border bg-surface'}`}
    >
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={expanded}
      >
        <span className={`font-mono ${isError ? 'text-failed' : 'text-accent'}`}>{tool}</span>
        <span className="truncate text-text-muted">{summary}</span>
        <span className="ml-auto shrink-0 text-text-muted">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="border-t border-border px-3 py-2">
          <div className="mb-1 text-text-muted">Input</div>
          <pre className="mb-2 overflow-x-auto whitespace-pre-wrap break-words text-text">
            {JSON.stringify(input, null, 2)}
          </pre>
          <div className="mb-1 text-text-muted">Result</div>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-text">{result}</pre>
        </div>
      )}
    </div>
  )
}
