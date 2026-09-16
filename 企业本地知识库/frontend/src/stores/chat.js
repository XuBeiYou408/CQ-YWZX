import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const SESSIONS_STORAGE_KEY = 'rag_sessions_history'
const ACTIVE_SESSION_ID_KEY = 'rag_active_session_id'

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

/**
 * 获取初始会话状态：
 * 默认恢复到用户最近的一次对话（若重启服务或刷新网页时优先呈现历史记录，而非空白新对话）
 */
function getInitialSessionState() {
  const sessions = loadAllSessionsFromStorage()
  if (sessions && sessions.length > 0) {
    const savedActiveId = localStorage.getItem(ACTIVE_SESSION_ID_KEY)
    let target = null
    // 1. 如果上次存在活跃会话且包含对话记录，优先恢复
    if (savedActiveId) {
      target = sessions.find(s => s.sessionId === savedActiveId && s.messages && s.messages.length > 0)
    }
    // 2. 否则默认恢复到最近的一次对话 (位于数组首位即最新的历史记录)
    if (!target) {
      target = sessions.find(s => s.messages && s.messages.length > 0) || sessions[0]
    }
    if (target && target.messages && target.messages.length > 0) {
      localStorage.setItem(ACTIVE_SESSION_ID_KEY, target.sessionId)
      return {
        sessionId: target.sessionId,
        messages: target.messages
      }
    }
  }
  return {
    sessionId: generateUUID(),
    messages: []
  }
}

export const useChatStore = defineStore('chat', () => {
  const initial = getInitialSessionState()
  const messages = ref(initial.messages)
  const isStreaming = ref(false)
  const mode = ref('stream')
  const currentSessionId = ref(initial.sessionId)

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
    localStorage.removeItem(ACTIVE_SESSION_ID_KEY)
  }

  function loadSession(sessionId) {
    const sessions = loadAllSessionsFromStorage()
    const target = sessions.find(s => s.sessionId === sessionId)
    if (target) {
      currentSessionId.value = target.sessionId
      messages.value = target.messages || []
      localStorage.setItem(ACTIVE_SESSION_ID_KEY, target.sessionId)
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
      sessions.splice(existingIdx, 1)
    }
    sessions.unshift(sessionData)

    saveAllSessionsToStorage(sessions)
    localStorage.setItem(ACTIVE_SESSION_ID_KEY, currentSessionId.value)
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

    const { type, content, intent, reason, message } = chunk || {}
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
    } else if (type === 'truncated') {
      last.isTruncated = true
      last.truncateReason = reason || 'length'
      last.truncateMessage = message || '回答已达模型单次最大输出 Token / 上下文长度上限，内容已被截断。'
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

      // 启发式截断智能检测：若后端未直接返回截断通知，但文本在语法中途（如公式未闭合、代码未闭合、孤立换行等）突然中断
      if (!last.isTruncated && last.content) {
        const trimmed = last.content.trim()
        const openBlockLatex = (trimmed.match(/\\\[/g) || []).length
        const closeBlockLatex = (trimmed.match(/\\\]/g) || []).length
        const openInlineLatex = (trimmed.match(/\\\(/g) || []).length
        const closeInlineLatex = (trimmed.match(/\\\)/g) || []).length
        const backticksCount = (trimmed.match(/```/g) || []).length
        const openBracket = (trimmed.match(/(?:^|\n)\s*\[\s*\n/g) || []).length
        const closeBracket = (trimmed.match(/(?:^|\n)\s*\]\s*(?:$|\n)/g) || []).length

        if (openBlockLatex > closeBlockLatex || openInlineLatex > closeInlineLatex || (backticksCount % 2 === 1) || (openBracket > closeBracket)) {
          last.isTruncated = true
          last.truncateReason = 'syntax_unclosed'
          last.truncateMessage = '模型回答在公式或语法段中途突然中止输出，已达到单次最大 Token / 上下文长度限制。'
        }
      }
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
