/**
 * Discord webhook integration. Unlike Slack/Notion/Teams which go through the
 * relay_web gateway and OAuth, Discord webhooks are created by the user inside
 * a Discord server (right-click channel → Edit → Integrations → Webhooks) and
 * pasted into our settings. We POST directly to the webhook URL — no backend,
 * no OAuth, no token refresh.
 *
 * Storage: tauri-plugin-store, file `discord-webhooks.json`. Webhook URLs are
 * effectively channel-write tokens, so they live alongside auth tokens in the
 * Tauri store rather than in cloud settings.
 */

import { fetch } from '@tauri-apps/plugin-http'
import { load } from '@tauri-apps/plugin-store'

const STORE_FILE = 'discord-webhooks.json'
const KEY_WEBHOOKS = 'webhooks'

/** Discord limits webhook content to 2000 chars. Reserve a small buffer for
 *  any prefix we might want to add (none right now), then send anything
 *  longer as a `.md` file attachment so the full summary still arrives. */
const MAX_INLINE_CHARS = 1990

export interface DiscordWebhook {
  id: string
  label: string
  url: string
  /** Wall-clock timestamp of when this webhook was added — sort key for the list. */
  created_at: string
}

export class DiscordError extends Error {
  constructor(public code: string, public httpStatus?: number) {
    super(code)
  }
}

// Validation accepts the four host variants Discord exposes (production,
// canary, ptb, and the legacy discordapp.com domain) and the canonical
// `/api/webhooks/<id>/<token>` path shape. Trim whitespace before testing —
// users frequently paste with trailing newlines.
const DISCORD_WEBHOOK_RE =
  /^https:\/\/((canary|ptb)\.)?(discord|discordapp)\.com\/api\/webhooks\/\d+\/[A-Za-z0-9_-]+\/?$/

export function validateWebhookUrl(url: string): boolean {
  return DISCORD_WEBHOOK_RE.test(url.trim())
}

async function getStore() {
  return load(STORE_FILE, { autoSave: true, defaults: {} })
}

export async function listWebhooks(): Promise<DiscordWebhook[]> {
  const store = await getStore()
  const list = (await store.get<DiscordWebhook[]>(KEY_WEBHOOKS)) ?? []
  // Sort newest-first so recently added shows on top.
  return [...list].sort((a, b) => b.created_at.localeCompare(a.created_at))
}

export async function saveWebhook(label: string, url: string): Promise<DiscordWebhook> {
  const trimmedUrl = url.trim()
  const trimmedLabel = label.trim() || '이름 없음'
  if (!validateWebhookUrl(trimmedUrl)) {
    throw new DiscordError('invalid_webhook_url')
  }
  const list = (await listWebhooks())
  // Prevent silent duplicates: if the same URL is already saved, error so the
  // caller can surface a friendlier message rather than letting the user
  // accumulate hidden duplicates.
  if (list.some((w) => w.url === trimmedUrl)) {
    throw new DiscordError('duplicate_webhook')
  }
  const entry: DiscordWebhook = {
    id: crypto.randomUUID(),
    label: trimmedLabel,
    url: trimmedUrl,
    created_at: new Date().toISOString(),
  }
  const next = [...list, entry]
  const store = await getStore()
  await store.set(KEY_WEBHOOKS, next)
  return entry
}

export async function deleteWebhook(id: string): Promise<void> {
  const list = await listWebhooks()
  const next = list.filter((w) => w.id !== id)
  const store = await getStore()
  await store.set(KEY_WEBHOOKS, next)
}

export async function renameWebhook(id: string, label: string): Promise<void> {
  const list = await listWebhooks()
  const idx = list.findIndex((w) => w.id === id)
  if (idx === -1) return
  const next = [...list]
  next[idx] = { ...next[idx], label: label.trim() || '이름 없음' }
  const store = await getStore()
  await store.set(KEY_WEBHOOKS, next)
}

/**
 * Post the markdown to the given Discord webhook. Short content goes inline;
 * anything beyond Discord's 2000-char limit is sent as a `.md` attachment so
 * nothing is silently truncated.
 *
 * `meetingTitle` is used both as the inline-message header (when attaching a
 * file) and as the file name, so receivers can see what the attachment is at
 * a glance.
 */
export async function sendToDiscordWebhook(
  url: string,
  markdown: string,
  meetingTitle?: string,
): Promise<void> {
  const trimmedTitle = meetingTitle?.trim() || ''

  if (markdown.length <= MAX_INLINE_CHARS) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: markdown }),
    })
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new DiscordError(`http_${res.status}: ${text.slice(0, 200)}`, res.status)
    }
    return
  }

  // Attachment path. Discord webhooks accept multipart/form-data with a file
  // field plus an optional `payload_json` for the message body. Pick a safe
  // file name — strip path-unfriendly chars but keep CJK so users can read it.
  const safeBase = trimmedTitle
    ? trimmedTitle.replace(/[\\/:*?"<>|]+/g, '_').slice(0, 60)
    : 'meeting-summary'
  const fileName = `${safeBase}.md`

  const form = new FormData()
  form.append(
    'payload_json',
    JSON.stringify({
      content: trimmedTitle
        ? `📝 회의 요약 — ${trimmedTitle} (첨부 참조)`
        : '📝 회의 요약 (첨부 참조)',
    }),
  )
  form.append(
    'file',
    new Blob([markdown], { type: 'text/markdown' }),
    fileName,
  )

  const res = await fetch(url, { method: 'POST', body: form })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new DiscordError(`http_${res.status}: ${text.slice(0, 200)}`, res.status)
  }
}
