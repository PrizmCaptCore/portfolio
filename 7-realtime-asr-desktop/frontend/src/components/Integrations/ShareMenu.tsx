'use client'

import { useEffect, useState } from 'react'
import {
  FileText,
  Mail,
  MessageSquare,
  Share2,
  Users,
} from 'lucide-react'
import { writeText } from '@tauri-apps/plugin-clipboard-manager'
import { invoke } from '@tauri-apps/api/core'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from '@/contexts/AuthContext'
import {
  getStatus,
  type IntegrationProvider,
} from '@/services/integrationService'
import { SendToSlackDialog } from './SendToSlackDialog'
import { SendToNotionDialog } from './SendToNotionDialog'
import { SendToTeamsDialog } from './SendToTeamsDialog'
// Discord / Telegram / KakaoTalk send entries removed from the share menu —
// Discord still required users to set up an inbound webhook (friction
// undermined the "one-click share" intent), and the chat-app pair were
// clipboard+open scaffolding that never produced a smooth send. The
// SendToDiscordDialog file is intentionally left in place so we can
// re-enable Discord later without a revert dance.
// TEMP: Gmail / Outlook Mail OAuth approval pending — see also IntegrationsSettings.tsx
import { SendToGmailDialog } from './SendToGmailDialog'
void SendToGmailDialog

// Web targets for "Send to AI assistant". No formal API exists for chat
// services — the contract is: copy summary to clipboard, open the service's
// new-conversation URL in the user's browser, then they Ctrl+V. If the user
// has a desktop app installed and registered as the default handler for
// these URLs (ChatGPT macOS app, Claude Desktop, etc.), the OS routes them
// there automatically. We don't try to detect installed apps — that's
// fragile across OSes and offers no UX gain over default OS routing.
const AI_TARGETS = [
  {
    id: 'chatgpt',
    label: 'ChatGPT',
    url: 'https://chatgpt.com/',
    color: 'text-[#10a37f]',
    logo: 'openai' as const,
  },
  {
    id: 'claude',
    label: 'Claude',
    url: 'https://claude.ai/new',
    color: 'text-[#d97757]',
    logo: 'claude' as const,
  },
  {
    id: 'gemini',
    label: 'Gemini',
    url: 'https://gemini.google.com/app',
    color: 'text-[#4285F4]',
    logo: 'gemini' as const,
  },
] as const

const AI_LOGO_SRC: Record<(typeof AI_TARGETS)[number]['logo'], string> = {
  openai: '/brand-icons/openai-icon.svg',
  claude: '/brand-icons/claude-ai-icon.svg',
  gemini: '/brand-icons/google-gemini-icon.svg',
}

type AITarget = typeof AI_TARGETS[number]

async function sendToAI(target: AITarget, getMarkdown: () => Promise<string>) {
  try {
    const text = await getMarkdown()
    if (!text.trim()) {
      toast.error('보낼 내용이 없어요.')
      return
    }
    await writeText(text)
    await invoke('open_external_url', { url: target.url })
    toast.success(`${target.label}에 붙여넣으세요`, {
      description: '회의 요약을 복사했어요. 열린 창에서 Ctrl+V (Mac은 Cmd+V).',
    })
  } catch (e: any) {
    toast.error(`${target.label}로 전송 실패: ${e?.message ?? e}`)
  }
}

interface ShareMenuProps {
  getMarkdown: () => Promise<string>
  defaultTitle?: string
  disabled?: boolean
  /** Optional pre-fill recipients passed to the Gmail dialog. */
  defaultRecipients?: string[]
}

// TEMP: 'gmail' removed from union while Gmail OAuth pending. Re-add once enabled.
type ShareTarget = Extract<IntegrationProvider, 'slack' | 'notion' | 'teams'>

