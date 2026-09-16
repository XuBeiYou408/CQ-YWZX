<script setup>
import { ref, nextTick, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat.js'
import { useModelStore } from '../stores/model.js'
import { streamQuestion, askQuestion } from '../api/index.js'
import MessageList from '../components/MessageList.vue'
import InputBox from '../components/InputBox.vue'

const router = useRouter()
const store = useChatStore()
const modelStore = useModelStore()
const loading = ref(false)
const thinking = ref(false)
const abortController = ref(null)
const messagesContainer = ref(null)
const searchMode = ref('hybrid')

// 智能滚动状态控制：防止打字时强制刷新到底部导致用户无法上滑查看
const userScrolledUp = ref(false)
const SCROLL_THRESHOLD = 80
let isSmoothScrolling = false
let smoothScrollTimer = null

function handleScroll() {
  if (!messagesContainer.value) return
  const { scrollTop, scrollHeight, clientHeight } = messagesContainer.value
  const distanceFromBottom = scrollHeight - scrollTop - clientHeight

  if (distanceFromBottom <= SCROLL_THRESHOLD) {
    userScrolledUp.value = false
    isSmoothScrolling = false
  } else if (!isSmoothScrolling) {
    userScrolledUp.value = true
  }
}

function scrollToBottom(smooth = true) {
  if (!messagesContainer.value) return
  userScrolledUp.value = false
  if (smooth) {
    isSmoothScrolling = true
    if (smoothScrollTimer) clearTimeout(smoothScrollTimer)
    smoothScrollTimer = setTimeout(() => {
      isSmoothScrolling = false
    }, 400)
    messagesContainer.value.scrollTo({
      top: messagesContainer.value.scrollHeight,
      behavior: 'smooth'
    })
  } else {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

onMounted(() => {
  nextTick(() => {
    if (messagesContainer.value && store.messages.length > 0) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
})

watch(() => store.currentSessionId, async () => {
  userScrolledUp.value = false
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
})

const HISTORY_KEY = 'rag_chat_history'

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function generateUUID() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'uuid-' + Date.now().toString(36) + '-' + Math.random().toString(36).substring(2, 9)
}

function saveToHistory(question, answer, costTime) {
  const history = loadHistory()
  history.unshift({
    id: generateUUID(),
    timestamp: new Date().toLocaleString('zh-CN'),
    question,
    answer,
    costTime,
  })
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 50)))
}

async function handleSend(question) {
  if (store.isStreaming) return

  userScrolledUp.value = false
  store.addUserMessage(question)
  loading.value = true
  store.isStreaming = true
  thinking.value = true

  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }

  if (store.mode === 'stream') {
    const startTime = Date.now()
    try {
      const controller = new AbortController()
      abortController.value = controller

      let firstToken = true
      for await (const chunk of streamQuestion(question, controller.signal, store.currentSessionId, modelStore.provider, modelStore.activeModelName)) {
        if (firstToken) {
          thinking.value = false
          firstToken = false
        }
        store.addAssistantChunk(chunk)
        await nextTick()
        // 关键防护：仅当用户未上滑查看历史时才自动跟随滚动，保证用户可自由上滑浏览
        if (messagesContainer.value && !userScrolledUp.value) {
          messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
        }
      }
      const costTime = parseFloat(((Date.now() - startTime) / 1000).toFixed(2))
      store.finishStreaming(costTime)
    } catch (e) {
      if (e.name !== 'AbortError') {
        store.addAssistantChunk({ type: 'content', content: '请求失败: ' + e.message })
      }
      store.isStreaming = false
      thinking.value = false
    }
  } else {
    try {
      const result = await askQuestion(question, modelStore.provider, modelStore.activeModelName)
      store.addAssistantChunk({ type: 'content', content: result.answer })
      store.finishStreaming(result.cost_time)
      await nextTick()
      if (messagesContainer.value && !userScrolledUp.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
      }
    } catch (e) {
      store.addAssistantChunk({ type: 'content', content: '请求失败: ' + e.message })
      store.isStreaming = false
    }
    thinking.value = false
  }

  loading.value = false
  abortController.value = null
}

function handleStop() {
  if (abortController.value) {
    abortController.value.abort()
    store.isStreaming = false
    loading.value = false
    thinking.value = false
  }
}

function handleClear() {
  userScrolledUp.value = false
  store.createNewSession()
}

function getTodayLabel() {
  return new Date().toLocaleDateString('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'long',
  })
}

// 网页标签页固定显示“企业本地知识库”
document.title = '企业本地知识库'
</script>

