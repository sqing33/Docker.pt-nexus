<!-- src/views/LocalQueryView.vue -->
<template>
  <div class="local-query-container">
    <el-card class="query-card">
      <template #header>
        <div class="card-header">
          <span>数据检索</span>
        </div>
      </template>
      <div class="placeholder-content">
        <el-empty description="功能开发中，敬请期待" />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
// 占位页面，后续添加实际功能
</script>

<style scoped>
.local-query-container {
  padding: 20px;
  height: 100%;
  overflow: auto;
}

.query-card {
  height: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.placeholder-content {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
}
</style>
