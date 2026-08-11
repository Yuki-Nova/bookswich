<script setup>
// UploadPanel.vue — 右侧主区上传卡片（2026-08-11：教材列表已移至左侧 SidebarPanel）
import { ref } from 'vue'

const props = defineProps({
  quota: Object,
})
const emit = defineEmits(['changed'])

const file = ref(null)
const uploading = ref(false)
const uploadingMsg = ref('')   // 上传反馈消息
const dragOver = ref(false)

function onFile(e) { file.value = e.target.files[0] || null }

// 拖拽支持
function onDrop(e) {
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f && f.type === 'application/pdf') file.value = f
}

async function upload() {
  if (!file.value) return
  uploading.value = true
  uploadingMsg.value = ''
  const fd = new FormData()
  fd.append('file', file.value)
  try {
    const r = await fetch('/api/books/upload', { method: 'POST', body: fd })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '上传失败')
    uploadingMsg.value = { text: `已上传《${d.title}》：${d.page_count} 页，可点左侧「开始解析」`, ok: true }
    file.value = null
    emit('changed')
  } catch (e) {
    uploadingMsg.value = { text: `上传失败：${e.message}`, ok: false }
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <!-- 上传卡片（借鉴 MinerU：大图标 + 主按钮 + 服务策略横幅） -->
  <section class="card upload-card">
    <h2>上传教材 PDF</h2>
    <div class="upload-zone" :class="{ dragover: dragOver }"
         @dragover.prevent="dragOver = true" @dragleave="dragOver = false"
         @drop.prevent="onDrop">
      <input type="file" accept=".pdf" @change="onFile" />
      <span class="upload-icon">📄</span>
      <span class="upload-title">点击选择或拖拽 PDF 到此处</span>
      <span class="upload-hint">自动检测页数，MinerU 分批解析（单文件 ≤ 200MB）</span>
      <span v-if="file" class="upload-file">{{ file.name }}</span>
    </div>
    <div class="upload-actions">
      <button class="btn" :disabled="!file || uploading" @click="upload">
        {{ uploading ? '上传中…' : '上传' }}
      </button>
      <button v-if="file" class="btn ghost" @click="file = null">取消</button>
    </div>
    <p v-if="uploadingMsg" class="msg" :class="uploadingMsg.ok ? 'ok' : 'err'">{{ uploadingMsg.text }}</p>

    <!-- 服务策略横幅（借鉴 MinerU，配额双维度概要） -->
    <div v-if="quota" class="quota-banner" :class="{ warn: quota.priority_exhausted }">
      <span class="qb-dot"></span>
      <span v-if="!quota.priority_exhausted">
        服务策略：优先解析 {{ quota.daily_priority_pages }} 页/日（超出进普通队列较慢）· 文件 {{ quota.daily_file_limit }} 份/日
      </span>
      <span v-else>⚠ 优先额度已用完（{{ quota.daily_priority_pages }} 页/日），解析进入普通队列，会较慢</span>
    </div>
  </section>
</template>
