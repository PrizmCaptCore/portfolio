/**
 * Update Service
 *
 * Handles automatic software updates using Tauri updater plugin.
 * Provides update checking, downloading, and installation functionality.
 */

import { relaunch } from '@tauri-apps/plugin-process';
import { getVersion } from '@tauri-apps/api/app';
import { check, Update } from '@tauri-apps/plugin-updater';

export interface UpdateInfo {
  available: boolean;
  currentVersion: string;
  version?: string;
  date?: string;
  body?: string;
  downloadUrl?: string;
}

export interface UpdateProgress {
  downloaded: number;
  total: number;
  percentage: number;
}

/**
 * Update Service
 * Singleton service for managing app updates via tauri-plugin-updater.
 * The plugin checks the endpoint configured in tauri.conf.json
 * (`/api/v1/updates/check/` on our gateway) and verifies the bundle
 * signature against the embedded public key before installing.
 */
export class UpdateService {
  private updateCheckInProgress = false;
  private lastCheckTime: number | null = null;
  private readonly CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000; // 24 hours
  // Cache the Update handle returned by check() so a follow-up
  // downloadAndInstall doesn't have to re-fetch the manifest.
  private pendingUpdate: Update | null = null;

  async checkForUpdates(force = false): Promise<UpdateInfo> {
    if (this.updateCheckInProgress) {
      throw new Error('Update check already in progress');
    }
    if (!force && this.lastCheckTime) {
      const timeSinceLastCheck = Date.now() - this.lastCheckTime;
      if (timeSinceLastCheck < this.CHECK_INTERVAL_MS) {
        return {
          available: false,
          currentVersion: await getVersion(),
        };
      }
    }
    this.updateCheckInProgress = true;
    this.lastCheckTime = Date.now();

    try {
      const currentVersion = await getVersion();
      const update = await check();
      if (update) {
        this.pendingUpdate = update;
        return {
          available: true,
          currentVersion,
          version: update.version,
          date: update.date,
          body: update.body,
        };
      }
      this.pendingUpdate = null;
      return { available: false, currentVersion };
    } catch (error) {
      console.error('Failed to check for updates:', error);
      throw error;
    } finally {
      this.updateCheckInProgress = false;
    }
  }

  async downloadAndInstall(
    onProgress?: (progress: UpdateProgress) => void,
  ): Promise<void> {
    const update = this.pendingUpdate ?? (await check());
    if (!update) {
      throw new Error('No update available');
    }
    let total = 0;
    let downloaded = 0;
    try {
      await update.downloadAndInstall((event) => {
        if (event.event === 'Started') {
          total = event.data.contentLength ?? 0;
        } else if (event.event === 'Progress') {
          downloaded += event.data.chunkLength;
          if (onProgress && total > 0) {
            onProgress({
              downloaded,
              total,
              percentage: Math.round((downloaded / total) * 100),
            });
          }
        }
      });
      await relaunch();
    } catch (error) {
      console.error('Failed to download/install update:', error);
      throw error;
    } finally {
      this.pendingUpdate = null;
    }
  }

  /**
   * Get the current app version
   * @returns Promise with version string
   */
  async getCurrentVersion(): Promise<string> {
    return getVersion();
  }

  /**
   * Check if an update check was performed recently
   * @returns true if checked within the interval
   */
  wasCheckedRecently(): boolean {
    if (!this.lastCheckTime) return false;
    const timeSinceLastCheck = Date.now() - this.lastCheckTime;
    return timeSinceLastCheck < this.CHECK_INTERVAL_MS;
  }
}

// Export singleton instance
export const updateService = new UpdateService();
