export interface TranscriptModelProps {
  provider: string;
  model: string;
  apiKey?: string | null;
}

export interface TranscriptSettingsProps {
  transcriptModelConfig: TranscriptModelProps;
  setTranscriptModelConfig: (config: TranscriptModelProps) => void;
  onModelSelect?: () => void;
}

// The transcription engine is fixed — no user-facing choice, no model name
// displayed. The backend provider/model identifiers are resolved on the Rust
// side when the recording starts, so this component renders an empty shell
// that callers (e.g., the legacy "model selector" modal) can still mount
// without exposing anything.
export function TranscriptSettings(_props: TranscriptSettingsProps) {
  return <div />;
}
