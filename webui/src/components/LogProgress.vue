<template>
  <div v-if="visible" class="log-progress-container">
    <div class="log-progress-header">
      <h3>处理进度</h3>
      <button @click="$emit('close')" class="close-btn" title="关闭">×</button>
    </div>
    <div class="log-progress-content">
      <div
        v-for="(step, index) in steps"
        :key="index"
        class="step-item"
        :class="{ 
          'step-processing': step.status === 'processing',
          'step-success': step.status === 'success',
          'step-error': step.status === 'error',
          'step-warning': step.status === 'warning'
        }"
      >
        <span class="step-icon">
          <i v-if="step.status === 'success'" class="icon-check">✓</i>
          <i v-else-if="step.status === 'error'" class="icon-error">✗</i>
          <i v-else-if="step.status === 'warning'" class="icon-warning">!</i>
          <i v-else-if="step.status === 'processing'" class="icon-spinner">○</i>
          <span v-else class="step-number">{{ index + 1 }}</span>
        </span>
        <div class="step-content">
          <span class="step-name">{{ step.name }}</span>
          <span v-if="step.message" class="step-message">{{ step.message }}</span>
        </div>
      </div>
      <div v-if="isComplete" class="completion-message">
        <i class="icon-complete">✓</i> 所有步骤已完成
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'

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

const steps = ref<Step[]>([])
const isComplete = ref(false)
let eventSource: EventSource | null = null

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
  steps.value = []
  isComplete.value = false

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

        // 等待3秒后再断开连接和关闭弹窗
        setTimeout(() => {
          isComplete.value = true
          emit('complete')
          disconnectSSE()
          emit('close')
        }, 300000)
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
  const existingStep = steps.value.find(s => s.name === stepName)
  if (existingStep) {
    existingStep.message = message
    existingStep.status = status as Step['status']
  } else {
    steps.value.push({
      name: stepName,
      message,
      status: status as Step['status']
    })
  }
}
</script>

<style scoped>
.log-progress-container {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 500px;
  max-width: 90vw;
  max-height: 80vh;
  background: white;
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  z-index: 9999;
  display: flex;
  flex-direction: column;
}

.log-progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e0e0e0;
}

.log-progress-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.close-btn {
  background: none;
  border: none;
  font-size: 28px;
  line-height: 1;
  color: #999;
  cursor: pointer;
  padding: 0;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #f5f5f5;
  color: #666;
}

.log-progress-content {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.step-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
  transition: all 0.3s;
}

.step-item:last-child {
  border-bottom: none;
}

.step-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 14px;
  font-weight: bold;
  background: #e0e0e0;
  color: #666;
}

.step-processing .step-icon {
  background: #2196F3;
  color: white;
}

.step-success .step-icon {
  background: #4CAF50;
  color: white;
}

.step-error .step-icon {
  background: #f44336;
  color: white;
}

.step-warning .step-icon {
  background: #ff9800;
  color: white;
}

.icon-spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.step-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.step-name {
  font-weight: 600;
  color: #333;
  font-size: 14px;
}

.step-message {
  font-size: 13px;
  color: #666;
  line-height: 1.4;
}

.step-processing .step-message {
  color: #2196F3;
}

.step-success .step-message {
  color: #4CAF50;
}

.step-error .step-message {
  color: #f44336;
}

.step-warning .step-message {
  color: #ff9800;
}

.completion-message {
  margin-top: 16px;
  padding: 12px;
  background: #e8f5e9;
  border-radius: 4px;
  color: #2e7d32;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.icon-complete {
  font-size: 18px;
}

.step-number {
  font-size: 12px;
}

/* 添加遮罩层 */
.log-progress-container::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: -1;
}
</style>
