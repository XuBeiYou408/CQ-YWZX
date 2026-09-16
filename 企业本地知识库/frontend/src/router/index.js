import { createRouter, createWebHashHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import HistoryView from '../views/HistoryView.vue'
import SettingsView from '../views/SettingsView.vue'

const routes = [
  {
    path: '/',
    name: 'Chat',
    component: ChatView,
    meta: { title: '企业知识库' },
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: KnowledgeView,
    meta: { title: '知识库管理 - 企业知识库' },
  },
  {
    path: '/history',
    name: 'History',
    component: HistoryView,
    meta: { title: '历史记录 - 企业知识库' },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: SettingsView,
    meta: { title: '模型管理 - 企业知识库' },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.afterEach(() => {
  document.title = '企业本地知识库'
})

// 防御异步模块加载异常与缓存失效
router.onError((error) => {
  console.error('路由导航异常:', error)
  if (/Failed to fetch dynamically imported module|Importing a module script failed/i.test(error?.message || '')) {
    window.location.reload()
  }
})

export default router
