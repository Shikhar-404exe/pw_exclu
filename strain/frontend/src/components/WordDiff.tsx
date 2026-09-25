import { useMemo } from 'react'

interface WordDiffProps {
  parentText: string
  childText: string
}

interface DiffSegment {
  type: 'eq' | 'del' | 'ins'
  text: string
}

/**
 * Character-level diff renderer using a simple LCS algorithm.
 * Highlights deletions from parent in red and insertions in child in green.
 */
function computeDiff(parent: string, child: string): DiffSegment[] {
  // Tokenise to words for readability
  const parentWords = parent.split(/(\s+)/)
  const childWords = child.split(/(\s+)/)

  const m = parentWords.length
  const n = childWords.length

  // LCS DP table
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (parentWords[i - 1] === childWords[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  // Traceback
  const segments: DiffSegment[] = []
  let i = m, j = n
  const ops: Array<{ type: 'eq' | 'del' | 'ins'; text: string }> = []

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && parentWords[i - 1] === childWords[j - 1]) {
      ops.unshift({ type: 'eq', text: parentWords[i - 1] })
      i--; j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.unshift({ type: 'ins', text: childWords[j - 1] })
      j--
    } else {
      ops.unshift({ type: 'del', text: parentWords[i - 1] })
      i--
    }
  }

  // Merge consecutive same-type segments
  for (const op of ops) {
    if (segments.length > 0 && segments[segments.length - 1].type === op.type) {
      segments[segments.length - 1].text += op.text
    } else {
      segments.push({ ...op })
    }
  }

  return segments
}

export function WordDiff({ parentText, childText }: WordDiffProps) {
  const diff = useMemo(() => computeDiff(parentText, childText), [parentText, childText])

  const delCount = diff.filter(s => s.type === 'del').length
  const insCount = diff.filter(s => s.type === 'ins').length

  return (
    <div>
      <div style={{
        display: 'flex',
        gap: 16,
        marginBottom: 12,
        fontSize: 12,
        fontWeight: 600,
      }}>
        <span style={{ color: '#a31236' }}>
          {delCount} removal{delCount !== 1 ? 's' : ''}
        </span>
        <span style={{ color: '#0f6c38' }}>
          {insCount} addition{insCount !== 1 ? 's' : ''}
        </span>
        {delCount === 0 && insCount === 0 && (
          <span style={{ color: 'var(--color-text-muted)' }}>No changes detected</span>
        )}
      </div>
      <div className="word-diff-container">
        {diff.map((seg, i) => {
          if (seg.type === 'del') {
            return <span key={i} className="diff-del">{seg.text}</span>
          }
          if (seg.type === 'ins') {
            return <span key={i} className="diff-ins">{seg.text}</span>
          }
          return <span key={i} className="diff-eq">{seg.text}</span>
        })}
      </div>
    </div>
  )
}
