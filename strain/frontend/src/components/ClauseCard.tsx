import { useState } from 'react'
import type { DiagnosisClause, OutcomeRecord } from '../api'
import { riskLevel } from '../api'
import { HarshnessBar } from './HarshnessBar'
import { WordDiff } from './WordDiff'

interface ClauseCardProps {
  clause: DiagnosisClause
  index: number
}

export function ClauseCard({ clause, index }: ClauseCardProps) {
  const [expanded, setExpanded] = useState(index === 0)
  // High-risk clauses lead with their lower-risk alternative visible:
  // the product's core value proposition stays unmissable.
  const prominent = (clause.virulence_score ?? 0) >= 60 && clause.neutralising_wording !== null
  const [showNeutralising, setShowNeutralising] = useState(prominent)

  const level = riskLevel(clause.virulence_score)
  const riskClass =
    level === 'critical' || level === 'high'
      ? 'high-risk'
      : level === 'moderate'
      ? 'medium-risk'
      : ''

  return (
    <div className={`clause-card ${riskClass} animate-in`}
      style={{ animationDelay: `${index * 0.04}s` }}
      id={`clause-${clause.clause_id}`}
    >
      {/* Header */}
      <div
        style={{
          padding: '14px 18px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          cursor: 'pointer',
          borderBottom: expanded ? '1px solid var(--color-border)' : 'none',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        {/* Ordinal badge */}
        <div style={{
          width: 28,
          height: 28,
          borderRadius: '50%',
          background: 'var(--color-surface-3)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 11,
          fontWeight: 700,
          color: 'var(--color-text-muted)',
          flexShrink: 0,
        }}>
          {index + 1}
        </div>

        {/* Clause info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>
              {clause.heading || `Clause ${clause.ordinal + 1}`}
            </span>
            {clause.family_name && (
              <span className="strain-tag">{clause.family_name}</span>
            )}
            {clause.status === 'unclassified' && (
              <span className="badge" style={{
                background: 'rgba(100,116,139,0.15)',
                color: '#94a3b8',
                border: '1px solid rgba(100,116,139,0.3)',
              }}>
                Unclassified
              </span>
            )}
            {clause.is_provisional_leaf && (
              <span className="badge badge-accent" style={{ fontSize: 10 }}>
                Your Document
              </span>
            )}
            {clause.is_preamble && (
              <span className="badge" style={{
                fontSize: 10,
                background: 'var(--card)',
                color: 'var(--color-text-muted)',
                border: '2px solid var(--color-text-faint)',
              }}>
                Preamble
              </span>
            )}
            {clause.is_compound && (
              <span className="badge" style={{
                fontSize: 10,
                background: '#fff3cf',
                color: 'var(--ink-deep)',
                border: '2px solid var(--ink)',
              }} title={`Covers multiple topics: ${(clause.topics || []).join(', ')}`}>
                Compound §
              </span>
            )}
          </div>
          {(clause.topics || []).length > 1 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
              {(clause.topics || []).map(t => (
                <span key={t} style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--color-text-muted)',
                  background: 'rgba(32,38,168,0.07)',
                  border: '1px solid rgba(32,38,168,0.25)',
                  borderRadius: 4,
                  padding: '0 6px',
                }}>
                  {t}
                </span>
              ))}
            </div>
          )}
          <div style={{
            fontSize: 12,
            color: 'var(--color-text-muted)',
            marginTop: 2,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {clause.text.slice(0, 100)}…
          </div>
        </div>

        {/* Score */}
        <div style={{ flexShrink: 0, textAlign: 'right', minWidth: 80 }}>
          <HarshnessBar score={clause.virulence_score} showLabel={false} compact />
        </div>

        <span style={{
          color: 'var(--color-text-faint)',
          fontSize: 12,
          flexShrink: 0,
          transition: 'transform 0.15s',
          transform: expanded ? 'rotate(90deg)' : 'none',
        }}>›</span>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div style={{ padding: '18px 18px 0' }}>
          {/* Unclassified message */}
          {clause.status === 'unclassified' && clause.unclassified_message && (
            <div style={{
              background: 'rgba(100,116,139,0.1)',
              border: '1px solid rgba(100,116,139,0.2)',
              borderRadius: 8,
              padding: '10px 14px',
              fontSize: 13,
              color: '#94a3b8',
              marginBottom: 16,
            }}>
              ℹ️ {clause.unclassified_message}
            </div>
          )}

          {/* Virulence breakdown */}
          {clause.virulence_score !== null && (
            <div style={{ marginBottom: 20 }}>
              <HarshnessBar score={clause.virulence_score} />

              {clause.virulence_components && (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, 1fr)',
                  gap: 8,
                  marginTop: 12,
                }}>
                  {[
                    { label: 'Asymmetry', value: clause.virulence_components.asymmetry, key: 'asymmetry' },
                    { label: 'Harshness Δ', value: clause.virulence_components.harshness_delta, key: 'harshness_delta' },
                    { label: 'Outcome Risk', value: clause.virulence_components.outcome_factor, key: 'outcome_factor' },
                  ].map(({ label, value, key }) => (
                    <div key={key} style={{
                      background: 'var(--color-surface-2)',
                      borderRadius: 8,
                      padding: '10px 12px',
                      textAlign: 'center',
                    }}>
                      <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.5px' }}>
                        {Math.round(value)}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        {label}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--color-text-faint)', marginTop: 1 }}>
                        weight {Math.round((clause.virulence_components!.weights[key] || 0) * 100)}%
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Clause text */}
          <div style={{ marginBottom: 16 }}>
            <div className="section-heading">Clause Text</div>
            <div className="clause-text" style={{
              background: 'var(--color-surface-2)',
              borderRadius: 8,
              padding: '12px 14px',
            }}>
              {clause.text}
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-faint)', marginTop: 4 }}>
              Source: {clause.doc_id} — {clause.clause_id}
            </div>
          </div>

          {/* Litigation history */}
          <div style={{ marginBottom: 16 }}>
            <div className="section-heading">Litigation History</div>
            {clause.outcomes.length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                No litigation history in this dataset for this strain family.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {clause.outcomes.map((o, i) => (
                  <OutcomeRow key={i} outcome={o} />
                ))}
              </div>
            )}
          </div>

          {/* Neutralising wording — centrepiece for high-risk clauses */}
          <div style={{ marginBottom: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <div className="section-heading" style={{ marginBottom: 0 }}>Neutralising Wording</div>
              {clause.neutralising_wording && !prominent && (
                <button
                  className="btn btn-ghost"
                  style={{ padding: '4px 12px', fontSize: 12 }}
                  onClick={() => setShowNeutralising(!showNeutralising)}
                >
                  {showNeutralising ? 'Hide' : 'Show'} alternative
                </button>
              )}
              {clause.neutralising_wording && prominent && (
                <button
                  className="btn btn-ghost"
                  style={{ padding: '4px 12px', fontSize: 12 }}
                  onClick={() => setShowNeutralising(!showNeutralising)}
                >
                  {showNeutralising ? 'Hide' : 'Show'} comparison
                </button>
              )}
            </div>
            {!clause.neutralising_wording ? (
              <div style={{ fontSize: 13, color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                No lower-risk variant found in this strain family.
              </div>
            ) : showNeutralising ? (
              <div>
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: 10,
                  marginBottom: 12,
                }}>
                  <div style={{
                    background: 'rgba(248,113,113,0.08)',
                    border: '1px solid rgba(248,113,113,0.4)',
                    borderRadius: 8,
                    padding: '12px 14px',
                  }}>
                    <div style={{
                      fontSize: 10,
                      fontWeight: 800,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                      color: 'var(--color-danger)',
                      marginBottom: 6,
                    }}>
                      Current wording
                    </div>
                    <div className="clause-text" style={{ fontSize: 12 }}>
                      {clause.text}
                    </div>
                  </div>
                  <div style={{
                    background: 'rgba(52,211,153,0.08)',
                    border: '1px solid rgba(52,211,153,0.4)',
                    borderRadius: 8,
                    padding: '12px 14px',
                  }}>
                    <div style={{
                      fontSize: 10,
                      fontWeight: 800,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                      color: 'var(--color-success)',
                      marginBottom: 6,
                    }}>
                      Lower-risk variant
                    </div>
                    <div className="clause-text" style={{ color: '#6ee7b7', fontSize: 12 }}>
                      {clause.neutralising_wording.text}
                    </div>
                    <div style={{
                      fontSize: 11,
                      color: 'var(--color-text-faint)',
                      marginTop: 8,
                      display: 'flex',
                      gap: 12,
                    }}>
                      <span>Source doc: {clause.neutralising_wording.source_doc_id}</span>
                      <span>Asymmetry: {Math.round(clause.neutralising_wording.asymmetry_score)}</span>
                    </div>
                  </div>
                </div>
                <WordDiff parentText={clause.text} childText={clause.neutralising_wording.text} />
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

function OutcomeRow({ outcome }: { outcome: OutcomeRecord }) {
  const outcomeColor = {
    voided: 'var(--color-danger)',
    upheld: 'var(--color-success)',
    partially_voided: 'var(--color-warning)',
  }[outcome.outcome] || 'var(--color-text-muted)'

  const outcomeLabel = {
    voided: 'Voided',
    upheld: 'Upheld',
    partially_voided: 'Partially Voided',
  }[outcome.outcome] || outcome.outcome

  return (
    <div style={{
      background: 'var(--color-surface-2)',
      borderRadius: 8,
      padding: '10px 14px',
      display: 'flex',
      gap: 12,
      alignItems: 'flex-start',
    }}>
      <div style={{
        flexShrink: 0,
        padding: '3px 10px',
        borderRadius: 20,
        fontSize: 11,
        fontWeight: 700,
        background: `${outcomeColor}18`,
        color: outcomeColor,
        border: `1px solid ${outcomeColor}30`,
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        whiteSpace: 'nowrap',
      }}>
        {outcomeLabel}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, lineHeight: 1.5 }}>{outcome.holding_summary}</div>
        <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
            {outcome.jurisdiction} · {outcome.year}
          </span>
          <span style={{ fontSize: 11, color: 'var(--color-text-faint)' }}>
            {outcome.source_label}
          </span>
          {outcome.illustrative && (
            <span className="badge badge-illustrative" style={{ fontSize: 10 }}>
              Illustrative
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
