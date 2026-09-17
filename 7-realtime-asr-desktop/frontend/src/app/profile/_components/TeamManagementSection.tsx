'use client'

import { useEffect, useMemo, useState } from 'react'
import { Loader2, Mail, ShieldCheck, UserMinus, Users } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ConfirmationModal } from '@/components/ConfirmationModel/confirmation-modal'
import {
  changeMemberRole,
  inviteMember,
  listMembers,
  listTeams,
  removeMember,
  type Team,
  type TeamMember,
  type TeamRole,
  TEAM_ROLE_LABELS,
} from '@/services/teamsService'
import { TIER_LABELS, type ProfileTier } from '@/services/profileService'

interface TeamManagementSectionProps {
  accessToken: string | null
  // Caller's email; used to disable self-modify actions on the row that
  // matches the current user. The backend rejects self-modification with 400,
  // so this is purely UX — preventing a click that would only fail.
  currentUserEmail: string | null | undefined
}

export function TeamManagementSection({
  accessToken,
  currentUserEmail,
}: TeamManagementSectionProps) {
  const [teams, setTeams] = useState<Team[] | null>(null)
  const [isLoadingTeams, setIsLoadingTeams] = useState(true)
  const [teamsError, setTeamsError] = useState<string | null>(null)
  const [selectedUuid, setSelectedUuid] = useState<string | null>(null)

  const [members, setMembers] = useState<TeamMember[] | null>(null)
  const [isLoadingMembers, setIsLoadingMembers] = useState(false)
  const [membersError, setMembersError] = useState<string | null>(null)

  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<TeamRole>('member')
  const [isInviting, setIsInviting] = useState(false)

  // Tracks per-row in-flight role/remove operations so we can disable just
  // that row's controls without locking the entire table.
  const [pendingRowId, setPendingRowId] = useState<number | null>(null)

  const [removeTarget, setRemoveTarget] = useState<TeamMember | null>(null)

  // Initial team list fetch.
  useEffect(() => {
    if (!accessToken) {
      setIsLoadingTeams(false)
      return
    }
    let cancelled = false
    setIsLoadingTeams(true)
    setTeamsError(null)
    listTeams(accessToken)
      .then((list) => {
        if (cancelled) return
        setTeams(list)
        setSelectedUuid((prev) => {
          if (prev && list.some((t) => t.uuid === prev)) return prev
          return list[0]?.uuid ?? null
        })
      })
      .catch((err) => {
        if (cancelled) return
        setTeamsError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setIsLoadingTeams(false)
      })
    return () => {
      cancelled = true
    }
  }, [accessToken])

  const selectedTeam = useMemo(
    () => teams?.find((t) => t.uuid === selectedUuid) ?? null,
    [teams, selectedUuid],
  )
  const isAdmin = selectedTeam?.my_role === 'admin'

  // Fetch members when an admin team is selected; non-admin teams skip the
  // call because the backend would 403 anyway.
  useEffect(() => {
    if (!accessToken || !selectedTeam || !isAdmin) {
      setMembers(null)
      setMembersError(null)
      return
    }
    let cancelled = false
    setIsLoadingMembers(true)
    setMembersError(null)
    listMembers(accessToken, selectedTeam.uuid)
      .then((list) => {
        if (!cancelled) setMembers(list)
      })
      .catch((err) => {
        if (!cancelled) {
          setMembersError(err instanceof Error ? err.message : String(err))
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoadingMembers(false)
      })
    return () => {
      cancelled = true
    }
  }, [accessToken, selectedTeam, isAdmin])

  const refreshTeams = async () => {
    if (!accessToken) return
    try {
      const list = await listTeams(accessToken)
      setTeams(list)
    } catch (err) {
      console.error('[TeamManagement] refresh teams failed', err)
    }
  }

  const handleInvite = async () => {
    if (!accessToken || !selectedTeam) return
    const email = inviteEmail.trim()
    if (!email) {
      toast.error('이메일을 입력해 주세요')
      return
    }
    setIsInviting(true)
    try {
      const result = await inviteMember(
        accessToken,
        selectedTeam.uuid,
        email,
        inviteRole,
      )
      toast.success(result.message)
      setInviteEmail('')
      setInviteRole('member')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '초대를 보내지 못했습니다')
    } finally {
      setIsInviting(false)
    }
  }

  const handleRoleChange = async (member: TeamMember, role: TeamRole) => {
    if (!accessToken || !selectedTeam || member.role === role) return
    setPendingRowId(member.id)
    try {
      const result = await changeMemberRole(
        accessToken,
        selectedTeam.uuid,
        member.id,
        role,
      )
      setMembers((prev) =>
        prev
          ? prev.map((m) => (m.id === member.id ? result.membership : m))
          : prev,
      )
      toast.success(result.message)
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : '권한을 변경하지 못했습니다',
      )
    } finally {
      setPendingRowId(null)
    }
  }

  const handleRemoveConfirm = async () => {
    const member = removeTarget
    setRemoveTarget(null)
    if (!member || !accessToken || !selectedTeam) return
    setPendingRowId(member.id)
    try {
      await removeMember(accessToken, selectedTeam.uuid, member.id)
      setMembers((prev) => prev?.filter((m) => m.id !== member.id) ?? prev)
      toast.success('팀원을 제거했습니다')
      // member_count on the team list goes stale after removal; quietly refresh
      // so the header chip reflects reality.
      void refreshTeams()
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : '팀원을 제거하지 못했습니다',
      )
    } finally {
      setPendingRowId(null)
    }
  }

  if (!accessToken) return null

  // Loading shell while we figure out whether the user has any teams at all —
  // we render a placeholder rather than nothing so the section doesn't pop in
  // late and shift the surrounding form.
  if (isLoadingTeams) {
    return (
      <section className="rounded-lg border border-gray-200 bg-white p-6">
        <SectionHeader />
        <div className="flex items-center justify-center py-8 text-gray-400">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      </section>
    )
  }

  if (teamsError) {
    return (
      <section className="rounded-lg border border-gray-200 bg-white p-6">
        <SectionHeader />
        <p className="mt-2 text-sm text-red-600">{teamsError}</p>
      </section>
    )
  }

  // Personal account — no teams. Render a disabled section so the user
  // still understands the feature exists but isn't applicable to them.
  if (!teams || teams.length === 0) {
    return (
      <section className="rounded-lg border border-gray-200 bg-white p-6 opacity-60">
        <SectionHeader />
        <p className="mt-3 text-sm text-gray-500">
          소속된 팀이 없습니다. 팀에 초대받으면 이 영역에서 관리할 수 있습니다.
        </p>
      </section>
    )
  }

  return (
    <section className="space-y-5 rounded-lg border border-gray-200 bg-white p-6">
      <SectionHeader />

      {/* Team picker — chip-style tabs so multi-team users can flip between
          teams quickly without a dropdown. */}
      <div className="flex flex-wrap gap-2">
        {teams.map((team) => {
          const isActive = team.uuid === selectedUuid
          return (
            <button
              key={team.uuid}
              type="button"
              onClick={() => setSelectedUuid(team.uuid)}
              className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors ${
                isActive
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
              }`}
            >
              <span className="font-medium">{team.name}</span>
              <span
                className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                  team.my_role === 'admin'
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-gray-100 text-gray-600'
                }`}
              >
                {team.my_role ? TEAM_ROLE_LABELS[team.my_role] : '-'}
              </span>
            </button>
          )
        })}
      </div>

      {selectedTeam ? (
        <div className="space-y-5">
          <TeamHeader team={selectedTeam} />

          {isAdmin ? (
            <>
              <MembersTable
                members={members}
                isLoading={isLoadingMembers}
                error={membersError}
                pendingRowId={pendingRowId}
                currentUserEmail={currentUserEmail}
                onRoleChange={handleRoleChange}
                onRemoveRequest={setRemoveTarget}
              />
              <InviteForm
                email={inviteEmail}
                role={inviteRole}
                isSubmitting={isInviting}
                seatsLeft={selectedTeam.max_seats - selectedTeam.member_count}
                onEmailChange={setInviteEmail}
                onRoleChange={setInviteRole}
                onSubmit={handleInvite}
              />
            </>
          ) : (
            <p className="rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-600">
              이 팀의 관리자만 팀원을 관리할 수 있습니다.
            </p>
          )}
        </div>
      ) : null}

      <ConfirmationModal
        isOpen={!!removeTarget}
        text={
          removeTarget
            ? `${removeTarget.user_name}(${removeTarget.user_email}) 님을 팀에서 제거하시겠습니까?`
            : ''
        }
        onConfirm={handleRemoveConfirm}
        onCancel={() => setRemoveTarget(null)}
      />
    </section>
  )
}

