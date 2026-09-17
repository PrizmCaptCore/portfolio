import { invoke } from '@tauri-apps/api/core'

export async function copyToClipboard(text: string): Promise<void> {
  await invoke('copy_to_clipboard', { text })
}
