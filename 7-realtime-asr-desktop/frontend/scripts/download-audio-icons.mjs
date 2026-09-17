// Downloads the MDI icon set subset used by react-h5-audio-player (which
// renders icons via @iconify/react and fetches them from api.iconify.design
// at runtime by default). Baking them into public/icons/ so the desktop
// bundle works fully offline — the CSP then doesn't need to whitelist
// api.iconify.design.
//
// Runs as a prebuild step — see package.json `prebuild` script.

import { createWriteStream, existsSync, mkdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { pipeline as streamPipeline } from 'node:stream/promises'
import { fileURLToPath } from 'node:url'

// Keep in sync with react-h5-audio-player's internal icon names (mdi:*).
const ICONS = [
  'play-circle',
  'pause-circle',
  'rewind',
  'fast-forward',
  'skip-previous',
  'skip-next',
  'repeat',
  'repeat-off',
  'volume-high',
  'volume-mute',
]

const PREFIX = 'mdi'
const OUT_DIR = fileURLToPath(new URL('../public/icons/', import.meta.url))
const OUT_FILE = join(OUT_DIR, `${PREFIX}-audio.json`)

// Iconify's public API hosts the same data on two mirrors. Try the primary
// first and fall back to the secondary so a single host outage doesn't
// break the build.
const HOSTS = ['api.iconify.design', 'api.simplesvg.com']

if (existsSync(OUT_FILE) && statSync(OUT_FILE).size > 0) {
  console.log(`[download-audio-icons] skip (already present: ${OUT_FILE})`)
  // Intentional natural exit — no process.exit() to avoid libuv handle-closing
  // assertion on Windows (UV_HANDLE_CLOSING in src\win\async.c).
} else {
  mkdirSync(OUT_DIR, { recursive: true })

  let lastErr
  for (const host of HOSTS) {
    const url = `https://${host}/${PREFIX}.json?icons=${ICONS.join(',')}`
    try {
      const res = await fetch(url)
      if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`)
      process.stdout.write(`[download-audio-icons] GET ${url} ... `)
      await streamPipeline(res.body, createWriteStream(OUT_FILE))
      const kb = (statSync(OUT_FILE).size / 1024).toFixed(1)
      console.log(`ok (${kb} KB)`)
      lastErr = null
      break
    } catch (e) {
      lastErr = e
      console.warn(`[download-audio-icons] ${host} failed: ${e.message ?? e}`)
    }
  }
  if (lastErr) throw lastErr ?? new Error('all iconify mirrors unreachable')
}
