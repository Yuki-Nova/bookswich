<script setup>
// UploadPanel.vue — workspace 空态：上传 hero + 拖拽区（2026-08-14 重构）
import { ref } from 'vue'

const props = defineProps({ quota: Object })
const emit = defineEmits(['changed'])

const file = ref(null)
const uploading = ref(false)
const uploadingMsg = ref('')   // {text, ok} | ''
const progress = ref(0)
const dragOver = ref(false)

function onFile(e) { file.value = e.target.files[0] || null }

function onDrop(e) {
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f && f.type === 'application/pdf') file.value = f
}

async function upload() {
  if (!file.value) return
  uploading.value = true
  uploadingMsg.value = ''
  progress.value = 0
  const fd = new FormData()
  fd.append('file', file.value)
  try {
    const d = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/api/books/upload')
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) progress.value = Math.round((e.loaded / e.total) * 100)
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText)) } catch { reject(new Error('响应解析失败')) }
        } else {
          let msg = `上传失败（HTTP ${xhr.status}）`
          try { const j = JSON.parse(xhr.responseText); if (j.detail) msg = j.detail } catch { /* 非 JSON */ }
          reject(new Error(msg))
        }
      }
      xhr.onerror = () => reject(new Error('网络错误'))
      xhr.upload.onerror = () => reject(new Error('上传中断'))
      xhr.send(fd)
    })
    uploadingMsg.value = { text: `已上传《${d.title}》：${d.page_count} 页，到左侧教材库「解析」`, ok: true }
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
  <div>
    <!-- 空态 hero -->
    <section class="card">
      <div class="empty-hero">
        <span class="ph-icon">📚</span>
        <h2 class="empty-title">把教材变成结构化的 Markdown</h2>
        <p class="empty-desc">上传 PDF → MinerU 分批解析 → 结构重建 → 下载 ZIP / 导入 Obsidian</p>
      </div>

      <div class="upload-zone" :class="{ dragover: dragOver }"
           @dragover.prevent="dragOver = true" @dragleave="dragOver = false"
           @drop.prevent="onDrop">
        <input type="file" accept=".pdf" @change="onFile" />
        <span class="upload-icon">📄</span>
        <span class="upload-title">拖拽 PDF 到此处，或点击选择</span>
        <span class="upload-hint">自动检测页数 · 单文件 ≤ 200MB</span>
        <span v-if="file" class="upload-file">{{ file.name }}</span>
      </div>

      <div class="upload-actions">
        <button class="btn" :disabled="!file || uploading" @click="upload">
          {{ uploading ? `上传中… ${progress}%` : '上传' }}
        </button>
        <button v-if="file" class="btn ghost" @click="file = null">取消</button>
      </div>

      <div v-if="uploading" class="upload-progress">
        <div class="bar">
          <div class="fill" :style="{ width: progress + '%' }"></div>
        </div>
        <div class="task-meta">{{ progress }}%</div>
      </div>
      <p v-if="uploadingMsg" class="msg" :class="uploadingMsg.ok ? 'ok' : 'err'">{{ uploadingMsg.text }}</p>

      <div v-if="quota" class="quota-banner" :class="{ warn: quota.priority_exhausted }">
        <span class="qb-dot"></span>
        <span v-if="!quota.priority_exhausted">
          优先解析 {{ quota.daily_priority_pages }} 页/日（超出进普通队列较慢）· 文件 {{ quota.daily_file_limit }} 份/日
        </span>
        <span v-else>⚠ 优先额度已用完，解析进入普通队列，会较慢</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.empty-hero { text-align: center; padding: 8px 0 20px; }
.empty-hero .ph-icon { font-size: 30px; line-height: 1; }
.empty-title { margin: 10px 0 4px; font-size: 22px; font-weight: 600; letter-spacing: -0.6px; }
.empty-desc { margin: 0; font-size: 13px; color: var(--text-3); }
</style>
