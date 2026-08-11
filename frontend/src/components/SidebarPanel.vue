<script setup>
// SidebarPanel.vue — 左侧边栏：限额卡片 + 解析任务卡片 + 已入库教材列表（2026-08-11）
import { computed, ref, watch } from 'vue'

const props = defineProps({
  books: Array,
  quota: Object,
  settings: Object,
  parseTask: Object,
  selectedId: Number,   // 对比预览选中的教材（高亮）
})
const emit = defineEmits(['changed', 'preview'])

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

const importingId = ref(null)  // 正在导入 Obsidian 的书
const deletingId = ref(null)   // 正在删除的书
const chapterMaps = ref({})    // bookId -> [{no, title}]

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

// 实时进度："2/13" → {pct, text}
const parseInfo = computed(() => {
  const p = props.parseTask?.progress || ''
  const m = /(\d+)\/(\d+)/.exec(p)
  if (!m) return { pct: 0, text: p || '—' }
  return { pct: Math.round(+m[1] / +m[2] * 100), text: `第 ${m[1]}/${m[2]} 批` }
})

const busyBook = computed(() => (props.books || []).find(b => b.parse_status === 'parsing'))

// 待解析 / 失败（可快捷开始解析）
const actionable = computed(() =>
  (props.books || []).filter(b => b.parse_status === 'pending' || b.parse_status === 'failed'))

const quotaPct = computed(() => {
  if (!props.quota) return 0
  return Math.round((props.quota.priority_used || 0) / (props.quota.daily_priority_pages || 1000) * 100)
})

function startParse(b) {
  if (props.parseTask) props.parseTask.startParse(b, props.quota)
}

function isReady(b) {
  return b.parse_status === 'parsed' || b.parse_status === 'structure_ok'
}

// 下载链接：整本 rebuilt / 按章 rebuilt（复用原 UploadPanel 语义）
function chapterHref(b) {
  return b._ch
    ? `/api/books/${b.id}/export?format=rebuilt&chapter=${b._ch}`
    : `/api/books/${b.id}/export?format=rebuilt&images=oss`
}

// 导入 Obsidian：按章拆分写入 vault/教材/<书名>/
async function importObsidian(b) {
  importingId.value = b.id
  try {
    const r = await fetch(`/api/books/${b.id}/import-obsidian`, { method: 'POST' })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '导入失败')
    alert(`✅ 已导入 Obsidian：${d.files} 个文件（图片已转 OSS 外链）`)
  } catch (e) {
    alert(`导入失败：${e.message}`)
  } finally {
    importingId.value = null
  }
}

