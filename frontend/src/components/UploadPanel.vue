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
const progress = ref(0)        // 上传进度 0-100（XHR onprogress）
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
  progress.value = 0
  const fd = new FormData()
  fd.append('file', file.value)
  try {
    const d = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/api/books/upload')
      // 上传进度事件（fetch 不提供 onprogress，必须用 XHR）
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) progress.value = Math.round((e.loaded / e.total) * 100)
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText)) } catch { reject(new Error('响应解析失败')) }
        } else {
          let msg = `上传失败（HTTP ${xhr.status}）`
          try { const j = JSON.parse(xhr.responseText); if (j.detail) msg = j.detail } catch { /* 非 JSON 响应 */ }
          reject(new Error(msg))
        }
      }
      xhr.onerror = () => reject(new Error('网络错误'))
      xhr.upload.onerror = () => reject(new Error('上传中断'))
      xhr.send(fd)
    })
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
        {{ uploading ? `上传中… ${progress}%` : '上传' }}
      </button>
      <button v-if="file" class="btn ghost" @click="file = null">取消</button>
    </div>
    <!-- 上传进度条（2026-08-11：XHR onprogress 实时更新） -->
    <div v-if="uploading" class="upload-progress">
      <div class="bar">
        <div class="fill" :style="{ width: progress + '%' }"></div>
      </div>
      <div class="task-meta">{{ progress }}%</div>
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
