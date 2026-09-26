import { useState, useEffect, useCallback } from 'react'
import { apiClient, BACKEND_DOWN_MESSAGE, isNetworkError } from '../api'
import type { StrainSummary, StrainDetail } from '../api'
import { MutationTree } from '../components/MutationTree'
import { WordDiff } from '../components/WordDiff'

interface StrainAtlasProps {
  userClauseIds?: Set<string>
}

export function StrainAtlas({ userClauseIds = new Set() }: StrainAtlasProps) {
  const [strains, setStrains] = useState<StrainSummary[]>([])
  const [selectedStrain, setSelectedStrain] = useState<string | null>(null)
  const [strainDetail, setStrainDetail] = useState<StrainDetail | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    setLoading(true)
    apiClient.listStrains()
      .then(({ strains: s }) => {
        // Filter out singletons for atlas view
        const nonSingleton = s.filter(st => !st.strain_id.startsWith('singleton-') && st.edge_count > 0)
        setStrains(nonSingleton)
        if (nonSingleton.length > 0 && !selectedStrain) {
          setSelectedStrain(nonSingleton[0].strain_id)
        }
      })
      .catch((e) => setError(isNetworkError(e) ? BACKEND_DOWN_MESSAGE : 'Failed to load strains'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!selectedStrain) return
    setLoadingDetail(true)
    setStrainDetail(null)
    setSelectedNode(null)
    apiClient.getStrain(selectedStrain)
      .then(setStrainDetail)
      .catch((e) => setError(isNetworkError(e) ? BACKEND_DOWN_MESSAGE : 'Failed to load strain detail'))
      .finally(() => setLoadingDetail(false))
  }, [selectedStrain])

  const handleNodeClick = useCallback((nodeId: string) => {
    setSelectedNode(prev => prev === nodeId ? null : nodeId)
  }, [])

  const selectedClause = strainDetail?.clauses.find(c => c.clause_id === selectedNode)
  const selectedEdge = strainDetail?.edges.find(e => e.child_clause_id === selectedNode)
  // Selector shows the top 10 families by clause count by default.
  const visibleStrains = showAll ? strains : strains.slice(0, 10)
  const parentClause = selectedEdge
    ? strainDetail?.clauses.find(c => c.clause_id === selectedEdge.parent_clause_id)
    : null

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Strain Atlas</div>
        <div className="page-subtitle">
          Phylogeny explorer — trace how clause families mutate across document generations
        </div>
      </div>

      <div className="corpus-notice">
        <span>🧬</span>
        Relationships shown are textual kinship between clause patterns. Connections indicate similar text, not proven origin or copying.
      </div>

      {error && (
        <div role="alert" style={{
          padding: '12px 16px',
          background: 'var(--color-danger-glow)',
          border: '1px solid rgba(248,113,113,0.3)',
          borderRadius: 8,
          color: 'var(--color-danger)',
          marginBottom: 20,
        }}>
          {error}
        </div>
      )}

      {loading && (
        <div role="status" aria-label="Loading strain families" style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 20, color: 'var(--color-text-muted)' }}>
          <div className="spinner" />
          Loading strain families…
        </div>
      )}

      {/* Strain selector */}
      {strains.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div className="section-heading">Select Strain Family</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {visibleStrains.map(s => (
              <button
                key={s.strain_id}
                onClick={() => setSelectedStrain(s.strain_id)}
                className={`btn ${selectedStrain === s.strain_id ? 'btn-primary' : 'btn-ghost'}`}
                style={{ fontSize: 12 }}
                id={`strain-btn-${s.strain_id.slice(-6)}`}
              >
                {s.family_name}
                <span style={{
                  fontSize: 10,
                  background: 'rgba(255,255,255,0.1)',
                  padding: '1px 6px',
                  borderRadius: 10,
                }}>
                  {s.clause_count}
                </span>
              </button>
            ))}
          </div>
          {strains.length > 10 && (
            <button
              className="btn btn-ghost"
              style={{ marginTop: 10, fontSize: 12 }}
              onClick={() => setShowAll(v => !v)}
              id="toggle-all-strains-btn"
            >
              {showAll ? `Show top 10 only` : `Show all families (${strains.length})`}
            </button>
          )}
        </div>
      )}

      {/* Legend */}
      <div style={{
        display: 'flex',
        gap: 20,
        marginBottom: 16,
        fontSize: 12,
        color: 'var(--color-text-muted)',
        flexWrap: 'wrap',
      }}>
        {[
          { color: '#f23d7f', label: 'Your document\'s clause' },
          { color: '#1d9e57', label: 'Low risk' },
          { color: '#e8a100', label: 'Moderate' },
          { color: '#e86a1d', label: 'High' },
          { color: '#d81b4c', label: 'Critical' },
        ].map(({ color, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: color }} />
            {label}
          </div>
        ))}
        <span>Scroll to zoom · Drag to pan · Click node to inspect</span>
      </div>

      {/* Main layout: tree + side panel */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: selectedNode ? '1fr 380px' : '1fr',
        gap: 20,
        minHeight: 520,
      }}>
        {/* Tree */}
        <div className="card" style={{ overflow: 'hidden' }}>
          {loadingDetail ? (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: 400,
              gap: 12,
              color: 'var(--color-text-muted)',
            }}>
              <div className="spinner" />
              Building phylogeny…
            </div>
          ) : strainDetail ? (
            <div style={{ height: 520 }}>
              <MutationTree
                strain={strainDetail}
                userClauseIds={userClauseIds}
                onNodeClick={handleNodeClick}
                selectedNodeId={selectedNode}
              />
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">🌳</div>
              <div className="empty-state-title">Select a strain to explore</div>
            </div>
          )}
        </div>

        {/* Side panel — node detail */}
        {selectedNode && selectedClause && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {/* Node info */}
            <div className="card">
              <div className="card-header">
                <span style={{ fontSize: 16 }}>🔍</span>
                <div>
                  <div style={{ fontWeight: 600 }}>Selected Node</div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 1, fontFamily: 'JetBrains Mono, monospace' }}>
                    {selectedClause.clause_id.slice(-16)}
                  </div>
                </div>
                <button
                  className="btn btn-ghost"
                  style={{ marginLeft: 'auto', padding: '4px 10px', fontSize: 12 }}
                  onClick={() => setSelectedNode(null)}
                  id="close-node-panel-btn"
                  aria-label="Close node detail panel"
                >
                  ✕
                </button>
              </div>
              <div className="card-body">
                <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 6 }}>
                  Source: {selectedClause.doc_id}
                </div>
                {selectedClause.heading && (
                  <div style={{ fontWeight: 600, marginBottom: 8 }}>
                    {selectedClause.heading}
                  </div>
                )}
                {userClauseIds.has(selectedClause.clause_id) && (
                  <div style={{ marginBottom: 8 }}>
                    <span className="badge badge-accent">Your Document</span>
                  </div>
                )}
                <div className="clause-text" style={{
                  background: 'var(--color-surface-2)',
                  borderRadius: 6,
                  padding: '10px 12px',
                  fontSize: 11,
                  maxHeight: 160,
                  overflowY: 'auto',
                }}>
                  {selectedClause.text}
                </div>
                {selectedClause.virulence_score !== null && (
                  <div style={{ marginTop: 10, display: 'flex', gap: 12, fontSize: 12 }}>
                    <span style={{ color: 'var(--color-text-muted)' }}>
                      Risk score: <strong style={{ color: 'var(--color-text)' }}>{Math.round(selectedClause.virulence_score)}</strong>
                    </span>
                    {selectedClause.asymmetry_score !== null && (
                      <span style={{ color: 'var(--color-text-muted)' }}>
                        Asymmetry: <strong style={{ color: 'var(--color-text)' }}>{Math.round(selectedClause.asymmetry_score)}</strong>
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Mutation from parent */}
            {parentClause && selectedEdge && (
              <div className="card">
                <div className="card-header">
                  <span style={{ fontSize: 16 }}>🔬</span>
                  <div>
                    <div style={{ fontWeight: 600 }}>Mutation from Parent</div>
                    <div style={{
                      fontSize: 11,
                      color: 'var(--color-accent)',
                      marginTop: 2,
                      fontStyle: 'italic',
                    }}>
                      {selectedEdge.mutation_label || 'No label'}
                    </div>
                  </div>
                </div>
                <div className="card-body">
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 10 }}>
                    Parent: {parentClause.doc_id.slice(-12)}
                  </div>
                  <WordDiff
                    parentText={parentClause.text}
                    childText={selectedClause.text}
                  />
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Strain outcomes */}
      {strainDetail && strainDetail.outcomes.length > 0 && (
        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-header">
            <span style={{ fontSize: 16 }}>⚖️</span>
            <div style={{ fontWeight: 600 }}>Litigation History — {strainDetail.family_name}</div>
            <span className="badge badge-illustrative" style={{ marginLeft: 'auto' }}>Illustrative</span>
          </div>
          <div className="card-body">
            <div style={{
              fontSize: 12,
              color: 'var(--color-text-muted)',
              marginBottom: 12,
              padding: '8px 12px',
              background: 'rgba(251,191,36,0.10)',
              border: '1px solid rgba(251,191,36,0.35)',
              borderRadius: 6,
            }}>
              Illustrative dataset scenarios — not verified judgments. No independently verified legal sources in this dataset.
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {strainDetail.outcomes.map((o, i) => (
                <div key={i} style={{
                  display: 'flex',
                  gap: 12,
                  padding: '10px 0',
                  borderBottom: i < strainDetail.outcomes.length - 1 ? '1px solid var(--color-border)' : 'none',
                }}>
                  <div style={{
                    flexShrink: 0,
                    padding: '3px 10px',
                    borderRadius: 20,
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '0.5px',
                    background: o.outcome === 'voided' ? 'var(--color-danger-glow)' :
                                o.outcome === 'upheld' ? 'var(--color-success-glow)' : 'var(--color-warning-glow)',
                    color: o.outcome === 'voided' ? 'var(--color-danger)' :
                           o.outcome === 'upheld' ? 'var(--color-success)' : 'var(--color-warning)',
                    border: `1px solid ${o.outcome === 'voided' ? 'rgba(248,113,113,0.3)' :
                                         o.outcome === 'upheld' ? 'rgba(52,211,153,0.3)' : 'rgba(251,191,36,0.3)'}`,
                    alignSelf: 'flex-start',
                    whiteSpace: 'nowrap',
                  }}>
                    {o.outcome.replace(/_/g, ' ')}
                  </div>
                  <div>
                    <div style={{ fontSize: 13, lineHeight: 1.5 }}>{o.holding_summary}</div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                      {o.jurisdiction} · {o.year} · {o.source_label}
                      {o.illustrative && <span className="badge badge-illustrative" style={{ marginLeft: 6, fontSize: 9 }}>Illustrative</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
