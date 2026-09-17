"use client"

import {
  ModelConfig,
  ModelSettingsModal,
} from "@/components/ModelSettingsModal"
import {
  Dialog,
  DialogContent,
  DialogTrigger,
  DialogTitle,
} from "@/components/ui/dialog"
import { VisuallyHidden } from "@/components/ui/visually-hidden"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Sparkles,
  Settings,
  Loader2,
  FileText,
  Check,
  Square,
} from "lucide-react"
import Analytics from "@/lib/analytics"
import { useEffect, useState } from "react"

interface SummaryGeneratorButtonGroupProps {
  modelConfig: ModelConfig
  setModelConfig: (
    config: ModelConfig | ((prev: ModelConfig) => ModelConfig),
  ) => void
  onSaveModelConfig: (config?: ModelConfig) => Promise<void>
  onGenerateSummary: (customPrompt: string) => Promise<void>
  onStopGeneration: () => void
  customPrompt: string
  summaryStatus:
    | "idle"
    | "processing"
    | "summarizing"
    | "regenerating"
    | "completed"
    | "error"
  availableTemplates: Array<{ id: string; name: string; description: string }>
  selectedTemplate: string
  onTemplateSelect: (templateId: string, templateName: string) => void
  hasTranscripts?: boolean
  isModelConfigLoading?: boolean
  onOpenModelSettings?: (openFn: () => void) => void
}

export function SummaryGeneratorButtonGroup({
  modelConfig,
  setModelConfig,
  onSaveModelConfig,
  onGenerateSummary,
  onStopGeneration,
  customPrompt,
  summaryStatus,
  availableTemplates,
  selectedTemplate,
  onTemplateSelect,
  hasTranscripts = true,
  isModelConfigLoading = false,
  onOpenModelSettings,
}: SummaryGeneratorButtonGroupProps) {
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false)

  useEffect(() => {
    onOpenModelSettings?.(() => setSettingsDialogOpen(true))
  }, [onOpenModelSettings])

  if (!hasTranscripts) {
    return null
  }

  const isGenerating =
    summaryStatus === "processing" ||
    summaryStatus === "summarizing" ||
    summaryStatus === "regenerating"

  const handleGenerate = async () => {
    // `relay-ai` uses the Relay gateway (server-side resolution), so it
    // doesn't need an endpoint/model configured here. Only non-gateway
    // providers require a named model.
    const needsNamedModel =
      modelConfig.provider !== "relay-ai" && !modelConfig.model?.trim()

    if (needsNamedModel) {
      setSettingsDialogOpen(true)
      return
    }

    Analytics.trackButtonClick("generate_summary", "meeting_details")
    await onGenerateSummary(customPrompt)
  }

  return (
    <ButtonGroup>
      {isGenerating ? (
        <Button
          variant="outline"
          size="sm"
          className="bg-gradient-to-r from-red-50 to-orange-50 hover:from-red-100 hover:to-orange-100 border-red-200 xl:px-4"
          onClick={() => {
            Analytics.trackButtonClick(
              "stop_summary_generation",
              "meeting_details",
            )
            onStopGeneration()
          }}
          title="요약 생성 중지"
        >
          <Square className="xl:mr-2" size={18} fill="currentColor" />
          <span className="hidden lg:inline xl:inline">중지</span>
        </Button>
      ) : (
        <Button
          variant="outline"
          size="sm"
          className="bg-gradient-to-r from-blue-50 to-emerald-50 hover:from-blue-100 hover:to-emerald-100 border-blue-200 xl:px-4"
          onClick={handleGenerate}
          disabled={isModelConfigLoading}
          title={
            isModelConfigLoading
              ? "모델 설정을 불러오는 중…"
              : "AI 요약 생성"
          }
        >
          {isModelConfigLoading ? (
            <>
              <Loader2 className="animate-spin xl:mr-2" size={18} />
              <span className="hidden xl:inline">불러오는 중…</span>
            </>
          ) : (
            <>
              <Sparkles className="xl:mr-2" size={18} />
              <span className="hidden lg:inline xl:inline">
                요약 생성
              </span>
            </>
          )}
        </Button>
      )}

      <Dialog open={settingsDialogOpen} onOpenChange={setSettingsDialogOpen}>
        {/* <DialogTrigger asChild>
          <Button variant="outline" size="sm" title="Summary Settings">
            <Settings />
            <span className="hidden lg:inline">AI Model</span>
          </Button>
        </DialogTrigger> */}
        <DialogContent aria-describedby={undefined}>
          <VisuallyHidden>
            <DialogTitle>모델 설정</DialogTitle>
          </VisuallyHidden>
          <ModelSettingsModal
            onSave={async (config) => {
              await onSaveModelConfig(config)
              setSettingsDialogOpen(false)
            }}
            modelConfig={modelConfig}
            setModelConfig={setModelConfig}
            skipInitialFetch={true}
          />
        </DialogContent>
      </Dialog>

      {availableTemplates.length > 1 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" title="요약 템플릿 선택">
              <FileText />
              <span className="hidden lg:inline">템플릿</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {availableTemplates.map((template) => (
              <DropdownMenuItem
                key={template.id}
                onClick={() => onTemplateSelect(template.id, template.name)}
                title={template.description}
                className="flex items-center justify-between gap-2"
              >
                <span>{template.name}</span>
                {selectedTemplate === template.id && (
                  <Check className="h-4 w-4 text-green-600" />
                )}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </ButtonGroup>
  )
}
