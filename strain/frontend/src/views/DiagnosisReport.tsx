import type { DiagnosisResult } from '../api'
import { ClauseCard } from '../components/ClauseCard'
import { HandoffPanel } from '../components/HandoffPanel'

interface DiagnosisReportProps {
  result: DiagnosisResult
  onReset: () => void
}

export function DiagnosisReport({ result, onReset }: DiagnosisReportProps) {
  const classified = result.clauses.filter(c => c.status === 'classified')
  const unclassified = result.clauses.filter(c => c.status === 'unclassified')
  const highRisk = result.clauses.filter(c => (c.virulence_score ?? 0) >= 75)
  const avgVirulence = classified.length
    ? Math.round(classified.reduce((s, c) => s + (c.virulence_score ?? 0), 0) / classified.length)
    : 0

  return (
    <div>
      {/* Top banner */}
      <div className="corpus-notice" id="corpus-notice">
        <span>●</span>
        <span>
          <strong>Synthetic corpus.</strong>{' '}
          {result.corpus_note}
        </span>
      </div>

      {result.scope && result.scope.note && (
        <div className="corpus-notice" id="scope-notice" style={{ background: '#fff3cf' }}>
          <span>◐</span>
          <span>
            <strong>Outside v1 scope.</strong>{' '}
            {result.scope.note}
          </span>
        </div>
      )}

      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: 28,
        flexWrap: 'wrap',
        gap: 16,
      }}>
        <div>
          <div className="page-title">Diagnosis Report</div>
          <div className="page-subtitle">
            {result.filename} · {result.clause_count} clauses · sorted by risk
          </div>
          <div style={{
            fontSize: 11,
            color: 'var(--color-text-faint)',
            marginTop: 4,
            fontFamily: 'JetBrains Mono, monospace',
          }}>
            doc_id: {result.doc_id}
          </div>
        </div>
        <button className="btn btn-ghost" onClick={onReset} id="new-diagnosis-btn">
          ← New Document
        </button>
      </div>

      {/* Stats row */}
      <div className="grid-4" style={{ marginBottom: 28 }}>
        <div className="stat-card">
          <div className="stat-value">{result.clause_count}</div>
          <div className="stat-label">Clauses analysed</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: 'var(--color-danger)' }}>{highRisk.length}</div>
          <div className="stat-label">High-risk clauses</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: 'var(--color-accent)' }}>{classified.length}</div>
          <div className="stat-label">Strain matches</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{
            color: avgVirulence >= 65 ? 'var(--color-danger)' : avgVirulence >= 45 ? 'var(--color-warning)' : 'var(--color-success)',
          }}>
            {avgVirulence}
          </div>
          <div className="stat-label">Avg risk score</div>
        </div>
      </div>

      {/* Clauses — sorted by risk */}
      <div style={{ marginBottom: 32 }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}>
          <div className="section-heading" style={{ marginBottom: 0 }}>
            Clauses by Risk ({result.clauses.length})
          </div>
          {unclassified.length > 0 && (
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
              {unclassified.length} unclassified
            </span>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {result.clauses.map((clause, idx) => (
            <ClauseCard key={clause.clause_id} clause={clause} index={idx} />
          ))}
        </div>
      </div>

      {/* Handoff panel */}
      <HandoffPanel panel={result.handoff_panel} />
    </div>
  )
}
