<script setup>
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const activeIndex = computed(() => route.path)

const emit = defineEmits(['newChat'])
</script>

<template>
  <div class="sidebar">
    <div class="sidebar-brand">
      <div class="brand-title">企业本地知识库</div>
      <div class="brand-subtitle">智能问答 Agent 协同系统</div>
    </div>

    <div class="sidebar-action">
      <el-button
        class="new-chat-btn"
        @click="emit('newChat')"
        block
      >
        <el-icon><Plus /></el-icon>
        <span>新建对话</span>
      </el-button>
    </div>

    <el-menu
      :default-active="activeIndex"
      router
      background-color="transparent"
      text-color="#a0a0b8"
      active-text-color="#ffffff"
      class="sidebar-menu"
    >
      <el-menu-item index="/">
        <el-icon><ChatDotRound /></el-icon>
        <span>问答</span>
      </el-menu-item>
      <el-menu-item index="/knowledge">
        <el-icon><FolderOpened /></el-icon>
        <span>知识库</span>
      </el-menu-item>
      <el-menu-item index="/history">
        <el-icon><Clock /></el-icon>
        <span>历史</span>
      </el-menu-item>
      <el-menu-item index="/settings">
        <el-icon><Setting /></el-icon>
        <span>模型管理</span>
      </el-menu-item>
    </el-menu>

    <div class="sidebar-footer">
      <div class="user-info">
        <div class="user-avatar">A</div>
        <div class="user-detail">
          <div class="user-name">管理员</div>
          <div class="user-email">admin@rag-system.ai</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  height: 100%;
  background-color: var(--color-inverse);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-brand {
  padding: 24px 20px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.brand-title {
  font: var(--text-display);
  font-size: 24px;
  color: #ffffff;
  letter-spacing: -0.02em;
}

.brand-subtitle {
  font: var(--text-metadata);
  color: rgba(255, 255, 255, 0.45);
  margin-top: 2px;
  text-transform: none;
  letter-spacing: 0;
}

.sidebar-action {
  padding: 16px;
}

.new-chat-btn {
  --el-button-bg-color: rgba(37, 99, 235, 0.25);
  --el-button-border-color: transparent;
  --el-button-text-color: #ffffff;
  --el-button-hover-bg-color: rgba(37, 99, 235, 0.4);
  --el-button-hover-border-color: transparent;
  --el-button-hover-text-color: #ffffff;
  border-radius: var(--radius-lg);
  height: 42px;
  font-size: 14px;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
  padding: 8px;
}

.sidebar-menu .el-menu-item {
  border-radius: var(--radius-md);
  margin-bottom: 2px;
  height: 44px;
  font-size: 14px;
}

.sidebar-menu .el-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.06);
}

.sidebar-menu .el-menu-item.is-active {
  background-color: rgba(64, 158, 255, 0.15);
  border-left: 3px solid var(--color-primary-container);
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  transition: background-color 0.15s;
}

.user-info:hover {
  background-color: rgba(255, 255, 255, 0.05);
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background-color: var(--color-secondary);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.user-detail {
  overflow: hidden;
}

.user-name {
  font-size: 13px;
  color: #ffffff;
  font-weight: 500;
}

.user-email {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
