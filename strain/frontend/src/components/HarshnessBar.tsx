

interface HarshnessBarProps {
  score: number | null
  showLabel?: boolean
  compact?: boolean
}

import { riskLevel, RISK_LABEL } from '../api'

export function HarshnessBar({ score, showLabel = true, compact = false }: HarshnessBarProps) {
  if (score === null || score === undefined) {
    return <span style={{ color: 'var(--color-text-faint)', fontSize: 12 }}>—</span>
  }

  const pct = Math.min(100, Math.max(0, score))
  const risk = riskLevel(pct)!
  const level = risk === 'moderate' ? 'medium' : risk

  const levelLabel = RISK_LABEL[risk]

  const levelColor = {
    critical: 'var(--color-danger)',
    high: '#e86a1d',
    medium: 'var(--color-warning)',
    low: 'var(--color-success)',
  }[level]

  if (compact) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div className="harshness-bar-track" style={{ width: 80 }}>
          <div
            className={`harshness-bar-fill ${level}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span style={{ fontSize: 11, fontWeight: 700, color: levelColor }}>
          {Math.round(pct)}
        </span>
      </div>
    )
  }

  return (
    <div>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 8,
      }}>
        {showLabel && (
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-muted)' }}>
            Risk Score
          </span>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            fontSize: 22,
            fontWeight: 800,
            color: levelColor,
            letterSpacing: '-0.5px',
          }}>
            {Math.round(pct)}
          </span>
          <span style={{
            fontSize: 11,
            fontWeight: 700,
            color: levelColor,
            background: `${levelColor}18`,
            border: `1px solid ${levelColor}30`,
            padding: '2px 8px',
            borderRadius: 12,
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
          }}>
            {levelLabel}
          </span>
        </div>
      </div>
      <div className="harshness-bar-track">
        <div
          className={`harshness-bar-fill ${level}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
