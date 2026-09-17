// Historically this app let users pick among several summary LLM providers
// (OpenAI, Claude, Groq, OpenRouter, RelayAI). Now every summary runs
// through the Relay gateway via the relay-ai code path, so we expose
// only that single value and normalize any legacy stored provider onto it.
// Keeping the `SupportedSummaryProvider` type for backwards-compat with
// existing type signatures in ModelConfig; the set is intentionally minimal.
export const SUPPORTED_SUMMARY_PROVIDERS = ['relay-ai'] as const

export type SupportedSummaryProvider = (typeof SUPPORTED_SUMMARY_PROVIDERS)[number]

export function normalizeSummaryProvider(_provider?: string | null): SupportedSummaryProvider {
  // Any stored provider (claude / openai / groq / openrouter / null / unknown)
  // is forced onto relay-ai. Old rows with other values are silently
  // migrated at read time without requiring a DB backfill.
  return 'relay-ai'
}
