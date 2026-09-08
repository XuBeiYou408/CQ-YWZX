<script setup>
import { ref } from 'vue'

defineProps({
  cases: Array,
  getColor: Function,
})

const expandedId = ref(null)

function toggleExpand(row) {
  expandedId.value = expandedId.value === row.id ? null : row.id
}
</script>

<template>
  <div class="case-table">
    <h3 class="section-title">评估用例明细</h3>
    <div class="table-wrap">
      <el-table
        :data="cases"
        stripe
        style="width: 100%"
        row-class-name="case-row"
        @row-click="toggleExpand"
        @expand-change="() => {}"
      >
        <el-table-column width="40" align="center">
          <template #default="{ row }">
            <el-icon
              :class="['expand-arrow', { expanded: expandedId === row.id }]"
              :size="16"
            >
              <ArrowRight />
            </el-icon>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="编号" width="85" />
        <el-table-column prop="question" label="问题" show-overflow-tooltip min-width="180" />
        <el-table-column label="命中" width="70" align="center">
          <template #default="{ row }">
            <span
              :class="['status-badge', row.retrieval_hit ? 'success' : 'error']"
            >
              {{ row.retrieval_hit ? '成功' : '失败' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="忠实度" width="85" align="center">
          <template #default="{ row }">
            <span
              v-if="row.faithfulness != null"
              :style="{ color: getColor(row.faithfulness), fontWeight: 600 }"
            >
              {{ row.faithfulness.toFixed(2) }}
            </span>
            <span v-else class="na">—</span>
          </template>
        </el-table-column>
        <el-table-column label="相关性" width="85" align="center">
          <template #default="{ row }">
            <span
              v-if="row.answer_relevance != null"
              :style="{ color: getColor(row.answer_relevance), fontWeight: 600 }"
            >
              {{ row.answer_relevance.toFixed(2) }}
            </span>
            <span v-else class="na">—</span>
          </template>
        </el-table-column>
        <el-table-column label="完整性" width="85" align="center">
          <template #default="{ row }">
            <span
              v-if="row.completeness != null"
              :style="{ color: getColor(row.completeness), fontWeight: 600 }"
            >
              {{ row.completeness.toFixed(2) }}
            </span>
            <span v-else class="na">—</span>
          </template>
        </el-table-column>
      </el-table>

      <transition name="accordion">
        <div
          v-if="expandedId"
          :key="expandedId"
          class="expand-panel"
        >
          <template v-for="row in cases" :key="row.id">
            <div v-if="row.id === expandedId" class="expand-grid">
              <div class="expand-card">
                <h4 class="expand-card-title">检索上下文与系统回答</h4>
                <div v-if="row.generated_answer" class="expand-block">
                  <p class="expand-text">{{ row.generated_answer }}</p>
                </div>
                <div v-else class="expand-empty">暂无系统回答</div>
              </div>
              <div class="expand-card">
                <h4 class="expand-card-title">LLM 裁判分析判词</h4>
                <div v-if="row.judge_reason" class="expand-block">
                  <p class="expand-text">{{ row.judge_reason }}</p>
                </div>
                <div v-else class="expand-empty">暂无评分理由</div>
                <div v-if="row.faithfulness != null && row.faithfulness < 0.4" class="diagnostic-log">
                  <h4 class="log-title">诊断日志</h4>
                  <ul class="log-list">
                    <li>忠实度严重低于阈值 ({{ row.faithfulness.toFixed(2) }})</li>
                    <li>建议强化 Prompt 中"仅基于上下文回答"约束</li>
                    <li>可考虑降低 LLM temperature 减少幻觉</li>
                  </ul>
                </div>
              </div>
            </div>
          </template>
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.case-table {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: 20px;
  box-shadow: var(--shadow-card);
  margin-bottom: 24px;
}

.section-title {
  font: var(--text-section);
  color: #303133;
  margin: 0 0 16px 0;
}

.table-wrap {
  overflow: hidden;
}

.case-row {
  cursor: pointer;
}

.expand-arrow {
  transition: transform 0.3s ease;
  color: #a8abb2;
}

.expand-arrow.expanded {
  transform: rotate(90deg);
  color: var(--color-primary);
}

.status-badge {
  display: inline-block;
  font: var(--text-metadata);
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  text-transform: none;
  letter-spacing: 0;
}

.status-badge.success {
  color: var(--color-success-text);
  background: var(--color-success-bg);
}

.status-badge.error {
  color: var(--color-error-text);
  background: var(--color-error-bg);
}

.na { color: #c0c4cc; }

/* === Expand Panel === */
.expand-panel {
  border-top: 1px solid var(--color-outline-variant);
  background: var(--color-surface-low);
  overflow: hidden;
}

.accordion-enter-active {
  animation: slideDown 0.3s ease-out;
}

.accordion-leave-active {
  animation: slideDown 0.25s ease-in reverse;
}

@keyframes slideDown {
  from {
    opacity: 0;
    max-height: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    max-height: 600px;
    transform: translateY(0);
  }
}

.expand-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  padding: 20px;
}

.expand-card {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-soft);
}

.expand-card-title {
  font: var(--text-metadata);
  color: var(--color-secondary);
  margin: 0 0 12px 0;
  text-transform: none;
  letter-spacing: 0;
  font-size: 13px;
  font-weight: 600;
}

.expand-block {
  max-height: 280px;
  overflow-y: auto;
}

.expand-text {
  font: var(--text-body);
  color: #303133;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.expand-empty {
  font-size: 13px;
  color: #a8abb2;
  font-style: italic;
}

.diagnostic-log {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--color-outline-variant);
}

.log-title {
  font: var(--text-metadata);
  color: var(--color-error-text);
  font-weight: 600;
  margin: 0 0 8px 0;
  text-transform: none;
  letter-spacing: 0;
  font-size: 12px;
}

.log-list {
  padding-left: 18px;
  font-size: 13px;
  color: var(--color-secondary);
  line-height: 1.8;
}
</style>
