import axios from 'axios'

const API_BASE = '/api'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
})

// Diagnosis runs live model inference for never-seen wording (cache misses)
// plus nearest-strain matching — far slower than metadata reads. A cold
// backend can take a minute or more, so diagnose calls get their own budget.
const DIAGNOSE_TIMEOUT_MS = 180000

export const BACKEND_DOWN_MESSAGE =
  'Backend not reachable. Run: python -m uvicorn strain.backend.main:app --port 8000'

/** True for network-level failures (backend down), not HTTP 4xx/5xx.
 * Timeouts (ECONNABORTED) are excluded: the server may be up but slow. */
export function isNetworkError(e: any): boolean {
  if (!e) return false
  if (e.response) return false // server answered with an HTTP status
  if (e.code === 'ECONNABORTED') return false // slow server, not a dead one
  return (
    e.code === 'ERR_NETWORK' ||
    e.message === 'Network Error' ||
    !e.request
  )
}

export type RiskLevel = 'critical' | 'high' | 'moderate' | 'low'

/** Single source of truth for risk thresholds (0–100 virulence score). */
export function riskLevel(score: number | null | undefined): RiskLevel | null {
  if (score === null || score === undefined) return null
  if (score >= 75) return 'critical'
  if (score >= 55) return 'high'
  if (score >= 35) return 'moderate'
  return 'low'
}

export const RISK_LABEL: Record<RiskLevel, string> = {
  critical: 'Critical',
  high: 'High',
  moderate: 'Moderate',
  low: 'Low',
}

export interface DiagnosisClause {
  clause_id: string
  doc_id: string
  ordinal: number
  heading: string
  text: string
  topics: string[]
  topic?: string
  topic_label?: string
  topic_confidence?: 'high' | 'medium' | 'low'
  kind?: string
  is_compound: boolean
  is_preamble?: boolean
  strain_id: string | null
  family_name: string | null
  status: 'classified' | 'unclassified' | 'excluded'
  unclassified_message?: string
  exclusion_reason?: string
  confidence: number | null
  virulence_score: number | null
  asymmetry_score: number | null
  harshness_delta: number | null
  outcome_factor: number | null
  risk_confidence?: 'high' | 'medium' | 'low' | null
  evidence?: {
    asymmetry: { value: number; confidence: string; features: string[]; rationale: string }
    harshness: { value: number; confidence: string; features: string[]; rationale: string }
    outcome: { value: number; confidence: string; records: number; voided: number; basis: string; verified_sources: string[]; rationale: string }
  } | null
  evidence_limitations?: string[]
  is_provisional_leaf?: boolean
  virulence_components?: {
    weights: Record<string, number>
    asymmetry: number
    harshness_delta: number
    outcome_factor: number
  }
  outcomes: OutcomeRecord[]
  nearest_variant: {
    clause_id: string
    doc_id: string
    text: string
    similarity: number
  } | null
  neutralising_wording: {
    mode?: string
    clause_id: string
    doc_id: string
    text: string
    asymmetry_score: number
    source_doc_id: string
    material_differences?: string[]
    note?: string
  } | null
  neutralising_note?: string | null
}

export interface OutcomeRecord {
  clause_family: string
  jurisdiction: string
  year: number
  outcome: 'upheld' | 'voided' | 'partially_voided'
  holding_summary: string
  source_label: string
  illustrative: boolean
  verified?: boolean
  source_disclosure?: string
}

export interface KeyDate {
  date: string | null
  parsed_date?: string | null
  label: string
  date_type: string
  basis: 'explicit' | 'calculated' | 'unresolved'
  detail: string | null
  clause_id: string
  heading: string
}

export interface HandoffPanel {
  top_risk_clauses: Array<{
    clause_id: string
    heading: string
    family_name: string
    topic?: string
    topic_label?: string
    virulence_score: number | null
    text_excerpt: string
    lawyer_questions: string[]
  }>
  documents_to_bring: string[]
  detected_deadlines: Array<{
    date: string
    clause_id: string
    heading: string
    kind?: 'absolute' | 'relative' | 'derived'
    date_type?: string
    label?: string
    detail?: string
  }>
  key_dates?: KeyDate[]
  legal_referral_note: string
}

export interface DiagnosisResult {
  doc_id: string
  filename: string
  synthetic: boolean
  corpus_note: string
  scope: {
    in_scope: boolean
    markers: string[]
    note: string | null
  }
  clause_count: number
  operative_count?: number
  excluded_count?: number
  clauses: DiagnosisClause[]
  handoff_panel: HandoffPanel
}

export interface StrainSummary {
  strain_id: string
  family_name: string
  clause_count: number
  edge_count: number
  has_outcomes: boolean
  outcome_summary: Record<string, number>
}

export interface StrainDetail {
  strain_id: string
  family_name: string
  clause_count: number
  root_clause_id: string | null
  clauses: Array<{
    clause_id: string
    doc_id: string
    ordinal: number
    heading: string
    text: string
    normalised_text: string
    strain_id: string
    virulence_score: number | null
    asymmetry_score: number | null
    harshness_delta: number | null
    is_provisional_leaf: boolean
  }>
  edges: Array<{
    parent_clause_id: string
    child_clause_id: string
    distance: number
    mutation_label: string
    mutation_type: string
  }>
  outcomes: OutcomeRecord[]
  virulence_components: {
    description: string
    weights: Record<string, number>
    clauses: Array<{
      clause_id: string
      virulence_score: number | null
      asymmetry_score: number | null
      harshness_delta: number | null
      outcome_factor: number | null
    }>
  }
}

export interface OutbreakData {
  prevalence: Array<{ strain_id: string; family_name: string; count: number }>
  harshness_trend: Array<{ generation: number; avg_harshness: number }>
  outcome_distribution: Array<{ outcome: string; count: number }>
  strain_growth: Array<{
    strain_id: string
    family_name: string
    by_generation: Array<{ generation: number; count: number }>
  }>
  total_documents: number
  total_clauses: number
  total_strains: number
}

export const apiClient = {
  async health(): Promise<{ status: string }> {
    const { data } = await api.get('/health')
    return data
  },

  async diagnoseFile(file: File): Promise<DiagnosisResult> {
    const form = new FormData()
    form.append('file', file)
    const { data } = await api.post('/diagnose', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: DIAGNOSE_TIMEOUT_MS,
    })
    return data
  },

  async listStrains(): Promise<{ strains: StrainSummary[]; total: number }> {
    const { data } = await api.get('/strains')
    return data
  },

  async getStrain(strainId: string): Promise<StrainDetail> {
    const { data } = await api.get(`/strain/${encodeURIComponent(strainId)}`)
    return data
  },

  async getOutbreak(): Promise<OutbreakData> {
    const { data } = await api.get('/outbreak')
    return data
  },

  async listSamples(): Promise<{ samples: Array<{ filename: string; label: string }> }> {
    const { data } = await api.get('/samples')
    return data
  },

  async getSample(filename: string): Promise<{ filename: string; text: string }> {
    const { data } = await api.get(`/samples/${encodeURIComponent(filename)}`)
    return data
  },

  async ingestText(text: string, filename: string): Promise<DiagnosisResult> {
    const blob = new Blob([text], { type: 'text/plain' })
    const file = new File([blob], filename, { type: 'text/plain' })
    return this.diagnoseFile(file)
  },
}
