'use client'

import { MessageSquare, FileText, CalendarDays, Mail, Users } from 'lucide-react'
import { IntegrationCard } from './Integrations/IntegrationCard'
// Discord webhook settings removed alongside the share-menu Discord entry —
// re-mount this if Discord ever comes back. The component file itself is
// kept so re-enabling is a one-line import change.
import { MeetingSummaryIndexCard } from './Integrations/MeetingSummaryIndexCard'

export function IntegrationsSettings() {
  return (
    <div className="space-y-4 py-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">Integrations</h2>
        <p className="mt-1 text-sm text-gray-600">
          외부 앱과 연결하면 회의록을 바로 보내거나, 다가오는 회의를 홈에서 확인할 수 있어요.
        </p>
      </div>

      <div className="space-y-3">
        <IntegrationCard
          provider="google_calendar"
          title="Google Calendar"
          description="다가오는 회의를 홈 화면에 표시하고, 지난 회의를 회의록과 자동으로 연결해요."
          icon={<CalendarDays className="h-5 w-5 text-[#4285F4]" />}
        />
        <IntegrationCard
          provider="outlook_calendar"
          title="Outlook Calendar"
          description="Microsoft 365 캘린더의 다가오는 회의를 홈 화면에 함께 표시해요."
          icon={<CalendarDays className="h-5 w-5 text-[#0078D4]" />}
        />
        {/* OAuth approval pending — `comingSoon` shows the planned capability
            without exposing a Connect button that would fail. Drop the prop
            once both providers are approved. */}
        <IntegrationCard
          provider="gmail"
          title="Gmail"
          description="회의 후 후속 메일을 작성하고 바로 보낼 수 있어요. (읽기 권한은 사용하지 않습니다.)"
          icon={<Mail className="h-5 w-5 text-[#EA4335]" />}
          comingSoon
        />
        <IntegrationCard
          provider="outlook_mail"
          title="Outlook Mail"
          description="Microsoft 365 메일로 후속 메일을 보냅니다. (읽기 권한은 사용하지 않습니다.)"
          icon={<Mail className="h-5 w-5 text-[#0078D4]" />}
          comingSoon
        />
        <IntegrationCard
          provider="slack"
          title="Slack"
          description="선택한 채널로 회의 요약을 보냅니다."
          icon={<MessageSquare className="h-5 w-5 text-[#4A154B]" />}
        />
        <IntegrationCard
          provider="teams"
          title="Microsoft Teams"
          description="선택한 팀의 채널로 회의 요약을 보냅니다. 회사/학교 Microsoft 계정 (Microsoft 365 / Azure AD) 에서만 동작하고, 개인 계정 (@live.com, @hotmail.com, @outlook.com) 은 지원되지 않아요."
          icon={<Users className="h-5 w-5 text-[#6264A7]" />}
        />
        <IntegrationCard
          provider="notion"
          title="Notion"
          description="기존 페이지에 회의 노트를 추가하거나 새 페이지를 만듭니다."
          icon={<FileText className="h-5 w-5 text-gray-900" />}
        />
        <MeetingSummaryIndexCard />
      </div>
    </div>
  )
}
