/**
 * graphService.ts
 *
 * Meeting graph pipeline:
 * 1. Fetch meetings + key_points from SQLite (Tauri IPC)
 * 2. Check cached embeddings in SQLite
 * 3. Compute missing embeddings via @huggingface/transformers (all-MiniLM-L6-v2, WASM)
 * 4. Persist new embeddings to SQLite
 * 5. Cosine similarity matrix → edges above threshold
 * 6. Extract keywords from key_points text (no LLM)
 * 7. Return node/edge arrays for react-flow
 */

import { invoke } from '@tauri-apps/api/core'
import { MarkerType, type Node, type Edge } from '@xyflow/react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MeetingForGraph {
  id: string
  title: string
  created_at: string
  key_points: string | null
}

export interface MeetingEmbeddingInfo {
  meeting_id: string
  embedding_bytes: number[]
  source_text: string
}

export interface SaveEmbeddingRequest {
  meeting_id: string
  embedding_bytes: number[]
  source_text: string
}

export interface MeetingNodeData extends Record<string, unknown> {
  label: string
  meetingId: string
  date: string
  keywords: string[]
}

export interface GraphEdgeData extends Record<string, unknown> {
  similarity: number
}

// ---------------------------------------------------------------------------
// Embedding pipeline (singleton, lazy-loaded)
//
// transformers.js ships ESM sources that Next.js' SWC can't parse as CJS, and
// webpack can't bundle onnxruntime-web's native addons for a browser target.
// We sidestep both by loading the prebuilt browser bundle at runtime. The
// bundle and its WASM runtime / model weights are copied into public/ at build
// time (scripts/copy-transformers-wasm.mjs, scripts/download-embedding-model.mjs),
// so the DMG ships everything needed for offline inference.
// ---------------------------------------------------------------------------

type PipelineFn = (text: string, opts: object) => Promise<{ data: Float32Array }>

interface TransformersModule {
  pipeline: (task: string, model: string, opts: object) => Promise<PipelineFn>
  env: {
    allowRemoteModels: boolean
    allowLocalModels: boolean
    localModelPath: string
    backends: { onnx: { wasm: { wasmPaths: string } } }
  }
}

let pipelineInstance: PipelineFn | null = null

async function getEmbeddingPipeline(): Promise<PipelineFn> {
  if (pipelineInstance) return pipelineInstance

  // Dynamic import via Function() prevents webpack from statically analyzing
  // the specifier. The path is served from the Tauri bundle at runtime.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mod = await (Function('s', 'return import(s)') as any)(
    '/transformers/transformers.js'
  ) as TransformersModule

  mod.env.allowRemoteModels = false
  mod.env.allowLocalModels = true
  mod.env.localModelPath = '/models/'
  mod.env.backends.onnx.wasm.wasmPaths = '/transformers/'

  pipelineInstance = await mod.pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', {
    dtype: 'fp32',
  })
  return pipelineInstance
}

// ---------------------------------------------------------------------------
// Math helpers
// ---------------------------------------------------------------------------

function cosine(a: Float32Array, b: Float32Array): number {
  let dot = 0, normA = 0, normB = 0
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i]
    normA += a[i] * a[i]
    normB += b[i] * b[i]
  }
  if (normA === 0 || normB === 0) return 0
  return dot / (Math.sqrt(normA) * Math.sqrt(normB))
}

function bytesToFloat32(bytes: number[]): Float32Array {
  return new Float32Array(new Uint8Array(bytes).buffer)
}

function float32ToBytes(arr: Float32Array): number[] {
  return Array.from(new Uint8Array(arr.buffer))
}

// ---------------------------------------------------------------------------
// Keyword extraction (TF-based, no LLM)
// ---------------------------------------------------------------------------

const STOP_WORDS = new Set([
  'the','a','an','and','or','but','in','on','at','to','for','of','with',
  'is','was','are','were','be','been','has','have','had','will','would',
  'can','could','should','may','might','do','does','did','it','its',
  'this','that','these','those','we','our','they','their','you','your',
  'i','my','me','he','she','his','her','us','them','by','from','as','so',
  'if','not','no','up','out','about','what','which','who','when','where',
  'meeting','discussed','team','also','key','point','action','item',
])

function extractKeywords(text: string, topN = 4): string[] {
  if (!text) return []
  const tokens = text
    .toLowerCase()
    .replace(/[^a-z0-9가-힣\s]/g, ' ')
    .split(/\s+/)
    .filter(t => t.length > 2 && !STOP_WORDS.has(t))

  const freq = new Map<string, number>()
  for (const token of tokens) {
    freq.set(token, (freq.get(token) ?? 0) + 1)
  }
  return [...freq.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, topN)
    .map(([word]) => word)
}

