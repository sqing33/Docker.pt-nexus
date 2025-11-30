export interface SiteData {
  uploaded: number
  comment: string
  migration: number
  state: string
  seeders: number
}

export interface Torrent {
  unique_id: string
  name: string
  save_path: string
  size: number
  size_formatted: string
  progress: number
  state: string
  sites: Record<string, SiteData>
  total_uploaded: number
  total_uploaded_formatted: string
  seeders: number
  downloaderId?: string
  downloaderIds?: string[]
  target_sites_count?: number
}

export interface ISourceInfo {
  name: string
  site: string
  torrentId: string
}

export interface Downloader {
  id: string
  name: string
  enabled: boolean
}