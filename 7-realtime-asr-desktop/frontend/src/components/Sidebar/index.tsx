"use client"

import React, { useState, useMemo, useEffect } from "react"
import {
  ChevronDown,
  ChevronRight,
  File,
  Settings,
  PanelLeftClose,
  Calendar,
  StickyNote,
  House,
  Mic,
  Trash2,
  Plus,
  Pencil,
  NotepadText,
  Upload,
  UserRound,
} from "lucide-react"
import { useRouter, usePathname } from "next/navigation"
import { useSidebar } from "./SidebarProvider"
import type { CurrentMeeting } from "@/components/Sidebar/SidebarProvider"
import { ConfirmationModal } from "../ConfirmationModel/confirmation-modal"
import { ModelConfig } from "@/components/ModelSettingsModal"
import { SettingTabs } from "../SettingTabs"
import { TranscriptModelProps } from "@/components/TranscriptSettings"
import { DEFAULT_CNN_STT_MODEL } from "@/constants/modelDefaults"
import Analytics from "@/lib/analytics"
import { invoke } from "@tauri-apps/api/core"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { toast } from "sonner"
import { useRecordingState } from "@/contexts/RecordingStateContext"
import { useImportDialog } from "@/contexts/ImportDialogContext"
import { useConfig } from "@/contexts/ConfigContext"
import { normalizeSummaryProvider } from "@/lib/summaryProviders"
import { useAuth } from "@/contexts/AuthContext"

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog"
import { VisuallyHidden } from "@/components/ui/visually-hidden"

import { MessageToast } from "../MessageToast"
import Logo from "../Logo"
import Info from "../Info"
import { ComplianceNotification } from "../ComplianceNotification"

interface SidebarItem {
  id: string
  title: string
  type: "folder" | "file"
  children?: SidebarItem[]
}

