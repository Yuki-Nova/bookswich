<script setup>
import { ref, watch } from 'vue'

const props = defineProps({ books: Array, quota: Object, settings: Object })
const emit = defineEmits(['changed'])

const file = ref(null)
const uploading = ref(false)
const uploadingMsg = ref('')
const parsingId = ref(null)
const parsing = ref(false)
const progress = ref('')
const chapterMaps = ref({})   // bookId -> [{no, title}]
const importingId = ref(null) // 正在导入 Obsidian 的书
const dragOver = ref(false)

let timer = null

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

// 自动接管「解析中」的书（含刷新页面后恢复轮询）
watch(() => props.books, (list) => {
  const busy = (list || []).find(b => b.parse_status === 'parsing')
  if (busy && busy.id !== parsingId.value) {
    parsingId.value = busy.id
    parsing.value = true
    progress.value = busy.parse_progress || ''
    schedulePoll()
  }
}, { deep: true, immediate: true })

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

// 进度条：parse_progress "2/13" → 百分比 + 文案
function progressInfo(p) {
  const m = /(\d+)\/(\d+)/.exec(p || '')
  if (!m) return { pct: 0, text: p || '' }
  const done = +m[1], total = +m[2]
  return { pct: total ? Math.round(done / total * 100) : 0, text: `第 ${done}/${total} 批` }
}

function schedulePoll() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(poll, 4000)
}

async function poll() {
  if (!parsingId.value) return
  const r = await fetch(`/api/books/${parsingId.value}`)
  const d = await r.json()
  progress.value = d.parse_progress || ''
  if (d.parse_status === 'parsing') {
    schedulePoll()
  } else {
    parsing.value = false
    parsingId.value = null
    uploadingMsg.value = d.parse_status === 'parsed'
      ? { text: '✅ 解析完成，可下载 Markdown', ok: true }
      : { text: `解析结束：${d.parse_status}（进度 ${d.parse_progress}）`, ok: false }
    emit('changed')
  }
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

// 每本书的「开始/续跑解析」（缓存续跑：已解析批次自动跳过，不重复计费）
async function resumeParse(b) {
  parsingId.value = b.id
  parsing.value = true
  uploadingMsg.value = ''
  progress.value = b.parse_progress || ''
  try {
    const r = await fetch(`/api/books/${b.id}/parse`, { method: 'POST' })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '启动失败')
    schedulePoll()
  } catch (e) {
    parsing.value = false
    parsingId.value = null
    uploadingMsg.value = { text: `解析启动失败：${e.message}`, ok: false }
  }
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
</script>

<template>
  <div>
    <!-- 上传区 -->
    <section class="card">
      <h2>上传教材 PDF</h2>
      <div class="upload-zone" :class="{ dragover: dragOver }"
           @dragover.prevent="dragOver = true" @dragleave="dragOver = false"
           @drop.prevent="onDrop">
        <input type="file" accept=".pdf" @change="onFile" />
        <span class="upload-icon">📄</span>
        <span class="upload-title">点击选择或拖拽 PDF 到此处</span>
        <span class="upload-hint">自动检测页数，MinerU 分批解析（每天配额 {{ quota?.daily_limit || 1000 }} 页）</span>
        <span v-if="file" class="upload-file">{{ file.name }}</span>
      </div>
      <div class="upload-actions">
        <button class="btn" :disabled="!file || uploading" @click="upload">
          {{ uploading ? '上传中…' : '上传' }}
        </button>
        <button v-if="file" class="btn ghost" @click="file = null">取消</button>
      </div>
      <p v-if="uploadingMsg" class="msg" :class="uploadingMsg.ok ? 'ok' : 'err'">{{ uploadingMsg.text }}</p>

      <div v-if="parsing" class="prog">
        <div class="bar"><div class="fill" :style="{ width: progressInfo(progress).pct + '%' }"></div></div>
        <span class="prog-text">⏳ {{ progressInfo(progress).text }}</span>
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

          <div v-if="b.parse_status === 'parsing'" class="prog">
            <div class="bar"><div class="fill" :style="{ width: progressInfo(b.parse_progress).pct + '%' }"></div></div>
            <span class="prog-text">{{ progressInfo(b.parse_progress).text }}</span>
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
            </template>
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
