// Copies the onnxruntime-web WASM runtime + its .mjs loaders into
// frontend/public/transformers/ so the Tauri bundle can serve them from
// tauri://localhost/transformers/ at runtime. Required when
// @huggingface/transformers is bundled locally (no CDN fallback).
//
// Runs as a prebuild step — see package.json `prebuild` script.

import { copyFileSync, existsSync, mkdirSync, realpathSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// Files actually referenced by transformers.js 4.x at runtime:
//   - .wasm/.mjs pair — default WASM execution provider
//   - .asyncify.wasm/.mjs pair — WebGPU EP (JS↔WASM async via asyncify)
// `jsep` variants are not used by transformers.js 4.x; omitting them.
const ORT_FILES = [
  'ort-wasm-simd-threaded.wasm',
  'ort-wasm-simd-threaded.mjs',
  'ort-wasm-simd-threaded.asyncify.wasm',
  'ort-wasm-simd-threaded.asyncify.mjs',
]

// onnxruntime-web is a transitive dep of @huggingface/transformers and, under
// pnpm's hoisting, isn't resolvable from the project root. Resolve via the
// pnpm layout: .pnpm/@huggingface+transformers@*/node_modules/onnxruntime-web.
const frontendDir = dirname(dirname(fileURLToPath(import.meta.url)))
const transformersReal = realpathSync(join(frontendDir, 'node_modules/@huggingface/transformers'))
const peerNodeModules = dirname(dirname(transformersReal))
const ortDist = join(peerNodeModules, 'onnxruntime-web/dist')
const transformersDist = join(transformersReal, 'dist')
const outDir = fileURLToPath(new URL('../public/transformers/', import.meta.url))

if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true })

function copy(srcDir, name) {
  const src = join(srcDir, name)
  const dst = join(outDir, name)
  if (!existsSync(src)) {
    console.error(`[copy-transformers-wasm] missing: ${src}`)
    process.exit(1)
  }
  copyFileSync(src, dst)
  console.log(`[copy-transformers-wasm] ${name}`)
}

// ORT runtime — loaded by transformers.js via env.backends.onnx.wasm.wasmPaths.
for (const f of ORT_FILES) copy(ortDist, f)
// transformers.js browser bundle — loaded at runtime by graphService.ts so
// webpack never has to parse its ESM source.
// NOTE: must be `transformers.js` (fully self-contained ESM), NOT
// `transformers.web.js` which retains a bare `import "onnxruntime-web/webgpu"`
// that the browser can't resolve without an importmap.
copy(transformersDist, 'transformers.js')
