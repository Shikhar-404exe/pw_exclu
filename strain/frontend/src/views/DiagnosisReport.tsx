import type { DiagnosisResult } from '../api'
import { ClauseCard } from '../components/ClauseCard'
import { HandoffPanel } from '../components/HandoffPanel'

interface DiagnosisReportProps {
  result: DiagnosisResult
  onReset: () => void
}

export function DiagnosisReport({ result, onReset }: DiagnosisReportProps) {
  const operative = result.clauses.filter(c => (c.kind || 'operative') === 'operative')
  const excluded = result.clauses.filter(c => (c.kind || 'operative') !== 'operative')
  const classified = operative.filter(c => c.status === 'classified')
  const unclassified = operative.filter(c => c.status === 'unclassified')
  const highRisk = operative.filter(c => (c.virulence_score ?? 0) >= 75)
  const operativeCount = result.operative_count ?? operative.length
  const excludedCount = result.excluded_count ?? excluded.length
  const avgVirulence = classified.length
    ? Math.round(classified.reduce((s, c) => s + (c.virulence_score ?? 0), 0) / classified.length)
    : 0
  const lowConfidence = classified.filter(c => c.risk_confidence === 'low').length

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
            {result.filename} · {operativeCount} operative clauses
            {excludedCount > 0 && ` · ${excludedCount} non-operative (not scored)`} · sorted by risk
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
          <div className="stat-value">{operativeCount}</div>
          <div className="stat-label" title="Preambles, signatures, witnesses and schedules are identified, not scored">
            Operative clauses
          </div>
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
          <div className="stat-label" title={lowConfidence > 0 ? `${lowConfidence} clause(s) scored with low evidence confidence` : 'Average over strain-matched operative clauses'}>
            Avg risk score{lowConfidence > 0 ? ` · ${lowConfidence} low-confidence` : ''}
          </div>
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
            Clauses by Risk ({operative.length})
          </div>
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            {unclassified.length > 0 && `${unclassified.length} unclassified · `}
            {excludedCount > 0 && `${excludedCount} not scored`}
          </span>
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