// 删除教材：清服务器遗留文件（raw PDF + md/ + build/）+ db 记录
async function deleteBook(b) {
  if (b.parse_status === 'parsing') return
  if (!confirm(`删除《${b.title}》？\n将移除服务器上该教材的全部解析产物（PDF、批次 md、结构重建产物），不可恢复。`)) return
  deletingId.value = b.id
  try {
    const r = await fetch(`/api/books/${b.id}`, { method: 'DELETE' })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '删除失败')
    alert(`🗑 已删除《${b.title}》`)
    emit('changed')
  } catch (e) {
    alert(`删除失败：${e.message}`)
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="sidebar-stack">
    <!-- 限额卡片 -->
    <section class="card side-card">
      <h3>MinerU 免费额度</h3>
      <div class="quota-row">
        <span>优先配额</span>
        <b>{{ quota?.priority_used || 0 }}/{{ quota?.daily_priority_pages || 1000 }}</b>
      </div>
      <div class="bar quota-bar">
        <div class="fill" :class="{ warn: quota?.priority_exhausted }" :style="{ width: quotaPct + '%' }"></div>
      </div>
      <p v-if="quota?.priority_exhausted" class="quota-warn">⚠ 已进入普通队列（较慢）</p>
      <p v-if="quota && !quota.has_api_key" class="quota-warn">⚠ 未配置 API Key</p>
      <div class="quota-row file">
        <span>文件数</span>
        <b>{{ quota?.files_used || 0 }}/{{ quota?.daily_file_limit || 5000 }}</b>
      </div>
    </section>

    <!-- 解析任务卡片 -->
    <section class="card side-card">
      <h3>解析任务</h3>
      <!-- 启动/轮询/完成消息：所有分支可见（含失败后回到待办列表） -->
      <p v-if="parseTask?.parseMsg" class="msg" :class="parseTask.parseMsg.ok ? 'ok' : 'err'">
        {{ parseTask.parseMsg.text }}
      </p>
      <div v-if="parseTask?.parsing && busyBook" class="task-item active">
        <div class="task-title">{{ busyBook.title }}</div>
        <div class="bar">
          <div class="fill" :style="{ width: parseInfo.pct + '%' }"></div>
        </div>
        <div class="task-meta">⏳ {{ parseInfo.text }} · {{ parseInfo.pct }}%</div>
      </div>
      <div v-else-if="actionable.length" class="task-list">
        <div v-for="b in actionable" :key="b.id" class="task-item">
          <div class="task-title" :title="b.title">{{ b.title }}</div>
          <button class="btn ghost sm" @click="startParse(b)">
            {{ b.parse_status === 'failed' ? '重试解析' : '开始解析' }}
          </button>
        </div>
      </div>
      <div v-else class="task-empty">暂无解析任务</div>
    </section>

    <!-- 已入库教材卡片 -->
    <section class="card side-card">
      <h3>已入库教材 <span v-if="books.length" class="side-count">（{{ books.length }}）</span></h3>
      <div v-if="books.length" class="side-book-list">
        <div v-for="b in books" :key="b.id" class="side-book"
             :class="{ parsing: b.parse_status === 'parsing', selected: b.id === selectedId }">
          <div class="side-book-top">
            <span class="side-book-title" :title="b.title">{{ b.title }}</span>
            <span :class="['status-pill', STATUS_PILL[b.parse_status] || 'pill']">
              {{ STATUS_TEXT[b.parse_status] || b.parse_status }}
            </span>
          </div>
          <div class="side-book-meta">#{{ b.id }} · {{ b.page_count }} 页 · 进度 {{ b.parse_progress || '—' }}</div>

          <div class="side-book-ops">
            <template v-if="isReady(b)">
              <button class="link-btn" title="质检报告与章节对比" @click="emit('preview', b)">📊</button>
              <select v-model="b._ch" class="chapter-select" :disabled="importingId === b.id">
                <option :value="0">整本</option>
                <option v-for="c in chapterMaps[b.id] || []" :key="c.no" :value="c.no">
                  {{ c.no }}. {{ c.title }}
                </option>
              </select>
              <a class="link-btn" :href="chapterHref(b)" download title="下载 Markdown ZIP（整本或所选章节）">⬇ ZIP</a>
              <a class="link-btn muted" :href="`/api/books/${b.id}/export?format=raw&images=oss`" download title="原始 OCR 合并版 ZIP">原</a>
              <a class="link-btn purple" :href="`/api/books/${b.id}/export?format=obsidian&images=oss`" download title="Obsidian 版 ZIP">📓 版</a>
              <button v-if="settings?.obsidian_vault_configured" class="link-btn purple"
                      :disabled="importingId === b.id" @click="importObsidian(b)"
                      title="导入 Obsidian（图片转 OSS 外链）">
                {{ importingId === b.id ? '导入中…' : '📥 导入' }}
              </button>
              <span class="grow"></span>
              <button class="link-btn muted" :disabled="b.parse_status === 'parsing' || deletingId === b.id"
                      @click="deleteBook(b)" title="删除该教材全部解析产物">🗑</button>
            </template>
            <template v-else>
              <span v-if="b.parse_status === 'parsing'" class="pill blue"><span class="dot"></span>解析中…</span>
              <button v-if="b.parse_status === 'pending' || b.parse_status === 'failed'"
                      class="btn ghost sm" @click="startParse(b)">开始解析</button>
              <span class="grow"></span>
              <button class="link-btn muted" :disabled="deletingId === b.id"
                      @click="deleteBook(b)" title="删除该教材全部解析产物">🗑</button>
            </template>
          </div>
        </div>
      </div>
      <div v-else class="task-empty">暂无教材，先上传一份 PDF</div>
    </section>
  </div>
</template>

<style scoped>
.status-pill { flex-shrink: 0; }
</style>
