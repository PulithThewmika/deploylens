import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import '@testing-library/jest-dom/vitest'

// jsdom doesn't implement ResizeObserver; components (e.g. PipelineTimeline's
// useElementWidth) that rely on it need a stub or every render test crashes.
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

afterEach(cleanup)
