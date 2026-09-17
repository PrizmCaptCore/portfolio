// Downloads Xenova/all-MiniLM-L6-v2 (the embedding model used by
// graphService.ts) into frontend/public/models/Xenova/all-MiniLM-L6-v2/ so the
// Tauri bundle can load it offline via transformers.js localModelPath.
//
// Idempotent: skips files already present. Run as `pnpm setup:embedding-model`
// or transitively via `pnpm prebuild`.

import { createWriteStream, existsSync, mkdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { pipeline as streamPipeline } from 'node:stream/promises'
import { fileURLToPath } from 'node:url'

const MODEL_ID = 'Xenova/all-MiniLM-L6-v2'
const BASE_URL = `https://huggingface.co/${MODEL_ID}/resolve/main`

// graphService.ts calls pipeline(..., { dtype: 'fp32' }) — that maps to
// onnx/model.onnx, not model_quantized.onnx. Keep the set minimal so the
// download is ~90MB instead of pulling every variant.
const FILES = [
  'config.json',
  'tokenizer.json',
  'tokenizer_config.json',
  'onnx/model.onnx',
]

const outRoot = fileURLToPath(new URL(`../public/models/${MODEL_ID}/`, import.meta.url))

async function download(url, dst) {
  const res = await fetch(url)
  if (!res.ok || !res.body) {
    throw new Error(`GET ${url} -> ${res.status} ${res.statusText}`)
  }
  mkdirSync(dirname(dst), { recursive: true })
  await streamPipeline(res.body, createWriteStream(dst))
}

for (const f of FILES) {
  const dst = join(outRoot, f)
  if (existsSync(dst) && statSync(dst).size > 0) {
    console.log(`[download-embedding-model] skip ${f} (already present)`)
    continue
  }
  const url = `${BASE_URL}/${f}`
  process.stdout.write(`[download-embedding-model] GET ${url} ... `)
  await download(url, dst)
  const mb = (statSync(dst).size / 1024 / 1024).toFixed(1)
  console.log(`ok (${mb} MB)`)
}

console.log('[download-embedding-model] done')
