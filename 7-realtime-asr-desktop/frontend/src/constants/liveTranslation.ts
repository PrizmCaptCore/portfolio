/** Language for live “likely intent” hints (English names work best for models). Reply suggestions stay English. */
export const LIVE_COACHING_INTENT_LANGUAGES = [
  { id: 'en', label: 'English' },
  { id: 'ko', label: 'Korean' },
  { id: 'ja', label: 'Japanese' },
  { id: 'zh', label: 'Chinese' },
  { id: 'es', label: 'Spanish' },
  { id: 'fr', label: 'French' },
  { id: 'de', label: 'German' },
  { id: 'pt', label: 'Portuguese' },
  { id: 'vi', label: 'Vietnamese' },
  { id: 'hi', label: 'Hindi' },
] as const;

export const DEFAULT_LIVE_COACHING_INTENT_LANGUAGE = 'Korean';
