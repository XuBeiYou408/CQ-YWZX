<script setup>
import MessageBubble from './MessageBubble.vue'

defineProps({
  conversation: Object,
})

const emit = defineEmits(['resume'])
</script>

<template>
  <div class="history-detail">
    <div class="detail-inner">
      <div class="detail-header">
        <div class="header-info">
          <h3 class="session-title">{{ conversation.title || '历史对话' }}</h3>
          <span class="session-meta">
            创建于 {{ conversation.timestamp }} · 共 {{ conversation.messages?.length || 0 }} 条消息
          </span>
        </div>
        <div class="header-actions">
          <el-button type="primary" size="default" class="resume-btn" @click="emit('resume', conversation.sessionId)">
            <el-icon style="margin-right: 4px"><ChatDotRound /></el-icon>
            恢复并继续对话
          </el-button>
        </div>
      </div>

      <div class="messages-flow">
        <MessageBubble
          v-for="(msg, idx) in conversation.messages"
          :key="idx"
          :message="msg"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-detail {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 24px 32px;
  overflow-y: auto;
}

.detail-inner {
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--color-outline-variant, #e4e7ed);
}

.session-title {
  margin: 0 0 4px 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.session-meta {
  font-size: 12px;
  color: #9ca3af;
}

.resume-btn {
  border-radius: var(--radius-md, 6px);
}

.messages-flow {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
