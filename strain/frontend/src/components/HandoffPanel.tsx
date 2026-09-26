import type { HandoffPanel as HandoffPanelType } from '../api'

interface HandoffPanelProps {
  panel: HandoffPanelType
}

export function HandoffPanel({ panel }: HandoffPanelProps) {
  return (
    <div className="handoff-panel animate-in">
      <div className="handoff-panel-title">
        <span style={{ fontSize: 22 }}>⚖️</span>
        <div>
          <div>Next Steps — Take This to a Lawyer</div>
          <div style={{ fontSize: 13, fontWeight: 400, color: 'var(--color-text-muted)', marginTop: 2 }}>
            This panel is informational. A qualified lawyer can assess your specific situation.
          </div>
        </div>
      </div>

      {/* Key Dates — typed dates first (execution vs deadlines vs calculated) */}
      {(panel.key_dates || []).length > 0 ? (
        <div style={{
          marginBottom: 28,
          background: '#fff3cf',
          border: '2px solid var(--ink)',
          borderLeft: '6px solid var(--yellow)',
          borderRadius: 6,
          padding: 16,
          boxShadow: '3px 3px 0 var(--ink)',
        }}>
          <div className="section-heading" style={{ marginBottom: 10 }}>Key Dates</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(panel.key_dates || []).map((kd, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, fontSize: 13, alignItems: 'flex-start' }}>
                <span aria-hidden="true" style={{ flexShrink: 0 }}>📅</span>
                <span>
                  <strong>{kd.label}</strong>
                  {kd.date ? `: ~${kd.date}` : ''}
                  {kd.detail ? <span style={{ color: 'var(--color-text-muted)' }}> — {kd.detail}</span> : (!kd.date && <span> — date not stated</span>)}
                  <span style={{
                    fontSize: 10,
                    marginLeft: 6,
                    padding: '0 6px',
                    borderRadius: 8,
                    background: kd.basis === 'explicit' ? 'rgba(32,38,168,0.1)' : kd.basis === 'calculated' ? 'rgba(232,161,0,0.15)' : 'rgba(100,116,139,0.12)',
                    color: 'var(--color-text-muted)',
                  }}>
                    {kd.basis === 'explicit' ? 'in document' : kd.basis === 'calculated' ? 'calculated · approximate' : 'unresolved'}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : panel.detected_deadlines.length > 0 && (
        <div style={{
          marginBottom: 28,
          background: '#fff3cf',
          border: '2px solid var(--ink)',
          borderLeft: '6px solid var(--yellow)',
          borderRadius: 6,
          padding: 16,
          boxShadow: '3px 3px 0 var(--ink)',
        }}>
          <div className="section-heading" style={{ marginBottom: 10 }}>Key Dates</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {panel.detected_deadlines.map((dl, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, fontSize: 13, alignItems: 'flex-start' }}>
                <span style={{ flexShrink: 0 }}>📅</span>
                <span>
                  {dl.label ? (
                    <span><strong>{dl.label}</strong>: ~{dl.date}{dl.detail ? ` (${dl.detail})` : ''}</span>
                  ) : (
                    <span>{dl.date}{dl.kind === 'relative' ? ' (from document text)' : ''}</span>
                  )}
                  {dl.heading && (
                    <span style={{ color: 'var(--color-text-muted)' }}> — in: {dl.heading}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top risk clauses */}
      {panel.top_risk_clauses.length > 0 && (
        <div style={{ marginBottom: 28 }}>
          <div className="section-heading">Highest-Risk Clauses</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {panel.top_risk_clauses.map((item, idx) => (
              <div
                key={item.clause_id}
                style={{
                  background: '#fdf7e7',
                  border: '2px solid var(--ink)',
                  borderRadius: 6,
                  padding: 16,
                  boxShadow: '3px 3px 0 var(--ink)',
                }}
              >
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  marginBottom: 12,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      width: 24,
                      height: 24,
                      background: idx === 0 ? 'rgba(248,113,113,0.2)' : 'rgba(251,191,36,0.15)',
                      borderRadius: '50%',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 11,
                      fontWeight: 700,
                      color: idx === 0 ? 'var(--color-danger)' : 'var(--color-warning)',
                      flexShrink: 0,
                    }}>
                      {idx + 1}
                    </span>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>
                        {item.heading || item.family_name || 'Clause'}
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                        {item.topic_label && (
                          <div className="strain-tag">
                            {item.topic_label}
                          </div>
                        )}
                        {item.family_name && (
                          <div className="strain-tag">
                            {item.family_name}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                  {item.virulence_score !== null && (
                    <span style={{
                      fontSize: 13,
                      fontWeight: 700,
                      color: item.virulence_score >= 75 ? 'var(--color-danger)' : 'var(--color-warning)',
                    }}>
                      Score {Math.round(item.virulence_score)}
                    </span>
                  )}
                </div>

                {/* Clause excerpt */}
                {item.text_excerpt && (
                  <div style={{
                    background: '#f6ecd4',
                    border: '1px solid rgba(32,38,168,0.3)',
                    borderRadius: 4,
                    padding: '8px 12px',
                    fontSize: 12,
                    color: 'var(--color-text)',
                    fontStyle: 'italic',
                    marginBottom: 12,
                    lineHeight: 1.6,
                  }}>
                    "{item.text_excerpt}{item.text_excerpt.length >= 200 ? '…' : ''}"
                  </div>
                )}

                {/* Lawyer questions */}
                <div style={{ marginBottom: 0 }}>
                  <div style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: 'var(--color-accent)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.5px',
                    marginBottom: 8,
                  }}>
                    Ask Your Lawyer
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {item.lawyer_questions.map((q, qi) => (
                      <div key={qi} style={{
                        display: 'flex',
                        gap: 8,
                        fontSize: 13,
                        color: 'var(--color-text)',
                        lineHeight: 1.5,
                      }}>
                        <span style={{ color: 'var(--color-accent)', flexShrink: 0, marginTop: 1 }}>→</span>
                        <span>{q}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid-2" style={{ gap: 20 }}>
        {/* Documents to bring */}
        <div>
          <div className="section-heading">Documents to Bring</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {panel.documents_to_bring.map((doc, i) => (
              <div key={i} style={{
                display: 'flex',
                gap: 8,
                fontSize: 13,
                color: 'var(--color-text)',
                alignItems: 'flex-start',
              }}>
                <span style={{ color: 'var(--color-success)', flexShrink: 0 }}>✓</span>
                <span>{doc}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Detected deadlines */}
        <div>
          <div className="section-heading">Deadlines Detected in Document</div>
          {panel.detected_deadlines.length === 0 ? (
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              No explicit dates detected in this document.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {panel.detected_deadlines.map((dl, i) => (
                <div key={i} style={{
                  background: '#fdf7e7',
                  border: '2px solid var(--ink)',
                  borderRadius: 4,
                  padding: '8px 12px',
                }}>
                  <div style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: 'var(--ink-deep)',
                    marginBottom: 2,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}>
                    <span>📅 {dl.date}</span>
                    {dl.kind === 'relative' && (
                      <span style={{
                        fontSize: 9,
                        fontWeight: 800,
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        background: 'var(--pink)',
                        color: '#fff',
                        borderRadius: 10,
                        padding: '1px 8px',
                      }}>
                        Recurring
                      </span>
                    )}
                  </div>
                  {dl.heading && (
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                      in: {dl.heading}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Legal referral note */}
      <div style={{
        marginTop: 24,
        padding: '12px 16px',
        background: '#fdf7e7',
        borderRadius: 4,
        fontSize: 12,
        color: 'var(--color-text)',
        lineHeight: 1.6,
        border: '2px solid var(--ink)',
        borderLeft: '6px solid var(--pink)',
      }}>
        <strong style={{ color: 'var(--color-text)' }}>Note:</strong>{' '}
        {panel.legal_referral_note}
      </div>
    </div>
  )
}
