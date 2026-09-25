import { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell, AreaChart, Area, Legend,
} from 'recharts'
import { apiClient, BACKEND_DOWN_MESSAGE, isNetworkError } from '../api'
import type { OutbreakData } from '../api'

const CHART_COLORS = ['#2026a8', '#f23d7f', '#e8a100', '#7c5cff', '#0e9d6e', '#e86a1d', '#c92662']

export function OutbreakDashboard() {
  const [data, setData] = useState<OutbreakData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiClient.getOutbreak()
      .then(setData)
      .catch((e) => setError(isNetworkError(e) ? BACKEND_DOWN_MESSAGE : 'Failed to load outbreak data. Is the corpus seeded?'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 40 }}>
        <div className="spinner" />
        <span style={{ color: 'var(--color-text-muted)' }}>Loading outbreak data…</span>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div style={{
        padding: '12px 16px',
        background: 'var(--color-danger-glow)',
        border: '1px solid rgba(248,113,113,0.3)',
        borderRadius: 8,
        color: 'var(--color-danger)',
      }}>
        ⚠️ {error || 'No data available'}
      </div>
    )
  }

  const pieData = data.outcome_distribution.filter(d => d.count > 0).map(d => ({
    name: d.outcome.replace(/_/g, ' '),
    value: d.count,
  }))

  const pieColors = {
    voided: '#d81b4c',
    upheld: '#1d9e57',
    'partially voided': '#e8a100',
  }

  // Prepare growth data (pivot by generation)
  const growthData: Record<number, Record<string, number>> = {}
  for (const strain of data.strain_growth.slice(0, 5)) {
    for (const pt of strain.by_generation) {
      if (!growthData[pt.generation]) growthData[pt.generation] = { generation: pt.generation }
      growthData[pt.generation][strain.family_name] = pt.count
    }
  }
  const growthSeries = Object.values(growthData).sort((a, b) => (a.generation as number) - (b.generation as number))
  const growthKeys = data.strain_growth.slice(0, 5).map(s => s.family_name)

  const tooltipStyle = {
    background: '#fdf7e7',
    border: '2px solid #2026a8',
    borderRadius: 6,
    color: '#232a5e',
    fontSize: 12,
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Outbreak Dashboard</div>
        <div className="page-subtitle">
          Population view for legal-aid NGOs and regulators — strain prevalence, harshness trends, litigation outcomes
        </div>
      </div>

      <div className="corpus-notice" style={{ marginBottom: 28 }}>
        <span>🔬</span>
        Population data is from the synthetic corpus only. Numbers reflect the constructed evolutionary history, not a real document corpus.
      </div>

      {/* Summary stats */}
      <div className="grid-3" style={{ marginBottom: 28 }}>
        <div className="stat-card">
          <div className="stat-value" style={{ color: 'var(--color-accent)' }}>
            {data.total_documents}
          </div>
          <div className="stat-label">Documents in corpus</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: 'var(--color-purple)' }}>
            {data.total_clauses}
          </div>
          <div className="stat-label">Clauses indexed</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: 'var(--color-teal)' }}>
            {data.total_strains}
          </div>
          <div className="stat-label">Strain families identified</div>
        </div>
      </div>

      {/* Charts grid */}
      <div className="grid-2" style={{ gap: 20, marginBottom: 20 }}>
        {/* Strain prevalence */}
        <div className="card">
          <div className="card-header">
            <span>📊</span>
            <div style={{ fontWeight: 600 }}>Strain Prevalence</div>
          </div>
          <div className="card-body" id="prevalence-chart">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.prevalence.slice(0, 8)} layout="vertical" margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(32,38,168,0.18)" />
                <XAxis type="number" tick={{ fill: '#5a639a', fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="family_name"
                  tick={{ fill: '#5a639a', fontSize: 11 }}
                  width={110}
                />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="count" name="Clauses" radius={[0, 4, 4, 0]}>
                  {data.prevalence.slice(0, 8).map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Harshness trend */}
        <div className="card">
          <div className="card-header">
            <span>📈</span>
            <div style={{ fontWeight: 600 }}>Average Harshness by Generation</div>
          </div>
          <div className="card-body" id="harshness-trend-chart">
            {data.harshness_trend.length === 0 ? (
              <div className="empty-state" style={{ padding: 40 }}>
                <div>No trend data available — run the pipeline first</div>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={data.harshness_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(32,38,168,0.18)" />
                  <XAxis
                    dataKey="generation"
                    tick={{ fill: '#5a639a', fontSize: 11 }}
                    label={{ value: 'Generation', position: 'insideBottom', offset: -5, fill: '#5a639a', fontSize: 11 }}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fill: '#5a639a', fontSize: 11 }}
                    label={{ value: 'Avg Harshness', angle: -90, position: 'insideLeft', fill: '#5a639a', fontSize: 11 }}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(value) => [`${Number(value).toFixed(1)}`, 'Avg Harshness Score']}
                  />
                  <Line
                    type="monotone"
                    dataKey="avg_harshness"
                    stroke="#f23d7f"
                    strokeWidth={3}
                    dot={{ fill: '#f23d7f', r: 4 }}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Outcome distribution */}
        <div className="card">
          <div className="card-header">
            <span>⚖️</span>
            <div style={{ fontWeight: 600 }}>Litigation Outcome Distribution</div>
            <span className="badge badge-illustrative" style={{ marginLeft: 'auto' }}>Illustrative</span>
          </div>
          <div className="card-body" id="outcome-distribution-chart">
            {pieData.length === 0 ? (
              <div className="empty-state" style={{ padding: 40 }}>
                <div>No outcome records loaded</div>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
                <ResponsiveContainer width={200} height={200}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={85}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {pieData.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={(pieColors as any)[entry.name] || CHART_COLORS[i]}
                        />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {pieData.map((entry, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{
                        width: 12,
                        height: 12,
                        borderRadius: 3,
                        background: (pieColors as any)[entry.name] || CHART_COLORS[i],
                        flexShrink: 0,
                      }} />
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600, textTransform: 'capitalize' }}>
                          {entry.name}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                          {entry.value} record{entry.value !== 1 ? 's' : ''}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Strain growth by generation */}
        <div className="card">
          <div className="card-header">
            <span>🦠</span>
            <div style={{ fontWeight: 600 }}>Strain Growth Across Generations</div>
          </div>
          <div className="card-body" id="strain-growth-chart">
            {growthSeries.length === 0 ? (
              <div className="empty-state" style={{ padding: 40 }}>
                <div>No growth data available</div>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={growthSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(32,38,168,0.18)" />
                  <XAxis
                    dataKey="generation"
                    tick={{ fill: '#5a639a', fontSize: 11 }}
                    label={{ value: 'Generation', position: 'insideBottom', offset: -5, fill: '#5a639a', fontSize: 11 }}
                  />
                  <YAxis tick={{ fill: '#5a639a', fontSize: 11 }} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend
                    wrapperStyle={{ fontSize: 11, color: '#5a639a' }}
                  />
                  {growthKeys.map((key, i) => (
                    <Area
                      key={key}
                      type="monotone"
                      dataKey={key}
                      stackId="1"
                      stroke={CHART_COLORS[i % CHART_COLORS.length]}
                      fill={CHART_COLORS[i % CHART_COLORS.length]}
                      fillOpacity={0.3}
                      strokeWidth={1.5}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