// ---------------------------------------------------------------------------
// Timeline layout
//
// Meetings are placed top-to-bottom by recency (newest on top) with a 3-lane
// zigzag on the x-axis so edges between non-adjacent meetings can curve
// distinctly instead of overlapping a straight vertical stack.
// ---------------------------------------------------------------------------

const LANE_X = [20, 220, 420]
const ROW_Y_GAP = 150

function timelinePositions(count: number): { x: number; y: number }[] {
  return Array.from({ length: count }, (_, i) => ({
    x: LANE_X[i % LANE_X.length],
    y: 40 + i * ROW_Y_GAP,
  }))
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export interface GraphData {
  nodes: Node<MeetingNodeData>[]
  edges: Edge<GraphEdgeData>[]
}

export async function buildMeetingGraph(threshold = 0.35): Promise<GraphData> {
  // 1. Fetch meetings with key_points
  const meetings = await invoke<MeetingForGraph[]>('api_get_meetings_for_graph')
  if (meetings.length === 0) return { nodes: [], edges: [] }

  // Sort newest-first so the timeline layout has recent meetings on top and
  // so meetings[i] / meetings[j] with i<j always means i is more recent
  // (keeps the edge arrowhead pointing newer → older below).
  meetings.sort((a, b) => b.created_at.localeCompare(a.created_at))

  // 2. Fetch cached embeddings
  const cached = await invoke<MeetingEmbeddingInfo[]>('api_get_meeting_embeddings')
  const cache = new Map(cached.map(e => [e.meeting_id, e]))

  // 3. Determine what needs (re-)embedding
  const toEmbed = meetings.filter(m => {
    const src = m.key_points ?? ''
    const hit = cache.get(m.id)
    return !hit || hit.source_text !== src
  })

  // 4. Compute embeddings for stale/missing entries
  if (toEmbed.length > 0) {
    const model = await getEmbeddingPipeline()
    const toSave: SaveEmbeddingRequest[] = []

    for (const m of toEmbed) {
      const text = m.key_points ?? m.title
      const output = await model(text, { pooling: 'mean', normalize: true })
      const vec = new Float32Array(output.data)
      const bytes = float32ToBytes(vec)
      toSave.push({ meeting_id: m.id, embedding_bytes: bytes, source_text: m.key_points ?? '' })
      cache.set(m.id, { meeting_id: m.id, embedding_bytes: bytes, source_text: m.key_points ?? '' })
    }

    // 5. Persist new embeddings
    await invoke<void>('api_save_meeting_embeddings', { requests: toSave })
  }

  // 6. Rebuild vector map
  const vectors = new Map<string, Float32Array>()
  for (const m of meetings) {
    const hit = cache.get(m.id)
    if (hit) vectors.set(m.id, bytesToFloat32(hit.embedding_bytes))
  }

  // 7. Build nodes
  const positions = timelinePositions(meetings.length)
  const nodes: Node<MeetingNodeData>[] = meetings.map((m, i) => ({
    id: m.id,
    type: 'meetingNode',
    position: positions[i],
    data: {
      label: m.title,
      meetingId: m.id,
      date: m.created_at,
      keywords: extractKeywords(m.key_points ?? ''),
    },
  }))

  // 8. Build edges
  const edges: Edge<GraphEdgeData>[] = []
  for (let i = 0; i < meetings.length; i++) {
    for (let j = i + 1; j < meetings.length; j++) {
      const a = vectors.get(meetings[i].id)
      const b = vectors.get(meetings[j].id)
      if (!a || !b) continue
      const sim = cosine(a, b)
      if (sim < threshold) continue
      edges.push({
        id: `${meetings[i].id}--${meetings[j].id}`,
        source: meetings[i].id,
        target: meetings[j].id,
        type: 'simplebezier',
        animated: sim >= threshold + 0.2,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: `rgba(99,102,241,${(sim * 0.8 + 0.2).toFixed(2)})`,
        },
        style: {
          strokeWidth: Math.max(1, Math.round(sim * 4)),
          stroke: `rgba(99,102,241,${(sim * 0.8 + 0.2).toFixed(2)})`,
        },
        data: { similarity: sim },
        label: `${(sim * 100).toFixed(0)}%`,
        labelStyle: { fontSize: 10, fill: '#6366f1', fontWeight: 500 },
      })
    }
  }

  return { nodes, edges }
}
