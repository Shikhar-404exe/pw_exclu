import { useEffect, useRef, useCallback } from 'react'
import * as d3 from 'd3'
import type { StrainDetail } from '../api'

interface TreeNode {
  id: string
  docId: string
  text: string
  isUserNode: boolean
  isRoot: boolean
  virulenceScore: number | null
  asymmetryScore: number | null
  mutationLabel?: string
  mutationType?: string
  children?: TreeNode[]
}

interface MutationTreeProps {
  strain: StrainDetail
  userClauseIds: Set<string>
  onNodeClick: (nodeId: string) => void
  selectedNodeId: string | null
}

function buildTree(strain: StrainDetail, userClauseIds: Set<string>): TreeNode | null {
  const clauseMap = new Map(strain.clauses.map(c => [c.clause_id, c]))
  const edgeMap = new Map<string, string[]>() // parent → children
  const childSet = new Set<string>()

  for (const edge of strain.edges) {
    if (!edgeMap.has(edge.parent_clause_id)) {
      edgeMap.set(edge.parent_clause_id, [])
    }
    edgeMap.get(edge.parent_clause_id)!.push(edge.child_clause_id)
    childSet.add(edge.child_clause_id)
  }

  // Root: appears as parent but not as child
  const parentIds = new Set(strain.edges.map(e => e.parent_clause_id))
  const rootIds = [...parentIds].filter(id => !childSet.has(id))
  const rootId = strain.root_clause_id || rootIds[0] || strain.clauses[0]?.clause_id

  if (!rootId || !clauseMap.has(rootId)) {
    // Flat list, no edges — just show as list
    if (strain.clauses.length === 0) return null
    const root = strain.clauses[0]
    return {
      id: root.clause_id,
      docId: root.doc_id,
      text: root.text,
      isUserNode: userClauseIds.has(root.clause_id),
      isRoot: true,
      virulenceScore: root.virulence_score,
      asymmetryScore: root.asymmetry_score,
    }
  }

  const edgeLabelMap = new Map<string, { label: string; type: string }>()
  for (const e of strain.edges) {
    edgeLabelMap.set(`${e.parent_clause_id}->${e.child_clause_id}`, {
      label: e.mutation_label,
      type: e.mutation_type,
    })
  }

  function buildNode(clauseId: string, depth: number): TreeNode {
    const c = clauseMap.get(clauseId)!
    const childIds = edgeMap.get(clauseId) || []
    const children = depth < 10 ? childIds.map(cid => buildNode(cid, depth + 1)) : []
    return {
      id: clauseId,
      docId: c.doc_id,
      text: c.text || '',
      isUserNode: userClauseIds.has(clauseId),
      isRoot: clauseId === rootId,
      virulenceScore: c.virulence_score,
      asymmetryScore: c.asymmetry_score,
      mutationLabel: undefined,
      mutationType: undefined,
      children: children.length > 0 ? children : undefined,
    }
  }

  return buildNode(rootId, 0)
}

function virulenceColor(score: number | null): string {
  if (score === null) return '#8b93bd'
  if (score >= 75) return '#d81b4c'
  if (score >= 55) return '#e86a1d'
  if (score >= 35) return '#e8a100'
  return '#1d9e57'
}

