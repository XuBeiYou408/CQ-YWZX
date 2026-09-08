<script setup>
defineProps({
  summary: Object,
  getColor: Function,
})

function barWidth(score, isMs) {
  if (score == null) return '0%'
  if (isMs) {
    return Math.min(100, Math.max(0, (1 - score / 3) * 100)).toFixed(1) + '%'
  }
  return Math.min(100, Math.max(0, score * 100)).toFixed(1) + '%'
}
</script>

<template>
  <div class="score-cards">
    <div
      v-for="card in [
        { key: 'hitRate', label: '命中率 (Hit@5)', value: summary.hitRate + '%', color: parseFloat(summary.hitRate) >= 70 ? 'var(--color-success-text)' : parseFloat(summary.hitRate) >= 40 ? 'var(--color-warning-text)' : 'var(--color-error-text)', bar: summary.hitRate + '%' },
        { key: 'mrr', label: 'MRR', value: summary.mrr, color: parseFloat(summary.mrr) >= 0.5 ? 'var(--color-success-text)' : parseFloat(summary.mrr) >= 0.25 ? 'var(--color-warning-text)' : 'var(--color-error-text)', bar: (parseFloat(summary.mrr) * 100).toFixed(1) + '%' },
        { key: 'faithfulness', label: '忠实度', value: summary.avgFaithfulness != null ? summary.avgFaithfulness.toFixed(2) : '—', color: getColor(summary.avgFaithfulness), bar: summary.avgFaithfulness != null ? (summary.avgFaithfulness * 100).toFixed(1) + '%' : '0%' },
        { key: 'relevance', label: '相关性', value: summary.avgRelevance != null ? summary.avgRelevance.toFixed(2) : '—', color: getColor(summary.avgRelevance), bar: summary.avgRelevance != null ? (summary.avgRelevance * 100).toFixed(1) + '%' : '0%' },
        { key: 'completeness', label: '完整性', value: summary.avgCompleteness != null ? summary.avgCompleteness.toFixed(2) : '—', color: getColor(summary.avgCompleteness), bar: summary.avgCompleteness != null ? (summary.avgCompleteness * 100).toFixed(1) + '%' : '0%' },
        { key: 'ttft', label: '首字延迟 (TTFT)', value: summary.avgTTFT != null ? summary.avgTTFT.toFixed(2) + 's' : '—', color: summary.avgTTFT != null && summary.avgTTFT <= 1 ? 'var(--color-success-text)' : summary.avgTTFT != null && summary.avgTTFT <= 3 ? 'var(--color-warning-text)' : 'var(--color-error-text)', bar: summary.avgTTFT != null ? Math.min(100, Math.max(0, (1 - summary.avgTTFT / 3) * 100)).toFixed(1) + '%' : '0%' },
        { key: 'latency', label: '端到端延迟', value: summary.avgLatency != null ? summary.avgLatency.toFixed(2) + 's' : '—', color: summary.avgLatency != null && summary.avgLatency <= 5 ? 'var(--color-success-text)' : summary.avgLatency != null && summary.avgLatency <= 15 ? 'var(--color-warning-text)' : 'var(--color-error-text)', bar: summary.avgLatency != null ? Math.min(100, Math.max(0, (1 - summary.avgLatency / 20) * 100)).toFixed(1) + '%' : '0%' },
      ]"
      :key="card.key"
      class="score-card"
    >
      <div class="card-label">{{ card.label }}</div>
      <div class="card-value" :style="{ color: card.color }">{{ card.value }}</div>
      <div class="card-bar-track">
        <div
          class="card-bar-fill"
          :style="{ width: card.bar, backgroundColor: card.color }"
        ></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.score-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.score-card {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: 18px 16px 14px;
  box-shadow: var(--shadow-card);
}

.card-label {
  font: var(--text-metadata);
  color: var(--color-secondary);
  margin-bottom: 8px;
  text-transform: none;
  letter-spacing: 0;
}

.card-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 10px;
}

.card-bar-track {
  height: 4px;
  background: var(--color-surface-low);
  border-radius: 2px;
  overflow: hidden;
}

.card-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease;
}
</style>
