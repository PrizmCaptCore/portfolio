/**
 * Local dev build helper. Patches tauri.conf.json before building and restores it after.
 *
 * Patches applied:
 *   - version: 0.0.0-dev → 0.0.1  (Windows MSI requires numeric-only versions)
 *   - plugins.updater.pubkey: removed  (no signing key locally; updater not needed for dev)
 */
import { execSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const confPath = join(__dirname, '..', 'src-tauri', 'tauri.conf.json')

const original = readFileSync(confPath, 'utf8')
const conf = JSON.parse(original)

function restore() {
  writeFileSync(confPath, original)
  console.log('[build-local] tauri.conf.json restored')
}

conf.version = '0.0.1'
if (conf.plugins?.updater?.pubkey) {
  delete conf.plugins.updater.pubkey
}
writeFileSync(confPath, JSON.stringify(conf, null, 2) + '\n')
console.log('[build-local] patched: version → 0.0.1, updater pubkey removed')

try {
  execSync('pnpm tauri build', { stdio: 'inherit' })
} finally {
  restore()
}
