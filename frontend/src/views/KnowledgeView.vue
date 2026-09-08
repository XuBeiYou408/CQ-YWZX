<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getDocuments, uploadDocument, deleteDocument } from '../api/index.js'

const loading = ref(false)
const uploading = ref(false)
const documents = ref([])
const totalCount = ref(0)
const totalSize = ref('0 B')
const storagePath = ref('')
const searchQuery = ref('')

async function fetchDocuments() {
  loading.value = true
  try {
    const res = await getDocuments()
    documents.value = res.documents || []
    totalCount.value = res.total_count || 0
    totalSize.value = res.total_size || '0 B'
    storagePath.value = res.storage_path || ''
  } catch (err) {
    ElMessage.error(err.message || '获取文档列表失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchDocuments)

const filteredDocs = computed(() => {
  if (!searchQuery.value.trim()) return documents.value
  const q = searchQuery.value.toLowerCase().trim()
  return documents.value.filter(doc => 
    (doc.name && doc.name.toLowerCase().includes(q)) ||
    (doc.type && doc.type.toLowerCase().includes(q))
  )
})

async function handleCustomUpload(options) {
  const { file, onSuccess, onError } = options
  uploading.value = true
  try {
    const result = await uploadDocument(file)
    ElMessage.success(`文档 "${file.name}" 解析并建立索引成功！`)
    onSuccess(result)
    await fetchDocuments()
  } catch (err) {
    ElMessage.error(err.message || `上传 "${file.name}" 失败`)
    onError(err)
  } finally {
    uploading.value = false
  }
}

async function handleDelete(fileName) {
  try {
    await deleteDocument(fileName)
    ElMessage.success(`文档 "${fileName}" 已成功移除并更新知识库！`)
    await fetchDocuments()
  } catch (err) {
    ElMessage.error(err.message || '删除文档失败')
  }
}

function getTagType(type) {
  switch (type) {
    case 'PDF': return 'danger'
    case 'DOCX': return 'primary'
    case 'MD': return 'warning'
    case 'TXT': return 'info'
    default: return 'success'
  }
}
</script>

<template>
  <div class="knowledge-container">
    <!-- 头部横幅 -->
    <div class="knowledge-header">
      <div class="header-left">
        <h2>📚 企业本地知识库</h2>
        <p class="subtitle">
          管理用于检索问答的本地企业业务资料。上传后系统将自动切片、向量化并注入 Agent 混合检索环。
        </p>
      </div>
      <div class="header-right">
        <el-button
          type="primary"
          plain
          :loading="loading"
          @click="fetchDocuments"
        >
          <el-icon><Refresh /></el-icon>
          <span>刷新列表</span>
        </el-button>
      </div>
    </div>

    <!-- 概览指标卡片 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon icon-docs">
          <el-icon><Files /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-val">{{ totalCount }} 篇</div>
          <div class="stat-lbl">已就绪知识库文档</div>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon icon-size">
          <el-icon><Coin /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-val">{{ totalSize }}</div>
          <div class="stat-lbl">资料存储占用</div>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon icon-formats">
          <el-icon><CircleCheck /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-val">PDF / Word / MD / TXT</div>
          <div class="stat-lbl">支持格式 (自动解析分块)</div>
        </div>
      </div>
    </div>

    <!-- 上传拖拽区域 -->
    <div class="upload-section">
      <el-upload
        class="kb-uploader"
        drag
        action="#"
        :http-request="handleCustomUpload"
        :show-file-list="false"
        accept=".pdf,.docx,.txt,.md"
        :disabled="uploading"
      >
        <div class="uploader-body">
          <el-icon v-if="!uploading" class="uploader-icon"><UploadFilled /></el-icon>
          <el-icon v-else class="uploader-icon is-loading"><Loading /></el-icon>
          
          <div class="uploader-text">
            <div class="primary-text">
              {{ uploading ? '正在解析文档并写入向量数据库，请稍候...' : '将企业文档拖拽至此处，或 点击上传' }}
            </div>
            <div class="secondary-text">
              支持格式：.pdf、.docx (Word)、.md (Markdown)、.txt (纯文本)
            </div>
          </div>
        </div>
      </el-upload>
    </div>

    <!-- 文档列表卡片 -->
    <div class="table-card">
      <div class="table-toolbar">
        <div class="toolbar-title">
          <span>资料明细</span>
          <span class="count-badge">{{ filteredDocs.length }} 个文件</span>
        </div>
        <div class="toolbar-search">
          <el-input
            v-model="searchQuery"
            placeholder="搜索文档名称或格式..."
            prefix-icon="Search"
            clearable
            style="width: 240px"
          />
        </div>
      </div>

      <el-table
        :data="filteredDocs"
        v-loading="loading"
        stripe
        style="width: 100%"
        empty-text="暂无入库资料，请在上方拖拽或点击上传文档"
      >
        <el-table-column label="文档名称" min-width="260">
          <template #default="{ row }">
            <div class="doc-name-cell">
              <el-icon class="doc-file-icon"><Document /></el-icon>
              <span class="doc-name-text" :title="row.name">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="格式" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="getTagType(row.type)" size="small" effect="light">
              {{ row.type }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="size" label="文件大小" width="120" align="center" />

        <el-table-column label="检索状态" width="130" align="center">
          <template #default="{ row }">
            <el-tag type="success" size="small" effect="plain">
              <el-icon style="margin-right: 4px"><Check /></el-icon>
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="mtime" label="入库时间" width="190" align="center" />

        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-popconfirm
              :title="`确认从知识库中删除 ${row.name} 吗？`"
              confirm-button-text="删除"
              cancel-button-text="取消"
              confirm-button-type="danger"
              @confirm="handleDelete(row.name)"
            >
              <template #reference>
                <el-button type="danger" text size="small">
                  <el-icon><Delete /></el-icon>
                  <span>删除</span>
                </el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.knowledge-container {
  padding: 32px;
  max-width: 1200px;
  margin: 0 auto;
  min-height: 100%;
  box-sizing: border-box;
}

.knowledge-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.knowledge-header h2 {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 6px;
}

.subtitle {
  font-size: 14px;
  color: #64748b;
  line-height: 1.5;
}

/* 统计卡片 */
.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: #ffffff;
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  border: 1px solid #f1f5f9;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}

.icon-docs {
  background: #eff6ff;
  color: #2563eb;
}

.icon-size {
  background: #f0fdf4;
  color: #16a34a;
}

.icon-formats {
  background: #faf5ff;
  color: #9333ea;
}

.stat-info .stat-val {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.stat-info .stat-lbl {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}

/* 上传卡片 */
.upload-section {
  margin-bottom: 24px;
}

.kb-uploader :deep(.el-upload) {
  width: 100%;
}

.kb-uploader :deep(.el-upload-dragger) {
  width: 100%;
  padding: 32px 20px;
  border-radius: 14px;
  background: #ffffff;
  border: 2px dashed #cbd5e1;
  transition: all 0.2s ease;
}

.kb-uploader :deep(.el-upload-dragger:hover) {
  border-color: #2563eb;
  background: #f8faff;
}

.uploader-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.uploader-icon {
  font-size: 48px;
  color: #3b82f6;
}

.uploader-text .primary-text {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
}

.uploader-text .secondary-text {
  font-size: 12px;
  color: #94a3b8;
}

/* 列表表格卡片 */
.table-card {
  background: #ffffff;
  border-radius: 14px;
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  border: 1px solid #f1f5f9;
}

.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.toolbar-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.count-badge {
  font-size: 12px;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 9999px;
}

.doc-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-file-icon {
  color: #64748b;
  font-size: 16px;
  flex-shrink: 0;
}

.doc-name-text {
  font-weight: 500;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
