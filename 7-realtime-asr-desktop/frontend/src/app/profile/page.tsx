'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, Camera, ExternalLink, Loader2, LogOut } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { openUrl } from '@tauri-apps/plugin-opener'
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
import { useAuth } from '@/contexts/AuthContext'
import {
  getProfile,
  updateProfile,
  updateProfileWithAvatar,
  type Industry,
  type JobRole,
  type Position,
  type ProfileResponse,
  type ProfileUpdate,
  INDUSTRY_LABELS,
  JOB_ROLE_LABELS,
  POSITION_LABELS,
  TIER_LABELS,
} from '@/services/profileService'
import { BackupsSection } from './_components/BackupsSection'
import { TeamManagementSection } from './_components/TeamManagementSection'

// Sentinel used as the "비움" / "선택 안 함" option value.  Radix's <Select>
// disallows empty-string item values, but we still need a way for the user to
// clear an optional field, so we map it to null when sending to the API.
const NONE = '__none__'

const JOB_ROLES: JobRole[] = [
  'researcher',
  'doctor',
  'professor',
  'biz_dev',
  'investment',
  'engineer',
  'student',
  'other',
]
const INDUSTRIES: Industry[] = [
  'bio_pharma',
  'medical',
  'ai_it',
  'manufacturing',
  'finance',
  'startup',
  'other',
]
const POSITIONS: Position[] = ['junior', 'senior', 'executive']