function SectionHeader() {
  return (
    <div className="flex items-center gap-2">
      <Users className="h-5 w-5 text-gray-700" />
      <h2 className="text-lg font-semibold text-gray-900">팀 관리</h2>
    </div>
  )
}

function TeamHeader({ team }: { team: Team }) {
  return (
    <div className="flex items-center gap-4 rounded-md bg-gray-50 px-4 py-3">
      <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-md bg-white">
        {team.logo_url ? (
          <img
            src={team.logo_url}
            alt={`${team.name} 로고`}
            className="h-full w-full object-cover"
          />
        ) : (
          <Users className="h-5 w-5 text-gray-400" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-base font-semibold text-gray-900">
            {team.name}
          </span>
          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
            {TIER_LABELS[team.tier as ProfileTier] ?? team.tier}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-gray-500">
          멤버 {team.member_count} / {team.max_seats}명
        </div>
      </div>
    </div>
  )
}

interface MembersTableProps {
  members: TeamMember[] | null
  isLoading: boolean
  error: string | null
  pendingRowId: number | null
  currentUserEmail: string | null | undefined
  onRoleChange: (member: TeamMember, role: TeamRole) => void
  onRemoveRequest: (member: TeamMember) => void
}

function MembersTable({
  members,
  isLoading,
  error,
  pendingRowId,
  currentUserEmail,
  onRoleChange,
  onRemoveRequest,
}: MembersTableProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-gray-400">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    )
  }
  if (error) {
    return <p className="text-sm text-red-600">{error}</p>
  }
  if (!members || members.length === 0) {
    return <p className="text-sm text-gray-500">팀원이 없습니다.</p>
  }
  return (
    <div className="overflow-hidden rounded-md border border-gray-200">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-3 py-2 font-medium">멤버</th>
            <th className="px-3 py-2 font-medium">역할</th>
            <th className="px-3 py-2 font-medium">가입일</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {members.map((member) => {
            const isSelf =
              !!currentUserEmail &&
              member.user_email.toLowerCase() === currentUserEmail.toLowerCase()
            const rowDisabled = pendingRowId === member.id || isSelf
            return (
              <tr key={member.id} className="bg-white">
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-gray-100">
                      {member.avatar_url ? (
                        <img
                          src={member.avatar_url}
                          alt=""
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <span className="text-[10px] font-semibold text-gray-600">
                          {(member.user_name || member.user_email)
                            .slice(0, 1)
                            .toUpperCase()}
                        </span>
                      )}
                    </div>
                    <div className="min-w-0">
                      <div className="truncate font-medium text-gray-900">
                        {member.user_name || '(이름 없음)'}
                      </div>
                      <div className="truncate text-xs text-gray-500">
                        {member.user_email}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2.5">
                  <Select
                    value={member.role}
                    onValueChange={(v) =>
                      onRoleChange(member, v as TeamRole)
                    }
                    disabled={rowDisabled}
                  >
                    <SelectTrigger className="h-8 w-[110px] text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="admin">관리자</SelectItem>
                      <SelectItem value="member">멤버</SelectItem>
                    </SelectContent>
                  </Select>
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-500">
                  {formatDate(member.joined_at)}
                </td>
                <td className="px-3 py-2.5 text-right">
                  <button
                    type="button"
                    onClick={() => onRemoveRequest(member)}
                    disabled={rowDisabled}
                    className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label="팀원 제거"
                  >
                    <UserMinus className="h-3.5 w-3.5" />
                    <span>제거</span>
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

interface InviteFormProps {
  email: string
  role: TeamRole
  isSubmitting: boolean
  seatsLeft: number
  onEmailChange: (v: string) => void
  onRoleChange: (v: TeamRole) => void
  onSubmit: () => void
}

function InviteForm({
  email,
  role,
  isSubmitting,
  seatsLeft,
  onEmailChange,
  onRoleChange,
  onSubmit,
}: InviteFormProps) {
  const noSeats = seatsLeft <= 0
  return (
    <div className="space-y-3 rounded-md border border-dashed border-gray-200 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
        <Mail className="h-4 w-4" />
        <span>이메일로 초대</span>
        {noSeats ? (
          <span className="ml-auto text-xs font-normal text-amber-600">
            남은 자리 없음
          </span>
        ) : (
          <span className="ml-auto text-xs font-normal text-gray-500">
            남은 자리 {seatsLeft}개
          </span>
        )}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="flex-1 space-y-1">
          <Label htmlFor="invite-email" className="sr-only">
            이메일
          </Label>
          <Input
            id="invite-email"
            type="email"
            placeholder="invitee@example.com"
            value={email}
            onChange={(e) => onEmailChange(e.target.value)}
            disabled={isSubmitting || noSeats}
          />
        </div>
        <Select
          value={role}
          onValueChange={(v) => onRoleChange(v as TeamRole)}
          disabled={isSubmitting || noSeats}
        >
          <SelectTrigger className="w-full sm:w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="member">멤버</SelectItem>
            <SelectItem value="admin">관리자</SelectItem>
          </SelectContent>
        </Select>
        <Button onClick={onSubmit} disabled={isSubmitting || noSeats}>
          {isSubmitting ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <ShieldCheck className="mr-2 h-4 w-4" />
          )}
          초대
        </Button>
      </div>
    </div>
  )
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}
