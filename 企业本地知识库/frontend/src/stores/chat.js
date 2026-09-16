import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const SESSIONS_STORAGE_KEY = 'rag_sessions_history'

function generateUUID() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'session-' + Date.now().toString(36) + '-' + Math.random().toString(36).substring(2, 7)
}

function loadAllSessionsFromStorage() {
  try {
    const raw = localStorage.getItem(SESSIONS_STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveAllSessionsToStorage(sessions) {
  try {
    localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessions.slice(0, 50)))
  } catch (e) {
    console.error('保存会话历史失败:', e)
  }
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref([])
  const isStreaming = ref(false)
  const mode = ref('stream')
  const currentSessionId = ref(generateUUID())

  // 类似于 Antigravity，将会话首轮提问作为中文会话标题
  const currentChatTitle = computed(() => {
    const firstUserMsg = messages.value.find(m => m.role === 'user')
    if (firstUserMsg && firstUserMsg.content) {
      const clean = firstUserMsg.content.trim().split('\n')[0].replace(/^#+\s*/, '').trim()
      return clean.length > 28 ? clean.slice(0, 28) + '...' : clean
    }
    return '新建对话'
  })

  const fullChatTitle = computed(() => {
    const firstUserMsg = messages.value.find(m => m.role === 'user')
    if (firstUserMsg && firstUserMsg.content) {
      return firstUserMsg.content.trim().split('\n')[0].replace(/^#+\s*/, '').trim()
    }
    return '新建对话'
  })

  function createNewSession() {
    currentSessionId.value = generateUUID()
    messages.value = []
  }

  function loadSession(sessionId) {
    const sessions = loadAllSessionsFromStorage()
    const target = sessions.find(s => s.sessionId === sessionId)
    if (target) {
      currentSessionId.value = target.sessionId
      messages.value = target.messages || []
    }
  }

  function syncCurrentSessionToStorage() {
    if (messages.value.length === 0) return
    const sessions = loadAllSessionsFromStorage()
    
    // 寻找第一条用户提问作为标题
    const firstUserMsg = messages.value.find(m => m.role === 'user')
    const title = firstUserMsg ? firstUserMsg.content.slice(0, 32) : '新对话'
    
    const userMsgCount = messages.value.filter(m => m.role === 'user').length
    const nowStr = new Date().toLocaleString('zh-CN')

    const sessionData = {
      sessionId: currentSessionId.value,
      title,
      timestamp: nowStr,
      userMsgCount,
      messages: JSON.parse(JSON.stringify(messages.value))
    }

    const existingIdx = sessions.findIndex(s => s.sessionId === currentSessionId.value)
    if (existingIdx >= 0) {
      sessions[existingIdx] = sessionData
    } else {
      sessions.unshift(sessionData)
    }

    saveAllSessionsToStorage(sessions)
  }

  function addUserMessage(question) {
    messages.value.push({
      role: 'user',
      content: question,
      timestamp: Date.now(),
    })
    syncCurrentSessionToStorage()
  }

  function addAssistantChunk(chunk) {
    let last = messages.value[messages.value.length - 1]
    if (!last || last.role !== 'assistant') {
      last = {
        role: 'assistant',
        thought: '',
        content: '',
        isThinking: true,
        isCollapsed: false,
        timestamp: Date.now(),
      }
      messages.value.push(last)
    }

    if (typeof chunk === 'string') {
      last.content += chunk
      return
    }

    const { type, content, intent } = chunk || {}
    if (type === 'route') {
      last.routeIntent = intent
      if (intent === 'agent') {
        last.thought += `[🏢 智能规划] 启动企业知识库多工具协同推演...\n`
      } else if (intent === 'summarize') {
        last.thought += `[📋 制度清单] 启动规章全景探查与要点分析...\n`
      }
    } else if (type === 'thought') {
      if (content) last.thought += content + '\n'
    } else if (type === 'observation') {
      if (content) {
        const cleanObs = String(content).replace(/[\r\n]+/g, ' ').trim()
        const shortObs = cleanObs.length > 90 ? cleanObs.slice(0, 90) + '...' : cleanObs
        last.thought += `[检索观察] ${shortObs}\n`
      }
    } else if (type === 'output' || type === 'content') {
      if (content) last.content += content
    } else if (content) {
      last.content += content
    }
  }

  function finishStreaming(costTime) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.costTime = costTime
      last.isThinking = false
      last.isCollapsed = true
    }
    isStreaming.value = false
    syncCurrentSessionToStorage()
  }

  function clearMessages() {
    messages.value = []
  }

  function setMode(m) {
    mode.value = m
  }

  return {
    messages,
    isStreaming,
    mode,
    currentSessionId,
    currentChatTitle,
    fullChatTitle,
    createNewSession,
    loadSession,
    syncCurrentSessionToStorage,
    addUserMessage,
    addAssistantChunk,
    finishStreaming,
    clearMessages,
    setMode,
  }
})
