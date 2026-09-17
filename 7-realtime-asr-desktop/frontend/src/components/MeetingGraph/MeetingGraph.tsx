'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useRouter } from 'next/navigation'
import { buildMeetingGraph, type MeetingNodeData, type GraphEdgeData } from '@/services/graphService'
import { MeetingNode } from './MeetingNode'

const NODE_TYPES = { meetingNode: MeetingNode }

type LoadState = 'idle' | 'loading' | 'embedding' | 'done' | 'error'

interface Props {
  threshold?: number
  height?: string
  focusMeetingId?: string | null
  shouldFocusMeeting?: boolean
}

export function MeetingGraph({
  threshold = 0.35,
  height = '380px',
  focusMeetingId = null,
  shouldFocusMeeting = false,
}: Props) {
  const router = useRouter()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<MeetingNodeData>>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<GraphEdgeData>>([])
  const [loadState, setLoadState] = useState<LoadState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [nodeCount, setNodeCount] = useState(0)
  const cancelled = useRef(false)
  const reactFlowRef = useRef<ReactFlowInstance<Node<MeetingNodeData>, Edge<GraphEdgeData>> | null>(null)

  const load = useCallback(async () => {
    cancelled.current = false
    setLoadState('loading')
    setError(null)
    try {
      setLoadState('embedding')
      const { nodes: n, edges: e } = await buildMeetingGraph(threshold)
      if (cancelled.current) return
      setNodes(n)
      setEdges(e)
      setNodeCount(n.length)
      setLoadState('done')
    } catch (err) {
      if (!cancelled.current) {
        setError(err instanceof Error ? err.message : String(err))
        setLoadState('error')
      }
    }
  }, [threshold, setNodes, setEdges])

  useEffect(() => {
    load()
    return () => { cancelled.current = true }
  }, [load])

  useEffect(() => {
    if (!shouldFocusMeeting || !focusMeetingId || loadState !== 'done') return
    const instance = reactFlowRef.current
    if (!instance) return
    const targetNode = nodes.find((node) => node.id === focusMeetingId)
    if (!targetNode) return

    const frameId = window.requestAnimationFrame(() => {
      instance.fitView({
        nodes: [{ id: focusMeetingId }],
        padding: 1.1,
        duration: 450,
        maxZoom: 1.6,
      })
    })

    return () => window.cancelAnimationFrame(frameId)
  }, [shouldFocusMeeting, focusMeetingId, loadState, nodes])

  const onNodeClick: NodeMouseHandler<Node<MeetingNodeData>> = useCallback(
    (_e, node) => router.push(`/meeting-details?id=${(node.data as MeetingNodeData).meetingId}`),
    [router],
  )

  if (loadState === 'loading' || loadState === 'embedding') {
    return (
      <div
        className="flex flex-col items-center justify-center gap-2 text-sm text-gray-400"
        style={{ height }}
      >
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
        <span>
          {loadState === 'loading' ? '회의 데이터 불러오는 중…' : '유사도 계산 중…'}
        </span>
        {loadState === 'embedding' && (
          <span className="text-xs text-gray-300">(첫 실행 시 모델 다운로드 ~25MB)</span>
        )}
      </div>
    )
  }

  if (loadState === 'error') {
    return (
      <div
        className="flex flex-col items-center justify-center gap-2 text-sm text-red-400"
        style={{ height }}
      >
        <span>그래프 생성 실패: {error}</span>
        <button
          className="mt-1 rounded px-3 py-1 text-xs bg-red-50 hover:bg-red-100 text-red-500 border border-red-200"
          onClick={load}
        >
          다시 시도
        </button>
      </div>
    )
  }

  if (loadState === 'done' && nodeCount === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-gray-400"
        style={{ height }}
      >
        요약된 회의가 없습니다. 회의를 녹음하고 요약하면 그래프가 나타납니다.
      </div>
    )
  }

  return (
    <div style={{ height }} className="w-full rounded-xl border border-gray-100 overflow-hidden bg-gray-50/50">
      <ReactFlow
        onInit={(instance) => {
          reactFlowRef.current = instance
        }}
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        minZoom={0.25}
        maxZoom={2}
        attributionPosition="bottom-right"
      >
        <Background color="#e5e7eb" gap={20} size={1} />
        <Controls showInteractive={false} className="!shadow-sm !rounded-lg" />
        <MiniMap
          nodeColor="#6366f1"
          maskColor="rgba(255,255,255,0.75)"
          className="!shadow-sm !rounded-lg"
        />
      </ReactFlow>
    </div>
  )
}
