import { useEffect, useState } from 'react'

const VERDICT_COLORS: Record<string, string> = {
  healthy: '#22C55E',
  degraded: '#F59E0B',
  failed: '#EF4444',
}

const TRACK_COLOR = '#26262E'

type HealthRingProps = {
  score: number | null
  verdict: string | null
  size?: number
}

export function HealthRing({ score, verdict, size = 56 }: HealthRingProps) {
  const strokeWidth = Math.max(3, Math.round(size / 12))
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const isUnknown = score === null
  const clampedScore = Math.min(100, Math.max(0, score ?? 0))
  const targetOffset = isUnknown ? 0 : circumference * (1 - clampedScore / 100)
  const color = isUnknown ? '#4B5563' : (verdict && VERDICT_COLORS[verdict]) ?? TRACK_COLOR

  const [swept, setSwept] = useState(false)
  useEffect(() => {
    const frame = requestAnimationFrame(() => setSwept(true))
    return () => cancelAnimationFrame(frame)
  }, [])

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={TRACK_COLOR}
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={swept ? targetOffset : circumference}
          style={{ transition: 'stroke-dashoffset 0.5s ease-out' }}
        />
      </svg>
      <span
        className={`absolute font-heading font-medium tabular-nums ${isUnknown ? 'text-text-muted' : 'text-text'}`}
        style={{ fontSize: size * 0.32 }}
      >
        {isUnknown ? '—' : Math.round(clampedScore)}
      </span>
    </div>
  )
}
