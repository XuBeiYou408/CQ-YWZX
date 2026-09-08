import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const MODEL_CONFIG_KEY = 'rag_model_config'

function loadSavedConfig() {
  try {
    const raw = localStorage.getItem(MODEL_CONFIG_KEY)
    if (raw) return JSON.parse(raw)
  } catch (e) {
    console.error('加载模型配置失败:', e)
  }
  return {
    provider: 'cloud',
    cloudModel: 'deepseek-chat',
    localModel: 'qwen3.8-27b',
    cloudApiKey: '',
    cloudBaseUrl: '',
    temperature: 0.7
  }
}

export const useModelStore = defineStore('model', () => {
  const initial = loadSavedConfig()
  
  const provider = ref(initial.provider || 'cloud')
  const cloudModel = ref(initial.cloudModel || 'deepseek-chat')
  const localModel = ref(initial.localModel || 'qwen3.8-27b')
  const cloudApiKey = ref(initial.cloudApiKey || '')
  const cloudBaseUrl = ref(initial.cloudBaseUrl || '')
  const temperature = ref(initial.temperature ?? 0.7)

  const activeModelName = computed(() => {
    return provider.value === 'local' ? localModel.value : cloudModel.value
  })

  function saveConfig() {
    try {
      localStorage.setItem(MODEL_CONFIG_KEY, JSON.stringify({
        provider: provider.value,
        cloudModel: cloudModel.value,
        localModel: localModel.value,
        cloudApiKey: cloudApiKey.value,
        cloudBaseUrl: cloudBaseUrl.value,
        temperature: temperature.value
      }))
    } catch (e) {
      console.error('保存模型配置失败:', e)
    }
  }

  function setProvider(val) {
    provider.value = val
    saveConfig()
  }

  function setCloudModel(val) {
    cloudModel.value = val
    saveConfig()
  }

  function setLocalModel(val) {
    localModel.value = val
    saveConfig()
  }

  return {
    provider,
    cloudModel,
    localModel,
    cloudApiKey,
    cloudBaseUrl,
    temperature,
    activeModelName,
    setProvider,
    setCloudModel,
    setLocalModel,
    saveConfig
  }
})
