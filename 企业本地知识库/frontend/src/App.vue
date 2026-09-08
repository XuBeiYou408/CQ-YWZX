<script setup>
import { useRouter } from 'vue-router'
import { useChatStore } from './stores/chat.js'
import Sidebar from './components/Sidebar.vue'

const router = useRouter()
const store = useChatStore()

function handleNewChat() {
  store.createNewSession()
  router.push('/')
}
</script>

<template>
  <el-container class="app-container">
    <el-aside width="280px" class="app-aside">
      <Sidebar @new-chat="handleNewChat" />
    </el-aside>
    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<style scoped>
.app-container {
  height: 100vh;
}

.app-aside {
  background-color: var(--color-inverse);
  overflow: hidden;
}

.app-main {
  background-color: var(--color-background);
  padding: 0;
  overflow-y: auto;
}
</style>
