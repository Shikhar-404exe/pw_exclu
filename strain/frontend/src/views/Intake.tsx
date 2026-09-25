import React, { useState, useCallback, useRef } from 'react'
import { apiClient, BACKEND_DOWN_MESSAGE, isNetworkError } from '../api'
import type { DiagnosisResult } from '../api'

interface IntakeProps {
  onDiagnosis: (result: DiagnosisResult) => void
}

export function Intake({ onDiagnosis }: IntakeProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [samples, setSamples] = useState<Array<{ filename: string; label: string }>>([])
  const [loadingSamples, setLoadingSamples] = useState(false)
  const [pastedText, setPastedText] = useState('')
  const [showPaste, setShowPaste] = useState(false)
  const [backendDown, setBackendDown] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const lastFileRef = useRef<File | null>(null)

  const backendDownBox = (onRetry: () => void) => (
    <div style={{
      marginTop: 16,
      padding: '16px 18px',
      background: '#fdf7e7',
      border: '2px solid var(--ink)',
      borderLeft: '6px solid var(--color-danger)',
      borderRadius: 8,
      fontSize: 14,
    }}>
      <div style={{ fontWeight: 800, marginBottom: 6 }}>Backend not reachable</div>
      <div style={{
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: 12,
        background: 'var(--color-surface-2)',
        borderRadius: 6,
        padding: '8px 12px',
        marginBottom: 12,
        wordBreak: 'break-all',
      }}>
        {BACKEND_DOWN_MESSAGE}
      </div>
      <button className="btn btn-primary" onClick={onRetry} id="intake-retry-btn">
        Retry
      </button>
    </div>
  )

  const loadSamples = async () => {
    if (samples.length > 0) return
    setLoadingSamples(true)
    try {
      const { samples: s } = await apiClient.listSamples()
      setSamples(s)
    } catch {
      setSamples([])
    }
    setLoadingSamples(false)
  }

  const runDiagnosis = async (file: File) => {
    setLoading(true)
    setError(null)
    setBackendDown(false)
    lastFileRef.current = file
    try {
      const result = await apiClient.diagnoseFile(file)
      onDiagnosis(result)
    } catch (e: any) {
      if (isNetworkError(e)) {
        setBackendDown(true)
      } else {
        setError(e?.response?.data?.detail || e.message || 'Diagnosis failed. Is the backend running?')
      }
    }
    setLoading(false)
  }

  const handleFile = (file: File) => {
    const allowed = ['.pdf', '.docx', '.txt']
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!allowed.includes(ext)) {
      setError(`Unsupported file type. Please upload a PDF, DOCX, or TXT file.`)
      return
    }
    runDiagnosis(file)
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [])

  const handleSampleClick = async (sample: { filename: string; label: string }) => {
    setLoading(true)
    setError(null)
    try {
      const { text } = await apiClient.getSample(sample.filename)
      await apiClient.ingestText(text, sample.label).then(onDiagnosis)
    } catch (e: any) {
      if (isNetworkError(e)) {
        setBackendDown(true)
      } else {
        setError(e?.response?.data?.detail || e.message || 'Failed to load sample')
      }
    }
    setLoading(false)
  }

  const handlePasteSubmit = async () => {
    if (!pastedText.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await apiClient.ingestText(pastedText, 'pasted-document.txt')
      onDiagnosis(result)
    } catch (e: any) {
      if (isNetworkError(e)) {
        setBackendDown(true)
      } else {
        setError(e?.response?.data?.detail || e.message || 'Diagnosis failed')
      }
    }
    setLoading(false)
  }

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      <div className="poster-hero">
        <div className="hero-sun" aria-hidden />
        <div className="hero-slab" aria-hidden />
        <span className="poster-eyebrow">Residential Rental · India · Vol. 01</span>
        <h1 className="display">
          <span className="row-pink">Clauses</span>
          <span className="row-ink">that spread</span>
          <span className="row-ink">like strains</span>
        </h1>
        <p className="poster-sub">
          Upload a rental agreement. STRAIN identifies which clause families are present,
          how they have mutated, and where the risk lies.
        </p>
        <div style={{ display: 'flex', gap: 16, marginTop: 20, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()} id="hero-diagnose-btn">
            Diagnose a contract →
          </button>
          <button
            className="link-arrow"
            onClick={() => {
              loadSamples()
              document.getElementById('samples-section')?.scrollIntoView({ behavior: 'smooth' })
            }}
          >
            Try a sample →
          </button>
        </div>
      </div>

      <div className="corpus-notice" style={{ justifyContent: 'center' }}>
        <span>●</span>
        The comparison corpus is synthetic. Relationships shown are textual kinship between clause patterns — not proven copying or descent.
      </div>

      {/* Drop zone */}
      <div
        className={`dropzone ${isDragging ? 'active' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        id="file-drop-zone"
      >
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
            <div className="spinner" style={{ width: 40, height: 40, borderWidth: 3 }} />
            <div style={{ fontWeight: 600 }}>Diagnosing…</div>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              This may take up to 30 seconds
            </div>
          </div>
        ) : (
          <>
            <div className="dropzone-icon" aria-hidden style={{ display: 'flex', justifyContent: 'center', alignItems: 'flex-end', gap: 10 }}>
              <span style={{ width: 34, height: 44, background: 'var(--ink)', display: 'block' }} />
              <span style={{ width: 34, height: 44, background: 'var(--pink)', display: 'block', transform: 'rotate(6deg)' }} />
              <span style={{ width: 34, height: 44, background: 'var(--yellow)', border: '2px solid var(--ink)', display: 'block', transform: 'rotate(-6deg)' }} />
            </div>
            <div className="dropzone-title">Drop your rental agreement here</div>
            <div className="dropzone-subtitle">PDF, DOCX or TXT · Click to browse</div>
          </>
        )}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx,.txt"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) handleFile(f)
          e.target.value = ''
        }}
      />

      {backendDown && backendDownBox(() => {
        if (lastFileRef.current) runDiagnosis(lastFileRef.current)
        else setBackendDown(false)
      })}

      {error && (
        <div style={{
          marginTop: 16,
          padding: '12px 16px',
          background: 'var(--color-danger-glow)',
          border: '1px solid rgba(248,113,113,0.3)',
          borderRadius: 8,
          fontSize: 14,
          color: 'var(--color-danger)',
        }}>
          ⚠️ {error}
        </div>
      )}

      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        margin: '24px 0',
        color: 'var(--color-text-faint)',
        fontSize: 13,
      }}>
        <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
        <span>OR</span>
        <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
      </div>

      {/* Paste text */}
      <div style={{ marginBottom: 24 }}>
        <button
          className="btn btn-ghost"
          style={{ width: '100%', justifyContent: 'center', marginBottom: 12 }}
          onClick={() => setShowPaste(!showPaste)}
          id="paste-text-btn"
        >
          {showPaste ? '▲' : '▼'} Paste agreement text
        </button>
        {showPaste && (
          <div>
            <textarea
              value={pastedText}
              onChange={e => setPastedText(e.target.value)}
              placeholder="Paste the full text of the rental agreement here…"
              id="paste-text-area"
              style={{
                width: '100%',
                minHeight: 200,
                background: 'var(--color-surface-2)',
                border: '1px solid var(--color-border)',
                borderRadius: 8,
                padding: 16,
                color: 'var(--color-text)',
                fontSize: 13,
                fontFamily: 'inherit',
                resize: 'vertical',
                outline: 'none',
                marginBottom: 12,
              }}
            />
            <button
              className="btn btn-primary"
              disabled={!pastedText.trim() || loading}
              onClick={handlePasteSubmit}
              id="paste-diagnose-btn"
            >
              {loading ? 'Diagnosing…' : 'Diagnose Pasted Text'}
            </button>
          </div>
        )}
      </div>

      {/* Sample documents */}
      <div id="samples-section" style={{ scrollMarginTop: 20 }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}>
          <div className="section-heading" style={{ marginBottom: 0 }}>Try a Sample Document</div>
          <button
            className="btn btn-ghost"
            style={{ padding: '4px 12px', fontSize: 12 }}
            onClick={loadSamples}
            id="load-samples-btn"
          >
            {loadingSamples ? 'Loading…' : 'Load samples'}
          </button>
        </div>

        {samples.length > 0 && (
          <div className="tile-grid">
            {samples.map((s, i) => (
              <button
                key={s.filename}
                className="sample-card"
                onClick={() => handleSampleClick(s)}
                disabled={loading}
                id={`sample-btn-${s.filename}`}
              >
                <span className="sample-num">0{i + 1}</span>
                <div>
                  <div style={{ fontWeight: 800, fontSize: 13, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{s.label}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 600, marginTop: 2 }}>
                    Synthetic demonstration document
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
