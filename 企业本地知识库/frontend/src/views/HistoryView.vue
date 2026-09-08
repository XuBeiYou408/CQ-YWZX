<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat.js'
import HistoryList from '../components/HistoryList.vue'
import HistoryDetail from '../components/HistoryDetail.vue'

const SESSIONS_STORAGE_KEY = 'rag_sessions_history'
const router = useRouter()
const chatStore = useChatStore()

const conversations = ref([])
const selected = ref(null)
const searchText = ref('')
const timeFilter = ref('all')

function loadHistory() {
  try {
    const raw = localStorage.getItem(SESSIONS_STORAGE_KEY)
    if (raw) {
      conversations.value = JSON.parse(raw)
    } else {
      // 兼容可能存在的旧版 rag_chat_history
      const oldRaw = localStorage.getItem('rag_chat_history')
      if (oldRaw) {
        const oldItems = JSON.parse(oldRaw)
        conversations.value = oldItems.map(item => ({
          sessionId: item.id || ('session-' + Math.random().toString(36).substring(2, 7)),
          title: item.question || '历史对话',
          timestamp: item.timestamp || new Date().toLocaleString('zh-CN'),
          userMsgCount: 1,
          messages: [
            { role: 'user', content: item.question, timestamp: Date.now() },
            { role: 'assistant', content: item.answer, costTime: item.costTime, timestamp: Date.now() }
          ]
        }))
        localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(conversations.value))
      } else {
        conversations.value = []
      }
    }
  } catch {
    conversations.value = []
  }
}

onMounted(loadHistory)

function handleSelect(conv) {
  selected.value = conv
}

function handleDelete(sessionId) {
  conversations.value = conversations.value.filter(c => c.sessionId !== sessionId)
  localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(conversations.value))
  if (selected.value?.sessionId === sessionId) {
    selected.value = null
  }
}

function handleResume(sessionId) {
  chatStore.loadSession(sessionId)
  router.push('/')
}

function handleClearAll() {
  conversations.value = []
  selected.value = null
  localStorage.removeItem(SESSIONS_STORAGE_KEY)
}

const filteredConversations = computed(() => {
  let list = conversations.value

  if (searchText.value.trim()) {
    const q = searchText.value.trim().toLowerCase()
    list = list.filter(c => {
      const matchTitle = c.title?.toLowerCase().includes(q)
      const matchMsgs = c.messages?.some(m => m.content?.toLowerCase().includes(q))
      return matchTitle || matchMsgs
    })
  }

  if (timeFilter.value === '7days') {
    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
    list = list.filter(c => {
      const ts = new Date(c.timestamp).getTime()
      return ts > sevenDaysAgo
    })
  }

  return list
})
</script>

<template>
  <div class="history-view">
    <div class="history-left">
      <div class="history-left-header">
        <h3>历史对话</h3>
        <div class="header-actions">
          <el-button text size="small" :disabled="conversations.length === 0" @click="loadHistory">
            <el-icon><Refresh /></el-icon>
          </el-button>
          <el-popconfirm
            title="确定清空全部历史记录？"
            @confirm="handleClearAll"
          >
            <template #reference>
              <el-button text type="danger" size="small" :disabled="conversations.length === 0">
                清空全部
              </el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>

      <div class="search-wrap">
        <el-input
          v-model="searchText"
          placeholder="搜索对话内容..."
          size="default"
          clearable
          prefix-icon="Search"
          class="search-input"
        />
      </div>

      <div class="filter-row">
        <span
          :class="['filter-chip', { active: timeFilter === 'all' }]"
          @click="timeFilter = 'all'"
        >全部</span>
        <span
          :class="['filter-chip', { active: timeFilter === '7days' }]"
          @click="timeFilter = '7days'"
        >近 7 天</span>
      </div>

      <HistoryList
        :conversations="filteredConversations"
        :selected-id="selected?.sessionId"
        @select="handleSelect"
        @delete="handleDelete"
      />
    </div>

    <div class="history-right">
      <HistoryDetail
        v-if="selected"
        :conversation="selected"
        @resume="handleResume"
      />
      <div v-else class="empty-detail">
        <div class="empty-art">
          <svg width="100" height="100" viewBox="0 0 100 100" fill="none">
            <rect x="20" y="30" width="60" height="45" rx="8" stroke="#c0c4cc" stroke-width="2" stroke-dasharray="4 4"/>
            <circle cx="50" cy="65" r="12" fill="#f3f4f5" stroke="#c0c4cc" stroke-width="1.5"/>
            <circle cx="50" cy="65" r="4" fill="#c0c4cc"/>
          </svg>
        </div>
        <p class="empty-title">暂无历史记录</p>
        <p class="empty-desc">
          从左侧列表中选择一条历史对话查看详情，<br>或前往对话页开始新的问答。
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-view {
  display: flex;
  height: 100vh;
}

/* === Left Panel === */
.history-left {
  width: 380px;
  border-right: 1px solid var(--color-outline-variant);
  background: var(--color-surface);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.history-left-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 20px;
  border-bottom: 1px solid var(--color-outline-variant);
}

.history-left-header h3 {
  margin: 0;
  font: var(--text-section);
  color: #303133;
}

.header-actions {
  display: flex;
  gap: 4px;
}

.search-wrap {
  padding: 14px 20px;
}

.search-input :deep(.el-input__wrapper) {
  border-radius: var(--radius-lg);
}

.filter-row {
  display: flex;
  gap: 8px;
  padding: 0 20px 12px;
}

.filter-chip {
  padding: 4px 14px;
  border-radius: var(--radius-pill);
  font: var(--text-metadata);
  color: var(--color-secondary);
  background: var(--color-surface-low);
  cursor: pointer;
  transition: all 0.2s;
  text-transform: none;
  letter-spacing: 0;
}

.filter-chip.active {
  background: var(--color-primary);
  color: #fff;
}

/* === Right Panel === */
.history-right {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
}

.empty-detail {
  text-align: center;
  padding: 60px 40px;
}

.empty-art {
  margin-bottom: 24px;
  opacity: 0.5;
}

.empty-title {
  font: var(--text-section);
  color: var(--color-secondary);
  margin-bottom: 8px;
}

.empty-desc {
  font-size: 14px;
  color: #a8abb2;
  line-height: 1.8;
}
</style>
