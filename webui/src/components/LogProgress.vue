<template>
  <div v-if="visible" class="log-progress-overlay">
    <div class="log-progress-container">
      <div class="steps-wrapper">
        <el-steps direction="vertical" :active="activeStepIndex" finish-status="success">
          <el-step
            v-for="(step, index) in allSteps"
            :key="index"
            :title="step.name"
            :description="step.message"
            :status="getStepStatus(step)"
          >
            <template #icon>
              <div v-if="step.status === 'processing'" class="spinner-icon">
                <el-icon class="is-loading"><Loading /></el-icon>
              </div>
              <div v-else-if="step.status === 'success'" class="success-icon">
                <el-icon><CircleCheck /></el-icon>
              </div>
              <div v-else-if="step.status === 'error'" class="error-icon">
                <el-icon><CircleClose /></el-icon>
              </div>
              <div v-else-if="step.status === 'warning'" class="warning-icon">
                <el-icon><Warning /></el-icon>
              </div>
            </template>
          </el-step>
        </el-steps>
        
        <div v-if="isComplete" class="completion-message">
          <el-icon class="icon-complete" color="#67C23A"><CircleCheck /></el-icon>
          <span>所有步骤已完成</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { Loading, CircleCheck, CircleClose, Warning } from '@element-plus/icons-vue'

interface Step {
  name: string
  message?: string
  status: 'pending' | 'processing' | 'success' | 'error' | 'warning'
}

const props = defineProps<{
  visible: boolean
  taskId: string
}>()

const emit = defineEmits<{
  (e: 'complete'): void
  (e: 'close'): void
}>()

// 预定义所有步骤
const allSteps = ref<Step[]>([
  { name: '数据库查询', message: '正在检查缓存...', status: 'pending' },
  { name: '开始抓取', message: '准备从源站点获取...', status: 'pending' },
  { name: '获取种子信息', message: '', status: 'pending' },
  { name: '解析参数', message: '', status: 'pending' },
  { name: '验证图片链接', message: '', status: 'pending' },
  { name: '提取媒体信息', message: '', status: 'pending' },
  { name: '验证简介格式', message: '', status: 'pending' },
  { name: '检查声明感谢', message: '', status: 'pending' },
  { name: '成功获取参数', message: '', status: 'pending' }
])

const isComplete = ref(false)
let eventSource: EventSource | null = null

// 计算当前激活的步骤索引
const activeStepIndex = computed(() => {
  const processingIndex = allSteps.value.findIndex(s => s.status === 'processing')
  if (processingIndex !== -1) return processingIndex
  
  const successCount = allSteps.value.filter(s => s.status === 'success').length
  return successCount
})

// 获取步骤状态
const getStepStatus = (step: Step) => {
  if (step.status === 'success') return 'success'
  if (step.status === 'error') return 'error'
  if (step.status === 'warning') return 'warning'
  if (step.status === 'processing') return 'process'
  return 'wait'
}

// 监听 taskId 变化
watch(() => props.taskId, (newTaskId) => {
  if (newTaskId && props.visible) {
    connectSSE()
  }
})

// 监听 visible 变化
watch(() => props.visible, (newVisible) => {
  if (newVisible && props.taskId) {
    connectSSE()
  } else if (!newVisible) {
    disconnectSSE()
  }
})

onMounted(() => {
  if (props.visible && props.taskId) {
    connectSSE()
  }
})

onUnmounted(() => {
  disconnectSSE()
})

const connectSSE = () => {
  // 如果已有连接，先断开
  if (eventSource) {
    eventSource.close()
  }

  // 重置状态
  isComplete.value = false
  // 重置所有步骤为 pending 状态
  allSteps.value.forEach(step => {
    step.status = 'pending'
    step.message = step.name === '数据库查询' ? '正在检查缓存...' : 
                   step.name === '开始抓取' ? '准备从源站点获取...' : ''
  })

  // 创建新的 SSE 连接
  eventSource = new EventSource(`/api/migrate/logs/stream/${props.taskId}`)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)

      if (data.type === 'connected') {
        console.log('SSE 连接成功', data)
      } else if (data.type === 'log') {
        updateStep(data.step, data.message, data.status)
      } else if (data.type === 'complete') {
        isComplete.value = true
        emit('complete')
        disconnectSSE()
        emit('close')
      } else if (data.type === 'heartbeat') {
        // 心跳，保持连接
      }
    } catch (error) {
      console.error('解析 SSE 消息失败:', error)
    }
  }

  eventSource.onerror = (error) => {
    console.error('SSE 连接错误:', error)
    disconnectSSE()
  }
}

const disconnectSSE = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

const updateStep = (stepName: string, message: string, status: string) => {
  const stepIndex = allSteps.value.findIndex((s: Step) => s.name === stepName)
  
  if (stepIndex !== -1) {
    const currentStep = allSteps.value[stepIndex]
    currentStep.message = message
    currentStep.status = status as Step['status']
    
    // 当前步骤完成时，将下一个步骤设置为 processing 状态
    if (status === 'success' && stepIndex < allSteps.value.length - 1) {
      const nextStep = allSteps.value[stepIndex + 1]
      if (nextStep.status === 'pending') {
        nextStep.status = 'processing'
      }
    }
  }
}
</script>

<style scoped>
/* 透明遮罩层覆盖整个CrossSeedPanel区域 */
.log-progress-overlay {
  position: absolute;
  top: 43px;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(2px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.log-progress-container {
  width: 600px;
  max-width: 90%;
  max-height: 80vh;
  background: white;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}

.steps-wrapper {
  padding: 24px;
  max-height: 500px;
  overflow-y: auto;
}

/* Element Plus Steps 自定义样式 */
:deep(.el-step__main) {
  display: flex;
}

:deep(.el-step__title) {
  font-size: 15px;
  font-weight: 500;
  width:150px;
  line-height: 32px!important;
}

:deep(.el-step__description) {
  font-size: 13px;
  margin-top:0;
  line-height: 32px;
}

:deep(.el-step__icon) {
  width: 32px;
  height: 32px;
}

:deep(.el-step.is-wait .el-step__title) {
  color: #909399;
}

:deep(.el-step.is-wait .el-step__description) {
  color: #c0c4cc;
}

:deep(.el-step.is-process .el-step__title) {
  color: #409eff;
  font-weight: 600;
}

:deep(.el-step.is-process .el-step__description) {
  color: #409eff;
}

:deep(.el-step.is-success .el-step__title) {
  color: #67c23a;
}

:deep(.el-step.is-success .el-step__description) {
  color: #95d475;
}

:deep(.el-step.is-error .el-step__title) {
  color: #f56c6c;
}

:deep(.el-step.is-error .el-step__description) {
  color: #f56c6c;
}

.spinner-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.success-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #67c23a;
  font-size: 20px;
}

.error-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #f56c6c;
  font-size: 20px;
}

.warning-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #e6a23c;
  font-size: 20px;
}

.completion-message {
  margin-top: 24px;
  padding: 16px;
  background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
  border-radius: 8px;
  color: #2e7d32;
  font-weight: 600;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 2px 8px rgba(103, 194, 58, 0.15);
}

.icon-complete {
  font-size: 22px;
}

/* 滚动条样式 */
.steps-wrapper::-webkit-scrollbar {
  width: 6px;
}

.steps-wrapper::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.steps-wrapper::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.steps-wrapper::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

</style>
