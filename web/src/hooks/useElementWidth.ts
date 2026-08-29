import { useEffect, useRef, useState } from 'react'

/** Tracks an element's rendered width so layout-dependent content (e.g. text that only fits in wide segments) can react to it. */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return { ref, width }
}
