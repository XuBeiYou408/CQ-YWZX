<script setup>
import { ref } from 'vue'

const props = defineProps({
  loading: Boolean,
  streaming: Boolean,
  mode: String,
  searchMode: String,
})

const emit = defineEmits(['send', 'stop', 'toggleMode', 'clear', 'update:searchMode'])

const inputText = ref('')

function handleSend() {
  const text = inputText.value.trim()
  if (!text || props.streaming) return
  emit('send', text)
  inputText.value = ''
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="input-box">
    <div class="input-params">
      <div class="param-group">
        <span class="param-label">搜索模式</span>
        <el-segmented
          :model-value="searchMode"
          :options="[
            { label: '混合搜索', value: 'hybrid' },
            { label: '语义搜索', value: 'semantic' },
          ]"
          size="small"
          @change="(val) => emit('update:searchMode', val)"
        />
      </div>
      <div class="param-group">
        <span class="param-label">流式输出</span>
        <el-switch
          :model-value="mode === 'stream'"
          inline-prompt
          active-text="开"
          inactive-text="关"
          size="small"
          @change="(val) => emit('toggleMode', val ? 'stream' : 'sync')"
        />
      </div>
    </div>

    <div class="input-row">
      <el-button
        class="attach-btn"
        :disabled="loading"
        text
      >
        <el-icon><Link /></el-icon>
      </el-button>

      <el-input
        v-model="inputText"
        type="textarea"
        :rows="1"
        :autosize="{ minRows: 1, maxRows: 6 }"
        placeholder="输入问题，按 Enter 发送，Shift+Enter 换行"
        :disabled="loading"
        class="text-input"
        @keydown="handleKeydown"
      />

      <el-button
        v-if="!streaming"
        type="primary"
        :disabled="!inputText.trim() || loading"
        class="send-btn"
        @click="handleSend"
      >
        <el-icon><Promotion /></el-icon>
      </el-button>
      <el-button
        v-else
        type="danger"
        class="stop-btn"
        @click="emit('stop')"
      >
        停止
      </el-button>
    </div>

    <div class="input-hint">
      <kbd>Enter</kbd> 发送 &middot; <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行
      <span class="hint-right">
        <el-button text size="small" @click="emit('clear')">清空对话</el-button>
      </span>
    </div>
  </div>
</template>

<style scoped>
.input-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.input-params {
  display: flex;
  gap: 20px;
  align-items: center;
}

.param-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.param-label {
  font: var(--text-metadata);
  color: var(--color-secondary);
  text-transform: none;
  letter-spacing: 0;
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.attach-btn {
  height: 40px;
  width: 40px;
  border-radius: var(--radius-md);
  color: var(--color-secondary);
  flex-shrink: 0;
}

.text-input {
  flex: 1;
}

.text-input :deep(.el-textarea__inner) {
  border-radius: var(--radius-lg);
  font: var(--text-body);
  padding: 10px 14px;
  line-height: 1.5;
  resize: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.text-input :deep(.el-textarea__inner:focus) {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(0, 74, 198, 0.1);
}

.send-btn,
.stop-btn {
  height: 40px;
  width: 40px;
  border-radius: var(--radius-md);
  flex-shrink: 0;
}

.send-btn :deep(.el-icon) {
  font-size: 18px;
}

.input-hint {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font: var(--text-metadata);
  color: #a8abb2;
  text-transform: none;
  letter-spacing: 0;
}

.input-hint kbd {
  display: inline-block;
  padding: 1px 6px;
  font: var(--text-metadata);
  background: var(--color-surface-low);
  border: 1px solid var(--color-outline-variant);
  border-radius: var(--radius-sm);
  text-transform: none;
  letter-spacing: 0;
}

.hint-right {
  display: flex;
  align-items: center;
}
</style>
