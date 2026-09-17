/**
 * Follow-up draft generator. Hits the existing ai/summarize/ proxy
 * (which forwards to the inference Pod) with a chat-completions style payload —
 * no new backend endpoint needed.
 */

import { authedFetch } from './apiClient'

export type FollowUpTone = 'professional' | 'concise' | 'action_items' | 'thanks'

export interface GenerateFollowUpParams {
  /** Meeting summary or notes that the follow-up is based on. */
  summary: string
  tone: FollowUpTone
  /** "email" produces a salutation/sign-off; "slack" stays terse and channel-style. */
  channel: 'email' | 'slack'
  /** Optional meeting title — if present, the model uses it for subject/opening. */
  meetingTitle?: string
  /** Optional attendee names to address by. */
  attendees?: string[]
}

const TONE_INSTRUCTIONS: Record<FollowUpTone, string> = {
  professional:
    '톤은 정중하고 전문적으로 유지하며, 결정 사항과 다음 단계를 명확하게 전달합니다.',
  concise:
    '핵심만 짧게 전달합니다. 불필요한 인사말과 부연 설명은 생략하고, 5문장 이내로 작성합니다.',
  action_items:
    '액션 아이템 중심으로 작성합니다. "누가 / 무엇을 / 언제까지" 형식으로 항목별 정리하고, 결정 사항은 간단히만 언급합니다.',
  thanks:
    '회의에 대한 감사 인사로 시작하고, 주요 합의 사항을 따뜻한 톤으로 정리합니다.',
}

function buildSystemPrompt(params: GenerateFollowUpParams): string {
  const channel = params.channel === 'email'
    ? '이메일 (제목과 본문을 자연스럽게 포함, 인사말과 마무리 인사 포함)'
    : 'Slack 메시지 (인사말 최소화, 마크다운 가능)'
  const lines = [
    '당신은 회의 직후 보낼 후속 메시지의 초안을 작성하는 비서입니다.',
    `대상 채널: ${channel}.`,
    TONE_INSTRUCTIONS[params.tone],
    '회의 요약을 그대로 복사하지 말고, 후속 메시지에 적합한 형식으로 재구성하세요.',
    '받는 사람이 회의에 참석했다는 전제 하에 작성합니다 — 회의 자체를 처음부터 설명하지 않습니다.',
    '한국어로 작성하되, 회의 요약이 영어이거나 다국어로 섞여 있더라도 자연스러운 한국어로 통일합니다.',
  ]
  if (params.attendees && params.attendees.length > 0) {
    lines.push(`수신자: ${params.attendees.join(', ')}.`)
  }
  return lines.join('\n')
}

function buildUserPrompt(params: GenerateFollowUpParams): string {
  const titleLine = params.meetingTitle
    ? `회의 제목: ${params.meetingTitle}\n\n`
    : ''
  return `${titleLine}회의 요약:\n${params.summary}\n\n위 내용을 바탕으로 후속 메시지 초안을 작성해 주세요.`
}

/**
 * Returns the generated draft text. Throws on backend error.
 */
export async function generateFollowUp(
  params: GenerateFollowUpParams,
): Promise<string> {
  const res = await authedFetch('/ai/summarize/', {
    method: 'POST',
    body: JSON.stringify({
      messages: [
        { role: 'system', content: buildSystemPrompt(params) },
        { role: 'user', content: buildUserPrompt(params) },
      ],
      // modal_summary proxies to Ollama; these knobs are accepted by the
      // OpenAI-compatible interface and lightly tune output length.
      temperature: 0.4,
      max_tokens: 800,
    }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data?.detail || `http_${res.status}`)
  }
  const data = await res.json()
  // OpenAI-compat shape: choices[0].message.content
  const choice = (data?.choices ?? [])[0]
  const content = choice?.message?.content ?? choice?.text ?? ''
  if (!content) {
    throw new Error('empty_response')
  }
  return String(content).trim()
}