export function ShareMenu({
  getMarkdown,
  defaultTitle,
  disabled,
  defaultRecipients,
}: ShareMenuProps) {
  const { isAuthenticated } = useAuth()
  // `defaultRecipients` is currently unused (only Gmail dialog consumed it) — keep prop
  // surface intact so callers don't need to change while Gmail is disabled.
  void defaultRecipients
  const [connected, setConnected] = useState<Record<ShareTarget, boolean>>({
    slack: false,
    notion: false,
    teams: false,
  })
  const [openProvider, setOpenProvider] = useState<ShareTarget | null>(null)

  useEffect(() => {
    if (!isAuthenticated) return
    let cancelled = false
    Promise.all([
      getStatus('slack').catch(() => ({ connected: false })),
      getStatus('notion').catch(() => ({ connected: false })),
      getStatus('teams').catch(() => ({ connected: false })),
      // TEMP: Gmail status check disabled while OAuth approval pending.
      // getStatus('gmail').catch(() => ({ connected: false })),
    ]).then(([slack, notion, teams]) => {
      if (cancelled) return
      setConnected({
        slack: slack.connected === true,
        notion: notion.connected === true,
        teams: teams.connected === true,
      })
    })
    return () => {
      cancelled = true
    }
  }, [isAuthenticated])

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            disabled={disabled}
            title="외부 앱 또는 AI로 전송"
          >
            <Share2 />
            <span className="hidden lg:inline">공유</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem
            disabled={!connected.slack}
            onSelect={() => setOpenProvider('slack')}
          >
            <MessageSquare className="mr-2 h-4 w-4 text-[#4A154B]" />
            Slack으로 전송
            {!connected.slack && (
              <span className="ml-auto text-xs text-gray-400">미연결</span>
            )}
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={!connected.notion}
            onSelect={() => setOpenProvider('notion')}
          >
            <FileText className="mr-2 h-4 w-4 text-gray-900" />
            Notion으로 전송
            {!connected.notion && (
              <span className="ml-auto text-xs text-gray-400">미연결</span>
            )}
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={!connected.teams}
            onSelect={() => setOpenProvider('teams')}
          >
            <Users className="mr-2 h-4 w-4 text-[#6264A7]" />
            Teams로 전송
            {!connected.teams && (
              <span className="ml-auto text-xs text-gray-400">미연결</span>
            )}
          </DropdownMenuItem>
          {/* Gmail send — OAuth approval pending. Disabled with a "Coming Soon"
              hint so users see the planned capability without an interactable
              entry that would fail. */}
          <DropdownMenuItem disabled>
            <Mail className="mr-2 h-4 w-4 text-[#EA4335]" />
            메일로 전송
            <span className="ml-auto text-xs text-gray-400">준비 중</span>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          {AI_TARGETS.map((target) => (
            <DropdownMenuItem
              key={target.id}
              onSelect={() => sendToAI(target, getMarkdown)}
            >
              <img
                src={AI_LOGO_SRC[target.logo]}
                alt=""
                width={16}
                height={16}
                className="mr-2 h-4 w-4 shrink-0"
                aria-hidden
              />
              {`${target.label} 바로가기`}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <SendToSlackDialog
        open={openProvider === 'slack'}
        onOpenChange={(o) => !o && setOpenProvider(null)}
        getMarkdown={getMarkdown}
      />
      <SendToNotionDialog
        open={openProvider === 'notion'}
        onOpenChange={(o) => !o && setOpenProvider(null)}
        getMarkdown={getMarkdown}
        defaultTitle={defaultTitle}
      />
      <SendToTeamsDialog
        open={openProvider === 'teams'}
        onOpenChange={(o) => !o && setOpenProvider(null)}
        getMarkdown={getMarkdown}
      />
      {/* TEMP: Gmail dialog disabled while OAuth approval pending.
      <SendToGmailDialog
        open={openProvider === 'gmail'}
        onOpenChange={(o) => !o && setOpenProvider(null)}
        getMarkdown={getMarkdown}
        defaultSubject={defaultTitle}
        defaultRecipients={defaultRecipients}
      />
      */}
    </>
  )
}
