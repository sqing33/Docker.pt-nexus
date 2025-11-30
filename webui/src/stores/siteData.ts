import { defineStore } from 'pinia'
import type { Torrent, Downloader } from '@/types'

interface SiteDataState {
  dialogVisible: boolean
  currentTorrent: Torrent | null
  downloadersMap: Map<string, string>
  allDownloaders: Downloader[]
}

export const useSiteDataStore = defineStore('siteData', {
  state: (): SiteDataState => ({
    dialogVisible: false,
    currentTorrent: null,
    downloadersMap: new Map(),
    allDownloaders: [],
  }),

  actions: {
    openDialog(torrent: Torrent, allDownloaders?: Downloader[]) {
      this.currentTorrent = torrent
      this.dialogVisible = true

      // Store all downloaders
      this.allDownloaders = allDownloaders || []

      // Build downloaders map for name lookup
      this.downloadersMap.clear()
      if (allDownloaders) {
        allDownloaders.forEach(downloader => {
          this.downloadersMap.set(downloader.id, downloader.name)
        })
      }
    },

    closeDialog() {
      this.dialogVisible = false
      this.currentTorrent = null
      this.downloadersMap.clear()
      this.allDownloaders = []
    },

    setCurrentTorrent(torrent: Torrent | null) {
      this.currentTorrent = torrent
    },

    getDownloaderName(downloaderId: string): string {
      return this.downloadersMap.get(downloaderId) || '未知下载器'
    },

    getAllDownloaders(): Downloader[] {
      return this.allDownloaders
    },
  },
})