<template>
  <div class="chat-view">
    <header class="chat-header">
      <div class="header-left">
        <h1 class="chat-title" :title="store.fullChatTitle">
          <el-tooltip
            v-if="store.currentChatTitle !== '新建对话'"
            :content="store.fullChatTitle"
            placement="bottom-start"
            :show-after="300"
          >
            <span>{{ store.currentChatTitle }}</span>
          </el-tooltip>
          <span v-else>{{ store.currentChatTitle }}</span>
        </h1>
        <div class="chat-subtitle-box">
          <span class="chat-subtitle">LangChain + BGE + FAISS</span>
          <el-tag
            :type="modelStore.provider === 'local' ? 'success' : 'primary'"
            size="small"
            effect="light"
            class="model-active-tag"
            @click="router.push('/settings')"
            style="cursor: pointer; margin-left: 8px;"
          >
            {{ modelStore.provider === 'local' ? '🏠 本地部署: ' : '☁️ 云端 API: ' }}{{ modelStore.activeModelName }}
          </el-tag>
        </div>
      </div>
      <div class="header-right">
        <el-tooltip content="模型管理与设置" placement="bottom">
          <el-button text circle @click="router.push('/settings')">
            <el-icon :size="18"><Setting /></el-icon>
          </el-button>
        </el-tooltip>
        <el-button text>
          <el-icon :size="16" style="margin-right:4px"><Download /></el-icon>
          导出数据
        </el-button>
      </div>
    </header>

    <div class="chat-body" ref="messagesContainer" @scroll="handleScroll">
      <div v-if="store.messages.length === 0 && !thinking" class="empty-state">
        <div class="empty-icon">
          <svg width="72" height="72" viewBox="0 0 24 24" fill="none" stroke="#c0c4cc" stroke-width="1.2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            <path d="M8 9h8M8 13h6" stroke-linecap="round"/>
          </svg>
        </div>
        <p class="empty-title">欢迎使用企业本地知识库</p>
        <p class="empty-hint">基于知识库的智能问答，支持混合检索与流式输出</p>
      </div>

      <div v-else class="chat-timeline">
        <div class="timeline-label">{{ getTodayLabel() }}</div>
      </div>

      <MessageList :messages="store.messages" />

      <div v-if="thinking" class="thinking-bubble">
        <div class="think-avatar">AI</div>
        <div class="think-body">
          <div class="think-dots">
            <span class="dot" style="animation-delay: 0s"></span>
            <span class="dot" style="animation-delay: 0.2s"></span>
            <span class="dot" style="animation-delay: 0.4s"></span>
          </div>
          <span class="think-text">正在检索文档并思考解决方案...</span>
        </div>
      </div>
    </div>

    <footer class="chat-footer">
      <!-- 浮动回到底部快捷按钮（用户上滑查看历史时柔和呈现） -->
      <transition name="scroll-btn-fade">
        <div
          v-if="userScrolledUp && store.messages.length > 0"
          class="scroll-bottom-wrapper"
        >
          <button
            class="scroll-bottom-btn"
            @click="scrollToBottom(true)"
            title="回到底部"
          >
            <el-icon :size="13"><ArrowDown /></el-icon>
            <span>回到底部</span>
            <span v-if="store.isStreaming" class="streaming-badge">
              <span class="pulse-dot"></span>
              <span>生成中</span>
            </span>
          </button>
        </div>
      </transition>

      <InputBox
        :loading="loading"
        :streaming="store.isStreaming"
        :mode="store.mode"
        :search-mode="searchMode"
        @send="handleSend"
        @stop="handleStop"
        @toggle-mode="store.setMode"
        @update:search-mode="(v) => searchMode = v"
        @clear="handleClear"
      />
    </footer>
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 var(--spacing-lg);
}

/* === Header === */
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 0 14px;
  border-bottom: 1px solid var(--color-outline-variant);
  flex-shrink: 0;
}

.header-left {
  min-width: 0;
  flex: 1;
}

.chat-title {
  font: var(--text-section);
  color: #303133;
  margin: 0;
  max-width: 680px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-subtitle {
  font: var(--text-metadata);
  color: var(--color-secondary);
  margin-top: 2px;
  display: block;
  text-transform: none;
  letter-spacing: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* === Body === */
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 0 80px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 120px 20px;
  text-align: center;
}

.empty-icon { margin-bottom: 24px; opacity: 0.5; }

.empty-title {
  font: var(--text-section);
  color: var(--color-secondary);
  margin-bottom: 8px;
}

.empty-hint {
  font: var(--text-body);
  color: #a8abb2;
}

/* === Timeline === */
.chat-timeline {
  text-align: center;
  margin-bottom: 20px;
}

.timeline-label {
  display: inline-block;
  font: var(--text-metadata);
  color: #909399;
  background: var(--color-surface-low);
  padding: 4px 14px;
  border-radius: var(--radius-pill);
  text-transform: none;
  letter-spacing: 0;
}

/* === Thinking === */
.thinking-bubble {
  display: flex;
  gap: 12px;
  max-width: 80%;
  margin-top: 12px;
}

.think-avatar {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background-color: var(--color-secondary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.think-body {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  border-top-left-radius: var(--radius-sm);
  box-shadow: var(--shadow-soft);
}

.think-dots {
  display: flex;
  gap: 4px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--color-outline-variant);
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 60%, 100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  30% {
    opacity: 1;
    transform: scale(1.2);
  }
}

.think-text {
  font-size: 13px;
  color: var(--color-secondary);
  font-style: italic;
}

/* === Footer === */
.chat-footer {
  position: sticky;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 16px 0;
  background: rgba(248, 249, 250, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-top: 1px solid rgba(195, 198, 215, 0.5);
  flex-shrink: 0;
}

/* === 回到底部浮动按钮 === */
.scroll-bottom-wrapper {
  position: absolute;
  top: -44px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 50;
  pointer-events: auto;
}

.scroll-bottom-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  background: var(--color-surface);
  color: var(--color-primary-container);
  border: 1px solid var(--color-outline-variant);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.1);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  user-select: none;
}

.scroll-bottom-btn:hover {
  background: #f0f6ff;
  border-color: var(--color-primary-container);
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.18);
}

.streaming-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 2px;
  padding: 1px 6px;
  background: var(--color-success-bg);
  color: var(--color-success-text);
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #10b981;
  animation: pulse-dot 1.2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.3;
    transform: scale(0.7);
  }
}

.scroll-btn-fade-enter-active,
.scroll-btn-fade-leave-active {
  transition: all 0.2s ease;
}

.scroll-btn-fade-enter-from,
.scroll-btn-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