const Sidebar: React.FC = () => {
  const router = useRouter()
  const pathname = usePathname()
  const {
    currentMeeting,
    setCurrentMeeting,
    sidebarItems,
    isCollapsed,
    toggleCollapse,
    searchResults,
    searchQuery,
    isSearching,
    meetings,
    setMeetings,
    serverAddress,
  } = useSidebar()

  // Get recording state from RecordingStateContext (single source of truth)
  const { isRecording } = useRecordingState()
  const { openImportDialog } = useImportDialog()
  const { betaFeatures } = useConfig()
  const { logout, user } = useAuth()
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(
    new Set(["meetings"]),
  )
  const [showModelSettings, setShowModelSettings] = useState(false)
  const [modelConfig, setModelConfig] = useState<ModelConfig>({
    provider: "relay-ai",
    model: "",
    whisperModel: "",
    apiKey: null,
  })
  const [transcriptModelConfig, setTranscriptModelConfig] =
    useState<TranscriptModelProps>({
      provider: "cnn-stt",
      model: DEFAULT_CNN_STT_MODEL,
    })
  const [settingsSaveSuccess, setSettingsSaveSuccess] = useState<
    boolean | null
  >(null)

  // State for edit modal
  const [editModalState, setEditModalState] = useState<{
    isOpen: boolean
    meetingId: string | null
    currentTitle: string
  }>({
    isOpen: false,
    meetingId: null,
    currentTitle: "",
  })
  const [editingTitle, setEditingTitle] = useState<string>("")

  const userDisplayName = useMemo(() => {
    if (!user) return "User"
    const fullName = `${user.first_name ?? ""} ${user.last_name ?? ""}`.trim()
    return fullName || user.username || user.email || "User"
  }, [user])

  const userInitials = useMemo(() => {
    const source = userDisplayName.trim()
    if (!source) return "U"
    const parts = source.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
    }
    return source.slice(0, 2).toUpperCase()
  }, [userDisplayName])

  // Ensure 'meetings' folder is always expanded
  useEffect(() => {
    if (!expandedFolders.has("meetings")) {
      const newExpanded = new Set(expandedFolders)
      newExpanded.add("meetings")
      setExpandedFolders(newExpanded)
    }
  }, [expandedFolders])

  // useEffect(() => {
  //   if (settingsSaveSuccess !== null) {
  //     const timer = setTimeout(() => {
  //       setSettingsSaveSuccess(null);
  //     }, 3000);
  //   }
  // }, [settingsSaveSuccess]);

  const [deleteModalState, setDeleteModalState] = useState<{
    isOpen: boolean
    itemId: string | null
  }>({ isOpen: false, itemId: null })

  useEffect(() => {
    // Note: Don't set hardcoded defaults - let DB be the source of truth
    const fetchModelConfig = async () => {
      // Only make API call if serverAddress is loaded
      if (!serverAddress) {
        console.log(
          "Waiting for server address to load before fetching model config",
        )
        return
      }

      try {
        const data = (await invoke("api_get_model_config")) as any
        if (data && data.provider !== null) {
          const normalizedProvider = normalizeSummaryProvider(data.provider)

          if (normalizedProvider !== "relay-ai" && !data.apiKey) {
            try {
              const apiKeyData = (await invoke("api_get_api_key", {
                provider: normalizedProvider,
              })) as string
              data.apiKey = apiKeyData
            } catch (err) {
              console.error("Failed to fetch API key:", err)
            }
          }
          setModelConfig({
            ...data,
            provider: normalizedProvider,
          })
        }
      } catch (error) {
        console.error("Failed to fetch model config:", error)
      }
    }

    fetchModelConfig()
  }, [serverAddress])

  useEffect(() => {
    // Note: Don't set hardcoded defaults - let DB be the source of truth
    const fetchTranscriptSettings = async () => {
      // Only make API call if serverAddress is loaded
      if (!serverAddress) {
        console.log(
          "Waiting for server address to load before fetching transcript settings",
        )
        return
      }

      try {
        const data = (await invoke("api_get_transcript_config")) as any
        if (data && data.provider !== null) {
          setTranscriptModelConfig(data)
        }
      } catch (error) {
        console.error("Failed to fetch transcript settings:", error)
      }
    }
    fetchTranscriptSettings()
  }, [serverAddress])

  // Listen for model config updates from other components
  useEffect(() => {
    const setupListener = async () => {
      const { listen } = await import("@tauri-apps/api/event")
      const unlisten = await listen<ModelConfig>(
        "model-config-updated",
        (event) => {
          console.log(
            "Sidebar received model-config-updated event:",
            event.payload,
          )
          setModelConfig(event.payload)
        },
      )

      return unlisten
    }

    let cleanup: (() => void) | undefined
    setupListener().then((fn) => (cleanup = fn))

    return () => {
      cleanup?.()
    }
  }, [])

  // Handle model config save
  const handleSaveModelConfig = async (config: ModelConfig) => {
    try {
      await invoke("api_save_model_config", {
        provider: config.provider,
        model: config.model,
        whisperModel: config.whisperModel,
        apiKey: config.apiKey,
      })

      setModelConfig(config)
      console.log("Model config saved successfully")
      setSettingsSaveSuccess(true)

      // Emit event to sync other components
      const { emit } = await import("@tauri-apps/api/event")
      await emit("model-config-updated", config)

      // Track settings change
      await Analytics.trackSettingsChanged(
        "model_config",
        `${config.provider}_${config.model}`,
      )
    } catch (error) {
      console.error("Error saving model config:", error)
      setSettingsSaveSuccess(false)
    }
  }

  const handleSaveTranscriptConfig = async (
    updatedConfig?: TranscriptModelProps,
  ) => {
    try {
      const configToSave = updatedConfig || transcriptModelConfig
      const payload = {
        provider: configToSave.provider,
        model: configToSave.model,
        apiKey: configToSave.apiKey ?? null,
      }
      console.log("Saving transcript config with payload:", payload)

      await invoke("api_save_transcript_config", {
        provider: payload.provider,
        model: payload.model,
        apiKey: payload.apiKey,
      })

      setSettingsSaveSuccess(true)

      // Track settings change
      const transcriptConfigToSave = updatedConfig || transcriptModelConfig
      await Analytics.trackSettingsChanged(
        "transcript_config",
        `${transcriptConfigToSave.provider}_${transcriptConfigToSave.model}`,
      )
    } catch (error) {
      console.error("Failed to save transcript config:", error)
      setSettingsSaveSuccess(false)
    }
  }

  const filteredSidebarItems = useMemo(() => sidebarItems, [sidebarItems])

  const handleDelete = async (itemId: string) => {
    console.log("Deleting item:", itemId)
    const payload = {
      meetingId: itemId,
    }

    try {
      const { invoke } = await import("@tauri-apps/api/core")
      await invoke("api_delete_meeting", {
        meetingId: itemId,
      })
      console.log("Meeting deleted successfully")
      const updatedMeetings = meetings.filter(
        (m: CurrentMeeting) => m.id !== itemId,
      )
      setMeetings(updatedMeetings)

      // Track meeting deletion
      Analytics.trackMeetingDeleted(itemId)

      // Show success toast
      toast.success("회의를 삭제했습니다", {
        description: "관련 데이터가 모두 제거되었습니다",
      })

      // If deleting the active meeting, fall back to the "+ New Call"
      // placeholder which lives on the recording page.
      if (currentMeeting?.id === itemId) {
        setCurrentMeeting({ id: "intro-call", title: "+ 새 회의" })
        router.push("/record")
      }
    } catch (error) {
      console.error("Failed to delete meeting:", error)
      toast.error("회의를 삭제하지 못했습니다", {
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }

  const handleDeleteConfirm = () => {
    if (deleteModalState.itemId) {
      handleDelete(deleteModalState.itemId)
    }
    setDeleteModalState({ isOpen: false, itemId: null })
  }

  // Handle modal editing of meeting names
  const handleEditStart = (meetingId: string, currentTitle: string) => {
    setEditModalState({
      isOpen: true,
      meetingId: meetingId,
      currentTitle: currentTitle,
    })
    setEditingTitle(currentTitle)
  }

  const handleEditConfirm = async () => {
    const newTitle = editingTitle.trim()
    const meetingId = editModalState.meetingId

    if (!meetingId) return

    // Prevent empty titles
    if (!newTitle) {
      toast.error("회의 제목은 비워둘 수 없습니다")
      return
    }

    try {
      await invoke("api_save_meeting_title", {
        meetingId: meetingId,
        title: newTitle,
      })

      // Update local state
      const updatedMeetings = meetings.map((m: CurrentMeeting) =>
        m.id === meetingId ? { ...m, title: newTitle } : m,
      )
      setMeetings(updatedMeetings)

      // Update current meeting if it's the one being edited
      if (currentMeeting?.id === meetingId) {
        setCurrentMeeting({ id: meetingId, title: newTitle })
      }

      // Track the edit
      Analytics.trackButtonClick("edit_meeting_title", "sidebar")

      toast.success("회의 제목을 변경했습니다")

      // Close modal and reset state
      setEditModalState({ isOpen: false, meetingId: null, currentTitle: "" })
      setEditingTitle("")
    } catch (error) {
      console.error("Failed to update meeting title:", error)
      toast.error("회의 제목을 변경하지 못했습니다", {
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }

  const handleEditCancel = () => {
    setEditModalState({ isOpen: false, meetingId: null, currentTitle: "" })
    setEditingTitle("")
  }

  const toggleFolder = (folderId: string) => {
    // Normal toggle behavior for all folders
    const newExpanded = new Set(expandedFolders)
    if (newExpanded.has(folderId)) {
      newExpanded.delete(folderId)
    } else {
      newExpanded.add(folderId)
    }
    setExpandedFolders(newExpanded)
  }

  // Expose setShowModelSettings to window for Rust tray to call
  useEffect(() => {
    ;(window as any).openSettings = () => {
      setShowModelSettings(true)
    }

    // Cleanup on unmount
    return () => {
      delete (window as any).openSettings
    }
  }, [])

  const renderCollapsedIcons = () => {
    if (!isCollapsed) return null

    const isHomePage = pathname === "/"
    const isMeetingPage = pathname?.includes("/meeting-details")
    const isSettingsPage = pathname === "/settings"
    const isRecordPage = pathname === "/record"

    return (
      <TooltipProvider>
        <div className="flex flex-col items-center space-y-4 mt-4">
          <Logo isCollapsed={isCollapsed} />

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => router.push("/")}
                className={`p-2 rounded-lg transition-colors duration-150 ${
                  isHomePage ? "bg-gray-100" : "hover:bg-gray-100"
                }`}
              >
                <House className="w-5 h-5 text-gray-600" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>홈</p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => router.push("/record")}
                className={`p-2 rounded-lg transition-colors duration-150 ${
                  isRecordPage ? "bg-gray-100" : "hover:bg-gray-100"
                }`}
              >
                <Mic className="w-5 h-5 text-gray-600" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>녹음</p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => {
                  if (isCollapsed) toggleCollapse()
                  toggleFolder("meetings")
                }}
                className={`p-2 rounded-lg transition-colors duration-150 ${
                  isMeetingPage ? "bg-gray-100" : "hover:bg-gray-100"
                }`}
              >
                <NotepadText className="w-5 h-5 text-gray-600" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>회의록</p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => router.push("/settings")}
                className={`p-2 rounded-lg transition-colors duration-150 ${
                  isSettingsPage ? "bg-gray-100" : "hover:bg-gray-100"
                }`}
              >
                <Settings className="w-5 h-5 text-gray-600" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>설정</p>
            </TooltipContent>
          </Tooltip>

          <Info isCollapsed={isCollapsed} />
        </div>
      </TooltipProvider>
    )
  }

  const renderItem = (item: SidebarItem, depth = 0) => {
    const isExpanded = expandedFolders.has(item.id)
    const paddingLeft = `${depth * 12 + 12}px`
    const isActive = item.type === "file" && currentMeeting?.id === item.id
    const isMeetingItem =
      item.id.includes("-") && !item.id.startsWith("intro-call")

    if (isCollapsed) return null

    return (
      <div key={item.id}>
        <div
          className={`flex items-center transition-all duration-150 group ${
            item.type === "folder" && depth === 0
              ? "p-3 text-lg font-semibold h-10 mx-3 mt-3 rounded-lg"
              : `px-3 py-2 my-0.5 rounded-md text-sm ${
                  isActive
                    ? "bg-blue-100 text-blue-700 font-medium"
                    : "hover:bg-gray-50"
                } cursor-pointer`
          }`}
          style={item.type === "folder" && depth === 0 ? {} : { paddingLeft }}
          onClick={() => {
            if (item.type === "folder") {
              toggleFolder(item.id)
            } else {
              setCurrentMeeting({ id: item.id, title: item.title })
              const basePath = item.id.startsWith("intro-call")
                ? "/record"
                : item.id.includes("-")
                  ? `/meeting-details?id=${item.id}`
                  : `/notes/${item.id}`
              router.push(basePath)
            }
          }}
        >
          {item.type === "folder" ? (
            <>
              {item.id === "meetings" ? (
                <Calendar className="w-4 h-4 mr-2" />
              ) : item.id === "notes" ? (
                <Calendar className="w-4 h-4 mr-2" />
              ) : null}
              <span className={depth === 0 ? "" : "font-medium"}>
                {item.title}
              </span>
              <div className="ml-auto">
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-gray-500" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-gray-500" />
                )}
              </div>
              {searchQuery && item.id === "meetings" && isSearching && (
                <span className="ml-2 text-xs text-blue-500 animate-pulse">
                  검색 중…
                </span>
              )}
            </>
          ) : (
            <div className="flex flex-col w-full">
              <div className="flex items-center w-full">
                {isMeetingItem ? (
                  <div className="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full mr-2 bg-gray-100">
                    <File className="w-3.5 h-3.5 text-gray-600" />
                  </div>
                ) : (
                  <div className="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full mr-2 bg-blue-100">
                    <Plus className="w-3.5 h-3.5 text-blue-600" />
                  </div>
                )}
                <span className="flex-1 break-words">{item.title}</span>
                {isMeetingItem && (
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleEditStart(item.id, item.title)
                      }}
                      className="hover:text-blue-600 p-1 rounded-md hover:bg-blue-50 flex-shrink-0"
                      aria-label="회의 제목 편집"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setDeleteModalState({ isOpen: true, itemId: item.id })
                      }}
                      className="hover:text-red-600 p-1 rounded-md hover:bg-red-50 flex-shrink-0"
                      aria-label="회의 삭제"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        {item.type === "folder" && isExpanded && item.children && (
          <div className="ml-1">
            {item.children.map((child) => renderItem(child, depth + 1))}
          </div>
        )}
      </div>
    )
  }

  return (
    <>
      <div
        className={`fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-gray-200 bg-white shadow-sm transition-[width] duration-300 ease-out ${
          isCollapsed ? "w-16" : "w-64"
        }`}
      >
        {/*  Header with traffic light spacing */}
        <div className="flex-shrink-0 h-22 flex items-center">
          {/* Title container */}

          <div className="flex-1">
            {!isCollapsed && (
              <div className="p-3">
                <div className="mb-3 flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <Logo isCollapsed={isCollapsed} />
                  </div>
                  <button
                    type="button"
                    onClick={toggleCollapse}
                    aria-expanded={true}
                    aria-label="사이드바 접기"
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-600 shadow-sm transition-colors hover:bg-gray-50"
                  >
                    <PanelLeftClose className="h-5 w-5 shrink-0" />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Main content - scrollable area */}
        <div className="flex-1 flex flex-col min-h-0">
          {/* Fixed navigation items */}
          <div className="flex-shrink-0">
            {!isCollapsed && (
              <>
                <div
                  onClick={() => router.push("/")}
                  className={`p-3 text-lg font-semibold items-center hover:bg-gray-100 h-10 flex mx-3 mt-3 rounded-lg cursor-pointer ${
                    pathname === "/" ? "bg-gray-100" : ""
                  }`}
                >
                  <House className="w-4 h-4 mr-2" />
                  <span>홈</span>
                </div>
                <div
                  onClick={() => router.push("/record")}
                  className={`p-3 text-lg font-semibold items-center hover:bg-gray-100 h-10 flex mx-3 mt-1 rounded-lg cursor-pointer ${
                    pathname === "/record" ? "bg-gray-100" : ""
                  }`}
                >
                  <Mic className="w-4 h-4 mr-2" />
                  <span>녹음</span>
                </div>
              </>
            )}
          </div>

          {/* Content area */}
          <div className="flex-1 flex flex-col min-h-0">
            {renderCollapsedIcons()}
            {/* Meeting Notes folder header - fixed */}
            {!isCollapsed && (
              <div className="flex-shrink-0">
                {filteredSidebarItems
                  .filter((item) => item.type === "folder")
                  .map((item) => (
                    <div key={item.id}>
                      <div className="flex items-center transition-all duration-150 p-3 text-lg font-semibold h-10 mx-3 mt-3 rounded-lg">
                        <NotepadText className="w-4 h-4 mr-2 text-gray-600" />
                        <span className="text-gray-700">{item.title}</span>
                        {searchQuery &&
                          item.id === "meetings" &&
                          isSearching && (
                            <span className="ml-2 text-xs text-blue-500 animate-pulse">
                              검색 중…
                            </span>
                          )}
                      </div>
                    </div>
                  ))}
              </div>
            )}

            {/* Scrollable meeting items */}
            {!isCollapsed && (
              <div className="flex-1 overflow-y-auto custom-scrollbar min-h-0">
                {filteredSidebarItems
                  .filter(
                    (item) =>
                      item.type === "folder" &&
                      expandedFolders.has(item.id) &&
                      item.children,
                  )
                  .map((item) => (
                    <div key={`${item.id}-children`} className="mx-3">
                      {item.children!.map((child) => renderItem(child, 1))}
                    </div>
                  ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        {!isCollapsed && (
          <div className="flex-shrink-0 p-2 border-t border-gray-100">
            <button
              onClick={() => router.push("/settings")}
              className="w-full flex items-center justify-center px-3 py-1.5 mt-1 mb-1 text-sm font-medium text-gray-700 bg-gray-200 hover:bg-gray-300 rounded-lg transition-colors shadow-sm"
            >
              <Settings className="w-4 h-4 mr-2" />
              <span>설정</span>
            </button>
            <Info isCollapsed={isCollapsed} />
            <div className="my-1 h-px w-full bg-gray-200" aria-hidden />
            {/* User card → 프로필 진입점. Whole row is clickable; logout
                lives inside the profile page now, not here. */}
            <button
              type="button"
              onClick={() => router.push("/profile")}
              aria-label="프로필 열기"
              className={`mt-2 flex w-full items-center gap-2 rounded-lg border bg-white px-2 py-1 text-left transition-colors hover:bg-gray-50 ${
                pathname === "/profile"
                  ? "border-blue-200 bg-blue-50"
                  : "border-gray-200"
              }`}
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-semibold text-gray-700">
                {userInitials}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-gray-700">
                  {userDisplayName}
                </div>
                {user?.email ? (
                  <div className="truncate text-xs text-gray-500">
                    {user.email}
                  </div>
                ) : null}
              </div>
            </button>
          </div>
        )}

        {/* Collapsed-state profile entry — sits where the logout button used
            to live, anchored to the bottom of the sidebar. */}
        {isCollapsed && (
          <div className="flex-shrink-0 p-2 border-t border-gray-100">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => router.push("/profile")}
                    className={`w-full flex items-center justify-center p-2 rounded-lg transition-colors ${
                      pathname === "/profile"
                        ? "bg-gray-100"
                        : "hover:bg-gray-100"
                    }`}
                    aria-label="프로필"
                  >
                    <UserRound className="w-5 h-5 text-gray-600" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">
                  <p>프로필</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        )}
      </div>

      {/* Confirmation Modal for Delete */}
      <ConfirmationModal
        isOpen={deleteModalState.isOpen}
        text="이 회의를 삭제하시겠습니까? 삭제한 내용은 되돌릴 수 없습니다."
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteModalState({ isOpen: false, itemId: null })}
      />

      {/* Edit Meeting Title Modal */}
      <Dialog
        open={editModalState.isOpen}
        onOpenChange={(open) => {
          if (!open) handleEditCancel()
        }}
      >
        <DialogContent className="sm:max-w-[425px]">
          <VisuallyHidden>
            <DialogTitle>회의 제목 편집</DialogTitle>
          </VisuallyHidden>
          <div className="py-4">
            <h3 className="text-lg font-semibold mb-4">회의 제목 편집</h3>
            <div className="space-y-4">
              <div>
                <label
                  htmlFor="meeting-title"
                  className="block text-sm font-medium text-gray-700 mb-2"
                >
                  회의 제목
                </label>
                <input
                  id="meeting-title"
                  type="text"
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleEditConfirm()
                    } else if (e.key === "Escape") {
                      handleEditCancel()
                    }
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="회의 제목을 입력하세요"
                  autoFocus
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <button
              onClick={handleEditCancel}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
            >
              취소
            </button>
            <button
              onClick={handleEditConfirm}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors"
            >
              저장
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

export default Sidebar
