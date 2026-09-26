import { useState, useEffect } from 'react'
import './index.css'
import { Intake } from './views/Intake'
import { DiagnosisReport } from './views/DiagnosisReport'
import { StrainAtlas } from './views/StrainAtlas'
import { OutbreakDashboard } from './views/OutbreakDashboard'
import { apiClient, BACKEND_DOWN_MESSAGE, isNetworkError } from './api'
import type { DiagnosisResult } from './api'

type Tab = 'intake' | 'diagnosis' | 'atlas' | 'dashboard'

const NAV_TABS = [
  { id: 'intake', label: 'Diagnose' },
  { id: 'atlas', label: 'Strain Atlas' },
  { id: 'dashboard', label: 'Outbreak' },
] as const

const SIDE_FEATURES = [
  {
    shape: <span className="geo" style={{ width: 16, height: 16, borderRadius: '50%', background: 'var(--pink)', display: 'block' }} />,
    title: 'TEXTUAL KINSHIP',
    body: 'Related patterns, never proven copying.',
  },
  {
    shape: <span className="geo" style={{ width: 16, height: 16, background: 'var(--yellow)', border: '2px solid var(--ink)', display: 'block' }} />,
    title: 'SYNTHETIC CORPUS',
    body: 'Built for demonstration, 306 documents.',
  },
  {
    shape: <span className="geo" style={{ width: 0, height: 0, borderLeft: '9px solid transparent', borderRight: '9px solid transparent', borderBottom: '15px solid var(--ink)', display: 'block' }} />,
    title: 'STRAIN ATLAS',
    body: 'Every clause traced to its family tree.',
  },
  {
    shape: <span className="geo" style={{ width: 18, height: 10, background: 'var(--purple)', borderRadius: 6, display: 'block' }} />,
    title: 'HANDOFF PANEL',
    body: 'Take the report to a qualified lawyer.',
  },
]

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('intake')
  const [diagnosisResult, setDiagnosisResult] = useState<DiagnosisResult | null>(null)
  const [userClauseIds, setUserClauseIds] = useState<Set<string>>(new Set())
  const [backendDown, setBackendDown] = useState(false)
  const [checkingBackend, setCheckingBackend] = useState(true)

  const checkBackend = async () => {
    setCheckingBackend(true)
    try {
      await apiClient.health()
      setBackendDown(false)
    } catch (e) {
      if (isNetworkError(e)) setBackendDown(true)
    }
    setCheckingBackend(false)
  }

  useEffect(() => {
    checkBackend()
  }, [])

  const handleDiagnosis = (result: DiagnosisResult) => {
    setDiagnosisResult(result)
    setUserClauseIds(new Set(result.clauses.map(c => c.clause_id)))
    setActiveTab('diagnosis')
  }

  const handleReset = () => {
    setDiagnosisResult(null)
    setUserClauseIds(new Set())
    setActiveTab('intake')
  }

  const showDiagnosisTab = diagnosisResult !== null

  return (
    <div className="app-shell">
      {/* Sidebar */}
      <nav className="nav">
        <div className="nav-inner">
          <a href="#" className="nav-logo" onClick={() => setActiveTab('intake')}>
            <div className="nav-logo-icon" aria-hidden />
            <div className="nav-logo-text">STRAIN<br />PRESS</div>
          </a>

          <div className="nav-tabs">
            {NAV_TABS.map((tab, i) => (
              <button
                key={tab.id}
                className={`nav-tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id as Tab)}
                id={`nav-tab-${tab.id}`}
              >
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.7 }}>
                  0{i + 1}
                </span>
                {tab.label}
              </button>
            ))}
            {showDiagnosisTab && (
              <button
                className={`nav-tab ${activeTab === 'diagnosis' ? 'active' : ''}`}
                onClick={() => setActiveTab('diagnosis')}
                id="nav-tab-diagnosis"
              >
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.7 }}>04</span>
                Diagnosis
                <span style={{
                  fontSize: 9,
                  background: 'var(--pink)',
                  color: '#fff',
                  padding: '1px 7px',
                  borderRadius: 10,
                  fontWeight: 800,
                }}>
                  NEW
                </span>
              </button>
            )}
          </div>

          <div className="side-features">
            {SIDE_FEATURES.map(f => (
              <div className="side-feature" key={f.title}>
                {f.shape}
                <div>
                  <b>{f.title}</b>
                  <span>{f.body}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="side-help">
            <b>NEED HELP?</b>
            Confused by a clause? Bring this report to a qualified lawyer along with your documents.
          </div>

          <span className="nav-synthetic-badge">Synthetic Corpus</span>
        </div>
      </nav>

      {/* Main content */}
      <main className="main-content">
        {backendDown ? (
          <div role="alert" style={{
            maxWidth: 640,
            margin: '80px auto',
            background: '#fdf7e7',
            border: '2px solid var(--ink)',
            borderLeft: '6px solid var(--color-danger)',
            borderRadius: 8,
            padding: 32,
            textAlign: 'center',
            boxShadow: '4px 4px 0 var(--ink)',
          }}>
            <div aria-hidden="true" style={{ fontSize: 40, marginBottom: 12 }}>🔌</div>
            <div style={{ fontWeight: 800, fontSize: 20, marginBottom: 8 }}>
              Backend not reachable
            </div>
            <div style={{
              fontFamily: 'JetBrains Mono, monospace',
              fontSize: 12,
              background: 'var(--color-surface-2)',
              borderRadius: 6,
              padding: '10px 14px',
              marginBottom: 20,
              wordBreak: 'break-all',
            }}>
              {BACKEND_DOWN_MESSAGE}
            </div>
            <button
              className="btn btn-primary"
              onClick={checkBackend}
              disabled={checkingBackend}
              id="backend-retry-btn"
            >
              {checkingBackend ? 'Checking…' : 'Retry'}
            </button>
          </div>
        ) : (
          <>
        {activeTab === 'intake' && (
          <Intake onDiagnosis={handleDiagnosis} />
        )}
        {activeTab === 'diagnosis' && diagnosisResult && (
          <DiagnosisReport result={diagnosisResult} onReset={handleReset} />
        )}
        {activeTab === 'diagnosis' && !diagnosisResult && (
          <div className="empty-state" style={{ marginTop: 80 }}>
            <div className="empty-state-icon">
              <span style={{ display: 'inline-block', width: 40, height: 40, borderRadius: '50%', background: 'var(--pink)' }} />
            </div>
            <div className="empty-state-title">No diagnosis yet</div>
            <div style={{ marginTop: 12 }}>
              <button className="btn btn-primary" onClick={() => setActiveTab('intake')}>
                Start a Diagnosis →
              </button>
            </div>
          </div>
        )}
        {activeTab === 'atlas' && (
          <StrainAtlas userClauseIds={userClauseIds} />
        )}
        {activeTab === 'dashboard' && (
          <OutbreakDashboard />
        )}
          </>
        )}
      </main>
    </div>
  )
}