export default function ProfilePage() {
  const router = useRouter()
  const {
    accessToken,
    isAuthenticated,
    isLoading: isAuthLoading,
    user,
    logout,
  } = useAuth()

  const [data, setData] = useState<ProfileResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)

  // Form state — separate from the fetched data so we can dirty-track and
  // reset on Cancel.
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('ko')
  const [jobRole, setJobRole] = useState<string>(NONE)
  const [industry, setIndustry] = useState<string>(NONE)
  const [position, setPosition] = useState<string>(NONE)
  const [teamUuid, setTeamUuid] = useState<string>(NONE)

  // Avatar pending upload — `null` means "no change", a File means "upload".
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Hydrate form whenever a fresh ProfileResponse arrives.
  const hydrate = (resp: ProfileResponse) => {
    setData(resp)
    setName(resp.profile.name ?? '')
    setLanguage(resp.profile.language ?? 'ko')
    setJobRole(resp.profile.job_role ?? NONE)
    setIndustry(resp.profile.industry ?? NONE)
    setPosition(resp.profile.position ?? NONE)
    setTeamUuid(resp.profile.current_team_uuid ?? NONE)
    setAvatarFile(null)
    setAvatarPreview(null)
  }

  useEffect(() => {
    if (isAuthLoading) return
    if (!accessToken) {
      setIsLoading(false)
      return
    }
    let cancelled = false
    setIsLoading(true)
    getProfile(accessToken)
      .then((resp) => {
        if (!cancelled) hydrate(resp)
      })
      .catch((err) => {
        console.error('[ProfilePage] getProfile failed', err)
        toast.error('프로필을 불러오지 못했습니다', {
          description: err instanceof Error ? err.message : String(err),
        })
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [accessToken, isAuthLoading])

  // Object URL cleanup for the local preview of a pending avatar file.
  useEffect(() => {
    if (!avatarFile) return
    const url = URL.createObjectURL(avatarFile)
    setAvatarPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [avatarFile])

  // Track dirty state via ref so the focus handler below can read the latest
  // value without re-binding the listener every keystroke.
  const isDirtyRef = useRef(false)

  // Silent refetch when the window regains focus — covers the "user came back
  // from the external billing page" case so an upgraded tier shows up without
  // a manual refresh. Skipped if the form is dirty so we don't blow away the
  // user's in-progress edits.
  useEffect(() => {
    if (!accessToken) return
    const refresh = () => {
      if (isDirtyRef.current) return
      getProfile(accessToken)
        .then(hydrate)
        .catch(() => {})
    }
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [accessToken])

  const isDirty = useMemo(() => {
    if (!data) return false
    const p = data.profile
    return (
      name !== (p.name ?? '') ||
      language !== (p.language ?? 'ko') ||
      jobRole !== (p.job_role ?? NONE) ||
      industry !== (p.industry ?? NONE) ||
      position !== (p.position ?? NONE) ||
      teamUuid !== (p.current_team_uuid ?? NONE) ||
      avatarFile !== null
    )
  }, [data, name, language, jobRole, industry, position, teamUuid, avatarFile])

  // Mirror dirty state into a ref so the window-focus refetch handler (which
  // is bound once and lives across renders) can decide whether to skip the
  // silent refresh without us re-binding it on every keystroke.
  useEffect(() => {
    isDirtyRef.current = isDirty
  }, [isDirty])

  const handleSave = async () => {
    if (!accessToken || !data) return
    if (!name.trim()) {
      toast.error('이름을 입력해 주세요')
      return
    }

    const patch: ProfileUpdate = {
      name: name.trim(),
      language,
      job_role: jobRole === NONE ? null : (jobRole as JobRole),
      industry: industry === NONE ? null : (industry as Industry),
      position: position === NONE ? null : (position as Position),
      selected_team_uuid: teamUuid === NONE ? null : teamUuid,
    }

    setIsSaving(true)
    try {
      const resp = avatarFile
        ? await updateProfileWithAvatar(accessToken, patch, avatarFile)
        : await updateProfile(accessToken, patch)
      hydrate(resp)
      toast.success('프로필을 저장했습니다')
    } catch (err) {
      console.error('[ProfilePage] save failed', err)
      toast.error('프로필을 저장하지 못했습니다', {
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setIsSaving(false)
    }
  }

  const handleCancel = () => {
    if (data) hydrate(data)
  }

  const handleAvatarPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/')) {
      toast.error('이미지 파일만 업로드할 수 있습니다')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error('5MB 이하의 이미지를 선택해 주세요')
      return
    }
    setAvatarFile(file)
  }

  if (isAuthLoading || isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  if (!isAuthenticated || !data) {
    return (
      <div className="flex h-full items-center justify-center bg-gray-50">
        <p className="text-sm text-gray-500">
          프로필을 보려면 먼저 로그인해 주세요.
        </p>
      </div>
    )
  }

  const profile = data.profile
  const displayedAvatar = avatarPreview ?? profile.avatar_url
  const initials = (profile.name || profile.email || 'U')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('') || 'U'

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      {/* Header */}
      <div className="sticky top-0 z-10 border-b border-gray-200 bg-gray-50">
        <div className="mx-auto flex max-w-3xl items-center gap-4 px-8 py-6">
          <button
            type="button"
            onClick={() => router.back()}
            className="flex items-center gap-2 text-gray-600 transition-colors hover:text-gray-900"
          >
            <ArrowLeft className="h-5 w-5" />
            <span>뒤로</span>
          </button>
          <h1 className="text-3xl font-bold">프로필</h1>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-8 p-8 pt-6">
          {/* Avatar + name row */}
          <section className="flex items-center gap-6 rounded-lg border border-gray-200 bg-white p-6">
            <div className="relative">
              <div className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-full bg-gray-100 text-xl font-semibold text-gray-700">
                {displayedAvatar ? (
                  <img
                    src={displayedAvatar}
                    alt="avatar"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  initials
                )}
              </div>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="absolute -bottom-1 -right-1 flex h-7 w-7 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-600 shadow-sm hover:bg-gray-50"
                aria-label="아바타 업로드"
                title="아바타 업로드"
              >
                <Camera className="h-3.5 w-3.5" />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={handleAvatarPick}
              />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm text-gray-500">{profile.email}</div>
              <div className="mt-1 text-lg font-semibold text-gray-900">
                {name || profile.name || '(이름 없음)'}
              </div>
              <div className="mt-1 flex items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                  {TIER_LABELS[profile.tier] ?? profile.tier}
                </span>
                {/* Plans live on the marketing site; tier flips on this page
                    via the focus refetch above once the user returns. The
                    opener plugin is required because Tauri intercepts plain
                    `<a target="_blank">` clicks. */}
                <button
                  type="button"
                  onClick={() => {
                    void openUrl('https://example.com/plans')
                  }}
                  className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-white px-2 py-0.5 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-50"
                >
                  업그레이드
                  <ExternalLink className="h-3 w-3" />
                </button>
              </div>
            </div>
            <Button
              variant="outline"
              onClick={() => logout()}
              className="shrink-0 self-start text-red-600 hover:bg-red-50 hover:text-red-700"
            >
              <LogOut className="mr-2 h-4 w-4" />
              로그아웃
            </Button>
          </section>

          {/* Editable fields */}
          <section className="space-y-6 rounded-lg border border-gray-200 bg-white p-6">
            <div className="space-y-2">
              <Label htmlFor="profile-name">이름</Label>
              <Input
                id="profile-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="표시할 이름"
              />
            </div>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <Label>현재 팀</Label>
                <Select value={teamUuid} onValueChange={setTeamUuid}>
                  <SelectTrigger>
                    <SelectValue placeholder="팀 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>선택 안 함</SelectItem>
                    {data.teams.map((team) => (
                      <SelectItem key={team.uuid} value={team.uuid}>
                        {team.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>직무</Label>
                <Select value={jobRole} onValueChange={setJobRole}>
                  <SelectTrigger>
                    <SelectValue placeholder="직무 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>선택 안 함</SelectItem>
                    {JOB_ROLES.map((value) => (
                      <SelectItem key={value} value={value}>
                        {JOB_ROLE_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>산업</Label>
                <Select value={industry} onValueChange={setIndustry}>
                  <SelectTrigger>
                    <SelectValue placeholder="산업 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>선택 안 함</SelectItem>
                    {INDUSTRIES.map((value) => (
                      <SelectItem key={value} value={value}>
                        {INDUSTRY_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>직급</Label>
                <Select value={position} onValueChange={setPosition}>
                  <SelectTrigger>
                    <SelectValue placeholder="직급 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>선택 안 함</SelectItem>
                    {POSITIONS.map((value) => (
                      <SelectItem key={value} value={value}>
                        {POSITION_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </section>

          {/* Cloud backups — list, view, and restore meetings the user has
              uploaded with the meeting-detail page's '백업' button. */}
          <BackupsSection accessToken={accessToken} />

          {/* Team management — disabled when the user has no teams (개인 계정),
              admin-gated for management actions otherwise. */}
          <TeamManagementSection
            accessToken={accessToken}
            currentUserEmail={user?.email ?? profile.email}
          />

          {/* Actions */}
          <div className="sticky bottom-0 -mx-8 flex justify-end gap-2 border-t border-gray-200 bg-gray-50 px-8 py-4">
            <Button
              variant="outline"
              onClick={handleCancel}
              disabled={!isDirty || isSaving}
            >
              되돌리기
            </Button>
            <Button onClick={handleSave} disabled={!isDirty || isSaving}>
              {isSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              저장
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
