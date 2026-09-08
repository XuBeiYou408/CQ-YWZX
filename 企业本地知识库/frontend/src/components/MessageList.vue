<script setup>
import MessageBubble from './MessageBubble.vue'

defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
})
</script>

<template>
  <div class="message-list">
    <MessageBubble
      v-for="(msg, idx) in messages"
      :key="idx"
      :message="msg"
    />
  </div>
</template>

<style scoped>
.message-list {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding-bottom: 16px;
}
</style>
