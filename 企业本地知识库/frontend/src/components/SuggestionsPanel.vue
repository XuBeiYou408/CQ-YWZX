<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  summary: Object,
})

const applying = ref(false)

function handleApply() {
  applying.value = true
  setTimeout(() => {
    applying.value = false
  }, 2000)
}

const issues = computed(() => {
  const items = []
  const s = props.summary
  if (!s) return items

  if (parseFloat(s.hitRate) < 70) {
    items.push({
      id: 'retrieval',
      title: '检索命中率偏低',
      detail: `Hit@5 仅为 ${s.hitRate}%，核心文档未能进入 Top-5 召回。`,
      severity: 'error',
    })
  }
  if (s.avgFaithfulness != null && s.avgFaithfulness < 0.7) {
    items.push({
      id: 'faithfulness',
      title: '回答忠实度不足',
      detail: 'LLM 存在幻觉倾向，生成内容超出上下文范围。',
      severity: 'warning',
    })
  }
  if (s.avgRelevance != null && s.avgRelevance < 0.6) {
    items.push({
      id: 'relevance',
      title: '回答相关性待提升',
      detail: '检索噪声影响生成质量。',
      severity: 'warning',
    })
  }
  if (s.avgCompleteness != null && s.avgCompleteness < 0.5) {
    items.push({
      id: 'completeness',
      title: '回答完整性不足',
      detail: '检索上下文可能缺失关键信息。',
      severity: 'info',
    })
  }
  return items
})

const optimizations = [
  {
    step: '01',
    title: '优化 Embedding 模型',
    desc: '升级至 BGE-large-zh-v1.5 或 M3E 等更强语义模型，提升语义检索精度。',
    icon: 'Connection',
  },
  {
    step: '02',
    title: '升级混合搜索权重',
    desc: '调整 BM25 与向量检索的融合权重，增加稀疏检索对专有名词的召回贡献。',
    icon: 'Setting',
  },
  {
    step: '03',
    title: '引入 KV Cache 缓存',
    desc: '为 LLM 推理启用 KV Cache，降低重复问题的生成延迟 40%-60%。',
    icon: 'Timer',
  },
]
</script>

<template>
  <div class="suggestions-wrapper">
    <h3 class="section-title">系统瓶颈与优化</h3>
    <div class="suggestions-grid">
      <div class="bottleneck-card">
        <h4 class="card-header">瓶颈诊断</h4>
        <div v-if="issues.length === 0" class="no-issues">
          <div class="no-issues-icon">&#10003;</div>
          <p>系统运行状态良好，暂无明确瓶颈</p>
        </div>
        <div v-for="item in issues" :key="item.id" class="issue-item">
          <div class="issue-dot"></div>
          <div class="issue-body">
            <div class="issue-title">{{ item.title }}</div>
            <div class="issue-detail">{{ item.detail }}</div>
          </div>
        </div>
      </div>

      <div class="optimize-card">
        <h4 class="card-header light">优化路线</h4>
        <div class="opt-list">
          <div v-for="opt in optimizations" :key="opt.step" class="opt-item">
            <div class="opt-step">{{ opt.step }}</div>
            <div class="opt-body">
              <div class="opt-title">{{ opt.title }}</div>
              <div class="opt-desc">{{ opt.desc }}</div>
            </div>
          </div>
        </div>
        <el-button
          type="primary"
          :loading="applying"
          class="apply-btn"
          @click="handleApply"
        >
          {{ applying ? '部署中...' : '应用优化方案' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.suggestions-wrapper {
  margin-bottom: 24px;
}

.section-title {
  font: var(--text-section);
  color: #303133;
  margin: 0 0 16px 0;
}

.suggestions-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

/* === Bottleneck Card === */
.bottleneck-card {
  background: var(--color-inverse);
  border-radius: var(--radius-xl);
  padding: 24px;
  color: #fff;
}

.bottleneck-card .card-header {
  font: var(--text-section);
  color: #fff;
  margin: 0 0 20px 0;
}

.no-issues {
  text-align: center;
  padding: 20px 0;
  opacity: 0.8;
  font-size: 14px;
}

.no-issues-icon {
  font-size: 32px;
  margin-bottom: 8px;
  color: var(--color-success-text);
}

.issue-item {
  display: flex;
  gap: 14px;
  margin-bottom: 20px;
}

.issue-item:last-child { margin-bottom: 0; }

.issue-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-warning-text);
  margin-top: 6px;
  flex-shrink: 0;
}

.issue-body { flex: 1; }

.issue-title {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  margin-bottom: 4px;
}

.issue-detail {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.65);
  line-height: 1.6;
}

/* === Optimize Card === */
.optimize-card {
  background: var(--color-primary);
  border-radius: var(--radius-xl);
  padding: 24px;
  color: #fff;
}

.optimize-card .card-header {
  font: var(--text-section);
  color: #fff;
  margin: 0 0 20px 0;
}

.opt-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 20px;
}

.opt-item {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.opt-step {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.opt-body { flex: 1; }

.opt-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 2px;
}

.opt-desc {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.6;
}

.apply-btn {
  --el-button-bg-color: rgba(255, 255, 255, 0.2);
  --el-button-border-color: rgba(255, 255, 255, 0.3);
  --el-button-text-color: #ffffff;
  --el-button-hover-bg-color: rgba(255, 255, 255, 0.3);
  --el-button-hover-border-color: rgba(255, 255, 255, 0.4);
  width: 100%;
  height: 42px;
  font-size: 14px;
  border-radius: var(--radius-lg);
}
</style>
