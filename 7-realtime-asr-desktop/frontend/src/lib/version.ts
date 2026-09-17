import { getVersion } from '@tauri-apps/api/app'

// The three source-of-truth files (package.json, tauri.conf.json, Cargo.toml)
// carry this placeholder locally. Release CI rewrites them to the tag's real
// version before `tauri build` runs — see .github/workflows/release.yml
// ("Sync version from tag"). Anything still matching this sentinel at runtime
// means we're in a dev / unreleased build.
const DEV_VERSION_PLACEHOLDER = '0.0.0-dev'
const DEV_DISPLAY_LABEL = 'DEMO'

function isDevBuild(raw: string): boolean {
  // Strict match against the placeholder; also treat any "0.0.0-*" pre-release
  // as dev so an accidental `0.0.0-rc1` still shows DEMO rather than leaking.
  return raw === DEV_VERSION_PLACEHOLDER || raw.startsWith('0.0.0')
}

/**
 * Version string intended for user-facing display (About page, sidebar,
 * analytics preview modal). Returns `"DEMO"` for local / unreleased builds;
 * returns the real semver string for release builds.
 */
export async function getDisplayVersion(): Promise<string> {
  try {
    const raw = await getVersion()
    return isDevBuild(raw) ? DEV_DISPLAY_LABEL : raw
  } catch {
    return DEV_DISPLAY_LABEL
  }
}

/**
 * Raw version from the Tauri runtime, unconditioned. Use for internal
 * plumbing that must carry an accurate version: the updater endpoint's
 * `current_version` query param and telemetry/analytics event payloads.
 */
export async function getBuildVersion(): Promise<string> {
  return getVersion()
}
