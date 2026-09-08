<script setup>
defineProps({
  conversations: Array,
  selectedId: String,
})

const emit = defineEmits(['select', 'delete'])

function getLastAnswer(conv) {
  if (!conv.messages || conv.messages.length === 0) return '暂无答复'
  const lastAi = [...conv.messages].reverse().find(m => m.role === 'assistant')
  return lastAi ? lastAi.content : '单轮问答'
}
</script>

<template>
  <div class="history-list">
    <div v-if="conversations.length === 0" class="list-empty">
      <el-empty description="暂无匹配会话" :image-size="48" />
    </div>
    <div
      v-for="conv in conversations"
      :key="conv.sessionId"
      :class="['history-item', { active: conv.sessionId === selectedId }]"
      @click="emit('select', conv)"
    >
      <div class="item-main">
        <div class="item-top">
          <span class="item-status history">
            {{ (conv.userMsgCount || 1) + ' 轮对话' }}
          </span>
          <span class="item-time">{{ conv.timestamp }}</span>
        </div>
        <div class="item-question">{{ conv.title }}</div>
        <div class="item-preview">{{ getLastAnswer(conv).slice(0, 70) }}{{ getLastAnswer(conv).length > 70 ? '...' : '' }}</div>
      </div>
      <div class="item-actions">
        <el-button
          text
          size="small"
          class="hover-action"
          @click.stop="emit('delete', conv.sessionId)"
        >
          <el-icon :size="14"><Delete /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 12px 12px;
}

.list-empty {
  padding: 40px 0;
}

.history-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 14px;
  border-radius: var(--radius-lg);
  cursor: pointer;
  margin-bottom: 4px;
  transition: background-color 0.2s;
}

.history-item:hover {
  background-color: var(--color-surface-low);
}

.history-item.active {
  background-color: #f1f5f9;
  border-left: 3px solid var(--color-primary);
}

.item-main {
  flex: 1;
  overflow: hidden;
  min-width: 0;
}

.item-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.item-status {
  font: var(--text-metadata);
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  text-transform: none;
  letter-spacing: 0;
}

.item-status.success {
  color: var(--color-success-text);
  background: var(--color-success-bg);
}

.item-status.history {
  color: var(--color-secondary);
  background: var(--color-surface-low);
}

.item-time {
  font: var(--text-metadata);
  color: #a8abb2;
  text-transform: none;
  letter-spacing: 0;
}

.item-question {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.item-preview {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-actions {
  opacity: 0;
  transition: opacity 0.2s;
  flex-shrink: 0;
}

.history-item:hover .item-actions {
  opacity: 1;
}

.hover-action {
  color: var(--color-error-text);
}
</style>
