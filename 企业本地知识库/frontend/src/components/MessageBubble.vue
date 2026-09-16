<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { renderMarkdown, renderThought } from '../utils/markdown.js'

const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['continue'])

const elapsedTime = ref(0)
const thoughtLogRef = ref(null)
let timer = null

onMounted(() => {
  if (props.message.role === 'assistant' && props.message.isThinking) {
    const startTime = props.message.timestamp || Date.now()
    timer = setInterval(() => {
      elapsedTime.value = parseFloat(((Date.now() - startTime) / 1000).toFixed(1))
    }, 100)
  }
})

watch(() => props.message.isThinking, (isThinking) => {
  if (!isThinking && timer) {
    clearInterval(timer)
    timer = null
  }
})

// 当思维链实时流式输出时，思维卡片内部平滑自动向下滚动
watch(() => props.message.thought, () => {
  if (props.message.isThinking && !props.message.isCollapsed && thoughtLogRef.value) {
    thoughtLogRef.value.scrollTop = thoughtLogRef.value.scrollHeight
  }
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

function toggleCollapse() {
  if (typeof props.message.isCollapsed === 'undefined') {
    props.message.isCollapsed = false
  } else {
    props.message.isCollapsed = !props.message.isCollapsed
  }
}

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  try {
    return renderMarkdown(props.message.content)
  } catch (e) {
    return props.message.content
  }
})

const renderedThought = computed(() => {
  return renderThought(props.message.thought)
})
</script>

