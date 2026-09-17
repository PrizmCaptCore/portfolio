'use client'

import { openUrl } from '@tauri-apps/plugin-opener'

import { useAuth } from '@/contexts/AuthContext'

export function PaywallPage() {
  const { user, logout } = useAuth()

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-lg text-center">
        <div className="mb-6">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-blue-50">
            <svg className="h-7 w-7 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-gray-900">구독이 필요합니다</h1>
          <p className="mt-2 text-sm text-gray-500">
            Relay Assistant를 사용하려면 유료 플랜이 필요합니다.
          </p>
          {user?.email && (
            <p className="mt-1 text-xs text-gray-400">{user.email}</p>
          )}
        </div>

        <div className="space-y-3">
          <button
            type="button"
            onClick={() => {
              void openUrl('https://example.com/pricing')
            }}
            className="block w-full rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            플랜 구독하기
          </button>
          <button
            onClick={() => window.location.reload()}
            className="block w-full rounded-lg border border-gray-200 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            새로고침
          </button>
          <button
            onClick={logout}
            className="block w-full py-2 text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            다른 계정으로 로그인
          </button>
        </div>
      </div>
    </div>
  )
}
