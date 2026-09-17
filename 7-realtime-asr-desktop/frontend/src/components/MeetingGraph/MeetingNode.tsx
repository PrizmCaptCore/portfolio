import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { MeetingNodeData } from '@/services/graphService'

export const MeetingNode = memo(({ data, selected }: NodeProps) => {
  const nodeData = data as MeetingNodeData
  const date = new Date(nodeData.date).toLocaleDateString('ko-KR', {
    month: 'short',
    day: 'numeric',
  })

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-indigo-400 !w-2 !h-2" />
      <div
        className={[
          'rounded-xl border bg-white shadow-sm px-3 py-2 cursor-pointer transition-all duration-150',
          'min-w-[120px] max-w-[175px]',
          selected
            ? 'border-indigo-500 shadow-md ring-2 ring-indigo-200'
            : 'border-gray-200 hover:border-indigo-300 hover:shadow-md',
        ].join(' ')}
      >
        <p className="text-[10px] text-gray-400 mb-0.5 font-medium">{date}</p>
        <p className="text-[13px] font-semibold text-gray-800 leading-snug line-clamp-2">
          {nodeData.label}
        </p>
        {nodeData.keywords.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {nodeData.keywords.slice(0, 3).map(kw => (
              <span
                key={kw}
                className="inline-block rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-600 font-medium"
              >
                {kw}
              </span>
            ))}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-indigo-400 !w-2 !h-2" />
    </>
  )
})

MeetingNode.displayName = 'MeetingNode'