<template>
  <div :class="['message-bubble', message.role]">
    <div class="bubble-avatar">
      <span v-if="message.role === 'user'">你</span>
      <span v-else>AI</span>
    </div>

    <div class="bubble-body">
      <!-- Assistant 深度思考/Agent 推理面板：当处于思考中，或者已有思考推理日志时展示 -->
      <div
        v-if="message.role === 'assistant' && (message.isThinking || (message.thought && message.thought.trim()))"
        class="thinking-card"
        :class="{ collapsed: message.isCollapsed, 'is-thinking': message.isThinking }"
      >
        <div class="thinking-header" @click="toggleCollapse">
          <div class="header-title">
            <span class="think-icon-sparkle">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2v20M2 12h20M17 7l-10 10M7 7l10 10" stroke-linecap="round"/>
              </svg>
            </span>
            <span v-if="message.isThinking" class="think-status-text">
              思考中... <span class="think-timer">({{ elapsedTime }}s)</span>
            </span>
            <span v-else class="think-status-text">
              已深度思考 <span class="think-timer">(用时 {{ message.costTime != null ? message.costTime : elapsedTime }} 秒)</span>
            </span>
          </div>

          <div class="header-action">
            <span class="collapse-tip">{{ message.isCollapsed ? '展开' : '收起' }}</span>
            <span class="collapse-icon" :class="{ rotated: !message.isCollapsed }">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </span>
          </div>
        </div>

        <div ref="thoughtLogRef" v-show="!message.isCollapsed" class="thinking-content">
          <div v-if="renderedThought" class="thought-markdown markdown-body" v-html="renderedThought"></div>
          <div v-else class="thought-placeholder">正在检索企业知识库并推演合规回答...</div>
        </div>
      </div>

      <!-- 核心回答正文区 (Markdown 渲染) -->
      <div
        v-if="message.role === 'user' || message.content"
        :class="['bubble-content', message.role]"
      >
        <div v-if="message.role === 'user'" class="content-text">{{ message.content }}</div>
        <div
          v-else
          class="content-markdown markdown-body"
          v-html="renderedContent"
        ></div>

        <!-- 截断提示卡片 (当达到上下文/Token 上限时展示) -->
        <div v-if="message.role === 'assistant' && message.isTruncated" class="truncated-alert">
          <div class="truncated-header">
            <el-icon class="truncated-icon" :size="16"><WarningFilled /></el-icon>
            <span class="truncated-title">回答已截断：已达到大模型单次生成 Token / 上下文上限</span>
          </div>
          <p class="truncated-desc">
            {{ message.truncateMessage || '大模型单次生成长度已达上限，内容未能全部输出。' }}
          </p>
          <div class="truncated-actions">
            <el-button
              type="warning"
              size="small"
              class="continue-btn"
              @click="emit('continue')"
            >
              <el-icon style="margin-right: 4px"><Right /></el-icon>
              <span>继续生成</span>
            </el-button>
            <span class="truncated-tip">点击“继续生成”或在下方发送“继续”，模型将接着未完成的内容继续回答</span>
          </div>
        </div>

        <!-- 引用卡片 -->
        <div v-if="message.citations && message.citations.length" class="citations">
          <div
            v-for="(cite, idx) in message.citations"
            :key="idx"
            class="citation-card"
          >
            <div class="citation-bar"></div>
            <div class="citation-info">
              <span class="citation-type">PDF</span>
              <span class="citation-source">来源：{{ cite }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="message.costTime != null" class="bubble-meta">
        响应耗时 {{ message.costTime }}s
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-bubble {
  display: flex;
  gap: 12px;
  max-width: 85%;
  animation: fadeInUp 0.25s ease-out;
  margin-bottom: 16px;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-bubble.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.message-bubble.assistant {
  align-self: flex-start;
}

.bubble-avatar {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.user .bubble-avatar {
  background-color: var(--color-primary-container, #004ac6);
  color: #fff;
}

.assistant .bubble-avatar {
  background-color: #4f46e5;
  color: #fff;
}

.bubble-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  width: 100%;
}

/* === 深度思考 (Chain of Thought) 现代卡片 === */
.thinking-card {
  margin-bottom: 12px;
  border-radius: 12px;
  background-color: #f8fafc;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  transition: all 0.25s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.thinking-card:hover {
  border-color: #cbd5e1;
}

.thinking-card.is-thinking {
  border-color: #c7d2fe;
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.15);
}

.thinking-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 15px;
  cursor: pointer;
  user-select: none;
  background-color: #f1f5f9;
  transition: background-color 0.2s ease;
}

.thinking-header:hover {
  background-color: #e2e8f0;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #475569;
  font-weight: 500;
}

.think-icon-sparkle {
  color: #6366f1;
  display: flex;
  align-items: center;
  animation: pulseSparkle 2.2s infinite ease-in-out;
}

@keyframes pulseSparkle {
  0%, 100% { opacity: 0.65; transform: scale(0.95); }
  50% { opacity: 1; transform: scale(1.1); }
}

.think-status-text {
  font-size: 13px;
  color: #475569;
}

.think-timer {
  color: #94a3b8;
  font-size: 12px;
  margin-left: 2px;
}

.header-action {
  display: flex;
  align-items: center;
  gap: 6px;
}

.collapse-tip {
  font-size: 11.5px;
  color: #94a3b8;
}

.collapse-icon {
  display: flex;
  align-items: center;
  color: #94a3b8;
  transition: transform 0.25s ease;
}

.collapse-icon.rotated {
  transform: rotate(180deg);
}

.thinking-content {
  padding: 12px 18px;
  border-top: 1px dashed #e2e8f0;
  background-color: #ffffff;
  max-height: 280px;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.thought-markdown {
  font-size: 13px;
  line-height: 1.75;
  color: #475569;
}

.thought-markdown :deep(p) {
  margin: 0 0 8px 0;
}

.thought-markdown :deep(p:last-child) {
  margin-bottom: 0;
}

.thought-markdown :deep(ul),
.thought-markdown :deep(ol) {
  margin: 4px 0 8px 18px;
  padding: 0;
}

.thought-markdown :deep(li) {
  margin-bottom: 3px;
}

.thought-markdown :deep(strong) {
  color: #1e293b;
  font-weight: 600;
}

.thought-placeholder {
  font-size: 12.5px;
  color: #94a3b8;
  font-style: italic;
}

/* === 正文 Bubble === */
.bubble-content {
  padding: 14px 18px;
  border-radius: var(--radius-lg, 12px);
  line-height: 1.7;
  word-break: break-word;
}

.bubble-content.user {
  background-color: var(--color-primary-container, #004ac6);
  color: #ffffff;
  border-top-right-radius: var(--radius-sm, 4px);
}

.bubble-content.assistant {
  background-color: #ffffff;
  color: #2c3e50;
  border-top-left-radius: var(--radius-sm, 4px);
  border: 1px solid #eef0f4;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.03);
}

.content-text {
  white-space: pre-wrap;
}

/* Markdown 排版系统控制 */
:deep(.markdown-body) {
  font-size: 14.5px;
  line-height: 1.7;
  color: #2c3e50;
}

:deep(.markdown-body p) {
  margin: 0 0 10px 0;
}

:deep(.markdown-body p:last-child) {
  margin-bottom: 0;
}

:deep(.markdown-body h1),
:deep(.markdown-body h2),
:deep(.markdown-body h3),
:deep(.markdown-body h4) {
  margin: 14px 0 8px 0;
  font-weight: 600;
  line-height: 1.4;
  color: #1f2937;
}

:deep(.markdown-body h1) { font-size: 1.25em; }
:deep(.markdown-body h2) { font-size: 1.15em; }
:deep(.markdown-body h3) { font-size: 1.05em; }

:deep(.markdown-body ul),
:deep(.markdown-body ol) {
  padding-left: 20px;
  margin: 6px 0 10px 0;
}

:deep(.markdown-body li) {
  margin-bottom: 4px;
}

:deep(.markdown-body code) {
  background-color: #f3f4f6;
  color: #d97706;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: SFMono-Regular, Consolas, monospace;
}

:deep(.markdown-body pre) {
  background-color: #1e1e2e;
  color: #cdd6f4;
  padding: 12px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
}

:deep(.markdown-body pre code) {
  background-color: transparent;
  color: inherit;
  padding: 0;
  border-radius: 0;
}

:deep(.markdown-body blockquote) {
  border-left: 4px solid #4f46e5;
  margin: 10px 0;
  padding: 6px 12px;
  background-color: #f8fafc;
  color: #475569;
}

/* Citations */
.citations {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--color-outline-variant, #e0e0e0);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.citation-card {
  display: flex;
  border-radius: var(--radius-md, 6px);
  background-color: var(--color-surface-low, #f5f7fa);
  overflow: hidden;
}

.citation-bar {
  width: 4px;
  flex-shrink: 0;
  background-color: var(--color-primary, #004ac6);
}

.citation-info {
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.citation-type {
  color: var(--color-primary, #004ac6);
  background-color: rgba(0, 74, 198, 0.08);
  padding: 2px 8px;
  border-radius: 12px;
}

.citation-source {
  color: #606266;
  font-size: 13px;
}

.bubble-meta {
  font-size: 12px;
  color: #a8abb2;
  margin-top: 6px;
}

.user .bubble-meta { text-align: right; }
.assistant .bubble-meta { text-align: left; }

/* === KaTeX 数学公式渲染优化 === */
:deep(.katex-display-wrapper) {
  margin: 12px 0;
  overflow-x: auto;
  overflow-y: hidden;
  text-align: center;
  padding: 6px 0;
}

:deep(.katex) {
  font-size: 1.05em;
  text-indent: 0;
}

:deep(.katex-display) {
  margin: 0 !important;
}

/* === 截断提示卡片 === */
.truncated-alert {
  margin-top: 14px;
  padding: 12px 16px;
  border-radius: var(--radius-md, 8px);
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  animation: fadeIn 0.25s ease-out;
}

.truncated-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 13.5px;
  color: #b45309;
}

.truncated-icon {
  color: #d97706;
  flex-shrink: 0;
}

.truncated-desc {
  margin: 6px 0 10px 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: #78350f;
}

.truncated-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.continue-btn {
  background-color: #d97706 !important;
  border-color: #d97706 !important;
  color: #ffffff !important;
  font-weight: 500;
  border-radius: 6px;
}

.continue-btn:hover {
  background-color: #b45309 !important;
  border-color: #b45309 !important;
}

.truncated-tip {
  font-size: 12px;
  color: #92400e;
  opacity: 0.85;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
