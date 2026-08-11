<script setup>
// UploadPanel.vue — 右侧主区：上传卡片 + 教材列表（2026-08-11 L-5 去轮询，进度移交侧栏任务卡片）
import { ref, watch } from 'vue'

const props = defineProps({
  books: Array,
  quota: Object,
  settings: Object,
  parseTask: Object,
})
const emit = defineEmits(['changed'])

const file = ref(null)
const uploading = ref(false)
const uploadingMsg = ref('')   // 上传/导入/删除的反馈消息（解析消息在侧栏 parseTask.parseMsg）
const importingId = ref(null)  // 正在导入 Obsidian 的书
const deletingId = ref(null)   // 正在删除的书
const dragOver = ref(false)
const chapterMaps = ref({})    // bookId -> [{no, title}]

const STATUS_TEXT = {
  pending: '待解析',
  parsing: '解析中',
  parsed: '解析完成',
  structure_ok: '结构完成',
  failed: '解析失败',
}

const STATUS_PILL = {
  pending: 'pill',
  parsing: 'pill blue',
  parsed: 'pill green',
  structure_ok: 'pill green',
  failed: 'pill red',
}

watch(() => props.books, loadChapters, { deep: true })

async function loadChapters() {
  for (const b of props.books) {
    if (chapterMaps.value[b.id]) continue
    try {
      const r = await fetch(`/api/books/${b.id}/chapters`)
      const d = await r.json()
      if (d.chapters) chapterMaps.value[b.id] = d.chapters
      if (b._ch === undefined) b._ch = 0
    } catch { /* 未重建的书忽略 */ }
  }
}

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
    uploadingMsg.value = { text: `已上传《${d.title}》：${d.page_count} 页`, ok: true }
    file.value = null
    emit('changed')
  } catch (e) {
    uploadingMsg.value = { text: `上传失败：${e.message}`, ok: false }
  } finally {
    uploading.value = false
  }
}

// 开始/续跑解析：进度显示在左侧「解析任务」卡片（L-5 上移）
function resumeParse(b) {
  if (props.parseTask) props.parseTask.startParse(b, props.quota)
}

// 导入 Obsidian：按章拆分写入 vault/教材/<书名>/
async function importObsidian(b) {
  importingId.value = b.id
  uploadingMsg.value = ''
  try {
    const r = await fetch(`/api/books/${b.id}/import-obsidian`, { method: 'POST' })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '导入失败')
    uploadingMsg.value = { text: `✅ 已导入 Obsidian：${d.files} 个文件（图片已转 OSS 外链）`, ok: true }
  } catch (e) {
    uploadingMsg.value = { text: `导入失败：${e.message}`, ok: false }
  } finally {
    importingId.value = null
  }
}

function isReady(b) {
  return b.parse_status === 'parsed' || b.parse_status === 'structure_ok'
}

// 删除教材：清服务器遗留文件（raw PDF + md/ + build/）+ db 记录
async function deleteBook(b) {
  if (b.parse_status === 'parsing') return
  if (!confirm(`删除《${b.title}》？\n将移除服务器上该教材的全部解析产物（PDF、批次 md、结构重建产物），不可恢复。`)) return
  deletingId.value = b.id
  uploadingMsg.value = ''
  try {
    const r = await fetch(`/api/books/${b.id}`, { method: 'DELETE' })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '删除失败')
    uploadingMsg.value = { text: `🗑 已删除《${b.title}》`, ok: true }
    emit('changed')
  } catch (e) {
    uploadingMsg.value = { text: `删除失败：${e.message}`, ok: false }
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div>
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

    <!-- 教材列表 -->
    <section class="card">
      <h2>已入库教材 <span v-if="books.length" style="color:var(--text-muted);font-weight:400;font-size:13px">（{{ books.length }}）</span></h2>

      <div v-if="books.length" class="book-list">
        <div v-for="b in books" :key="b.id" class="book-card"
             :class="{ parsing: b.parse_status === 'parsing' }">
          <div class="book-top">
            <span class="book-title">{{ b.title }}</span>
            <span :class="['status-pill', STATUS_PILL[b.parse_status] || 'pill']">
              {{ STATUS_TEXT[b.parse_status] || b.parse_status }}
            </span>
          </div>
          <div class="book-meta">
            <span>#{{ b.id }}</span>
            <span class="sep">·</span>
            <span>{{ b.page_count }} 页</span>
            <span class="sep">·</span>
            <span>进度 {{ b.parse_progress || '—' }}</span>
          </div>

          <div class="book-ops">
            <button v-if="b.parse_status === 'pending' || b.parse_status === 'failed'"
                    class="btn ghost" @click="resumeParse(b)">开始解析</button>
            <span v-else-if="b.parse_status === 'parsing'" class="pill blue"><span class="dot"></span>解析中…</span>

            <template v-if="isReady(b)">
              <a class="link-btn" :href="`/api/books/${b.id}/export?format=rebuilt&images=oss`" download>下载 ZIP</a>
              <a class="link-btn muted" :href="`/api/books/${b.id}/export?format=raw&images=oss`" download>原始 ZIP</a>
              <a class="link-btn purple" :href="`/api/books/${b.id}/export?format=obsidian&images=oss`" download>Obsidian 版</a>
              <button v-if="settings && settings.obsidian_vault_configured"
                      class="btn purple" style="padding:4px 12px;font-size:12px"
                      :disabled="importingId === b.id" @click="importObsidian(b)">
                {{ importingId === b.id ? '导入中…' : '导入 Obsidian' }}
              </button>
              <select v-if="isReady(b)" v-model="b._ch" class="chapter-select">
                <option :value="0">整本</option>
                <option v-for="c in chapterMaps[b.id] || []" :key="c.no" :value="c.no">
                  {{ c.no }}. {{ c.title }}
                </option>
              </select>
              <a v-if="b._ch && isReady(b)" class="link-btn"
                 :href="`/api/books/${b.id}/export?format=rebuilt&chapter=${b._ch}`" download>
                章节 ZIP
              </a>
              <span class="grow"></span>
              <button class="link-btn" :class="{ muted: b.parse_status === 'parsing' }"
                      :disabled="b.parse_status === 'parsing' || deletingId === b.id"
                      @click="deleteBook(b)" title="删除该教材全部解析产物">
                {{ deletingId === b.id ? '删除中…' : '🗑 删除' }}
              </button>
            </template>
            <button v-if="!isReady(b) && b.parse_status !== 'parsing'"
                    class="link-btn" :disabled="deletingId === b.id" @click="deleteBook(b)"
                    title="删除该教材全部解析产物">
              {{ deletingId === b.id ? '删除中…' : '🗑 删除' }}
            </button>
          </div>
        </div>
      </div>

      <div v-else class="empty">
        <span class="big">📚</span>
        暂无教材，先上传一份 PDF 吧
      </div>
    </section>
  </div>
</template>

<style scoped>
.status-pill { flex-shrink: 0; }
</style>
