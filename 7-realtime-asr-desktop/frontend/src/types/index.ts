export interface Message {
  id: string;
  content: string;
  timestamp: string;
}

export interface Transcript {
  id: string;
  text: string;
  timestamp: string; // Wall-clock time (e.g., "14:30:05")
  source?: string; // "Me" (mic dominant) or "Speaker" (system audio dominant)
  sequence_id?: number;
  chunk_start_time?: number; // Legacy field
  is_partial?: boolean;
  confidence?: number;
  // Recording-relative timestamps for playback sync
  audio_start_time?: number; // Seconds from recording start (e.g., 125.3)
  audio_end_time?: number;   // Seconds from recording start (e.g., 128.6)
  duration?: number;          // Segment duration in seconds (e.g., 3.3)
  /** ISO 639-1 language code from Whisper auto-detect ("en", "ko", ...).
      Used to translate only when the detected language differs from the user's language. */
  detected_language?: string;
  /** Trailing portion of `text` that is still volatile (CNN STT partials re-decode the
      tail every emission). The committed prefix = text minus this suffix. Always undefined
      for finals — Whisper replaces the row entirely. Frontend renders this dimmed/italic. */
  tentative_text?: string;
  /** Live LLM translation (see Language Settings) */
  translated_text?: string;
  translation_pending?: boolean;
  translation_error?: string;
  /** Likely intent / meaning (live assistant) */
  coaching_intent?: string;
  /** Suggested reply lines (live assistant) */
  coaching_replies?: string[];
}

export interface TranscriptUpdate {
  text: string;
  timestamp: string; // Wall-clock time for reference
  source: string;
  sequence_id: number;
  chunk_start_time: number; // Legacy field
  is_partial: boolean;
  confidence: number;
  // Recording-relative timestamps for playback sync
  audio_start_time: number; // Seconds from recording start
  audio_end_time: number;   // Seconds from recording start
  duration: number;          // Segment duration in seconds
  /** ISO 639-1 lang code from Whisper auto-detect. None if provider doesn't expose it. */
  detected_language?: string;
  /** Volatile tail of `text` for partials (stable-prefix commit logic). */
  tentative_text?: string;
}

export interface Block {
  id: string;
  type: string;
  content: string;
  color: string;
}

export interface Section {
  title: string;
  blocks: Block[];
}

export interface Summary {
  [key: string]: Section;
}

export interface ApiResponse {
  message: string;
  num_chunks: number;
  data: any[];
}

export interface SummaryResponse {
  status: string;
  summary: Summary;
  raw_summary?: string;
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

// BlockNote-specific types
export type SummaryFormat = 'legacy' | 'markdown' | 'blocknote';

export interface BlockNoteBlock {
  id: string;
  type: string;
  props?: Record<string, any>;
  content?: any[];
  children?: BlockNoteBlock[];
}

export interface SummaryDataResponse {
  markdown?: string;
  summary_json?: BlockNoteBlock[];
  // Legacy format fields
  MeetingName?: string;
  _section_order?: string[];
  [key: string]: any; // For legacy section data
}

// Pagination types for optimized transcript loading
export interface MeetingMetadata {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  folder_path?: string;
}

export interface PaginatedTranscriptsResponse {
  transcripts: Transcript[];
  total_count: number;
  has_more: boolean;
}

// Transcript segment data for virtualized display
export interface TranscriptSegmentData {
  id: string;
  timestamp: number; // audio_start_time in seconds
  endTime?: number; // audio_end_time in seconds
  text: string;
  source?: string; // "Me" or "Speaker"
  /** When false, show full text immediately (no typewriter). */
  is_partial?: boolean;
  confidence?: number;
  /** Volatile tail of `text` for partials. Renderer dims this suffix. */
  tentative_text?: string;
  translated_text?: string;
  translation_pending?: boolean;
  translation_error?: string;
  coaching_intent?: string;
  coaching_replies?: string[];
}

/** Tauri `api_live_assist_transcript_segment` result (camelCase). `translation` is always empty. */
export interface LiveAssistResult {
  translation: string;
  intentSummary: string;
  replyIdeas: string[];
}
