// src/types/crossSeed.ts

import { defineStore } from 'pinia'

/**
 * Interface for the source site information used during cross-seeding.
 */
interface ISourceInfo {
  /**
   * The site's nickname, e.g., 'MTeam'.
   * This is used for display purposes.
   */
  name: string;

  /**
   * The site's internal identifier, e.g., 'mteam'.
   * This is used for API calls.
   */
  site: string;

  /**
   * The torrent ID on the source site.
   */
  torrentId: string;
}

// Pinia 存储
export const useCrossSeedStore = defineStore('crossSeed', {
  state: () => ({
    taskId: null as string | null,
    sourceInfo: null as ISourceInfo | null,
    workingParams: null as object | null, // 使用 object 类型以避免循环依赖
  }),
  actions: {
    /**
     * 设置任务 ID。
     *
     * @param {string} id - The task ID to set.
     */
    setTaskId(id: string) {
      this.taskId = id
    },

    /**
     * 清除任务 ID。
     */
    clearTaskId() {
      this.taskId = null
    },

    /**
     * 设置源信息。
     */
    setSourceInfo(info: ISourceInfo) {
      this.sourceInfo = info
    },

    /**
     * 清除源信息。
     */
    clearSourceInfo() {
      this.sourceInfo = null
    },

    /**
     * 设置工作参数。
     */
    setParams(params: object) {
      this.workingParams = params
    },

    /**
     * 清除工作参数。
     */
    clearParams() {
      this.workingParams = null
    },

    /**
     * 重置所有状态。
     */
    reset() {
      this.clearTaskId()
      this.clearSourceInfo()
      this.clearParams()
    },
  },
})