export function MutationTree({ strain, userClauseIds, onNodeClick, selectedNodeId }: MutationTreeProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  const draw = useCallback(() => {
    if (!svgRef.current) return
    const root = buildTree(strain, userClauseIds)
    if (!root) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const container = svgRef.current.parentElement
    const width = container?.clientWidth || 900
    const height = Math.max(500, container?.clientHeight || 600)

    svg.attr('width', width).attr('height', height)

    const g = svg.append('g').attr('transform', 'translate(60, 40)')

    const hierarchy = d3.hierarchy<TreeNode>(root)
    const treeLayout = d3.tree<TreeNode>()
      .size([height - 80, width - 200])
      .nodeSize([32, 200])

    treeLayout(hierarchy)

    // Links
    g.selectAll('.tree-link')
      .data(hierarchy.links())
      .enter()
      .append('path')
      .attr('class', d => {
        const isHighlighted = userClauseIds.has(d.source.data.id) || userClauseIds.has(d.target.data.id)
        return `tree-link ${isHighlighted ? 'highlighted' : ''}`
      })
      .attr('d', d3.linkHorizontal<d3.HierarchyLink<TreeNode>, d3.HierarchyPointNode<TreeNode>>()
        .x(d => d.y)
        .y(d => d.x))

    // Mutation labels on edges
    const edgeLabelMap = new Map<string, string>()
    for (const e of strain.edges) {
      edgeLabelMap.set(`${e.parent_clause_id}->${e.child_clause_id}`, e.mutation_label)
    }

    g.selectAll('.edge-label')
      .data(hierarchy.links())
      .enter()
      .append('text')
      .attr('class', 'edge-label')
      .attr('x', d => ((d.source as d3.HierarchyPointNode<TreeNode>).y + (d.target as d3.HierarchyPointNode<TreeNode>).y) / 2)
      .attr('y', d => ((d.source as d3.HierarchyPointNode<TreeNode>).x + (d.target as d3.HierarchyPointNode<TreeNode>).x) / 2 - 6)
      .attr('text-anchor', 'middle')
      .attr('font-size', '9px')
      .attr('fill', '#5a639a')
      .text(d => {
        const key = `${d.source.data.id}->${d.target.data.id}`
        const label = edgeLabelMap.get(key) || ''
        return label.length > 28 ? label.slice(0, 28) + '…' : label
      })

    // Nodes
    const nodes = g.selectAll('.tree-node')
      .data(hierarchy.descendants())
      .enter()
      .append('g')
      .attr('class', 'tree-node')
      .attr('transform', d => `translate(${(d as d3.HierarchyPointNode<TreeNode>).y},${(d as d3.HierarchyPointNode<TreeNode>).x})`)
      .style('cursor', 'pointer')
      .on('click', (_: MouseEvent, d: d3.HierarchyNode<TreeNode>) => onNodeClick(d.data.id))

    nodes.append('circle')
      .attr('r', d => {
        if (d.data.isUserNode) return 9
        if (d.data.isRoot) return 7
        return 5
      })
      .attr('fill', d => {
        if (d.data.isUserNode) return '#f23d7f'
        return virulenceColor(d.data.virulenceScore)
      })
      .attr('stroke', d => {
        if (d.data.id === selectedNodeId) return '#141a6e'
        if (d.data.isUserNode) return 'rgba(242,61,127,0.55)'
        return 'rgba(32,38,168,0.55)'
      })
      .attr('stroke-width', d => d.data.id === selectedNodeId ? 2.5 : 1.5)

    // User node pulse ring
    nodes.filter(d => d.data.isUserNode)
      .append('circle')
      .attr('r', 14)
      .attr('fill', 'none')
      .attr('stroke', 'rgba(242,61,127,0.4)')
      .attr('stroke-width', 1.5)

    // Node labels (doc_id truncated)
    nodes.append('text')
      .attr('x', d => d.children ? -10 : 10)
      .attr('text-anchor', d => d.children ? 'end' : 'start')
      .attr('dominant-baseline', 'middle')
      .attr('font-size', '10px')
      .attr('fill', d => d.data.isUserNode ? '#c92662' : '#232a5e')
      .text(d => {
        const id = d.data.docId.slice(-8)
        return d.data.isUserNode ? `Your doc (${id})` : id
      })

    // Zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform)
      })

    svg.call(zoom)
  }, [strain, userClauseIds, onNodeClick, selectedNodeId])

  useEffect(() => {
    draw()
    const handleResize = () => draw()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [draw])

  return (
    <svg
      ref={svgRef}
      style={{ width: '100%', height: '100%', minHeight: 500 }}
    />
  )
}
