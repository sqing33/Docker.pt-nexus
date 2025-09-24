// src/stores/crossSeed.ts
import { defineStore } from 'pinia'
import type { ISourceInfo } from '@/types'

export const useCrossSeedStore = defineStore('crossSeed', {
  state: () => ({
    // 工作中的参数，在修改和预览间保持同步
    workingParams: null as any | null,
    currentStep: 'edit', // 'edit' | 'preview' | 'publish'
    taskId: null as string | null,
    sourceInfo: null as ISourceInfo | null,
  }),

  actions: {
    // 批量更新
    setParams(params: any) {
      this.workingParams = { ...this.workingParams, ...params }
    },

    // 更新参数
    updateParam(key: string, value: any) {
      if (this.workingParams) {
        this.workingParams[key] = value
      }
    },

    // 设置任务ID
    setTaskId(taskId: string) {
      this.taskId = taskId
    },

    // 设置源信息
    setSourceInfo(info: ISourceInfo) {
      this.sourceInfo = info
    },

    // 切换到预览
    goToPreview() {
      this.currentStep = 'preview'
    },

    // 返回编辑
    backToEdit() {
      this.currentStep = 'edit'
    },

    // 重置状态
    reset() {
      this.workingParams = null
      this.currentStep = 'edit'
      this.taskId = null
      this.sourceInfo = null
    },
  },
})
