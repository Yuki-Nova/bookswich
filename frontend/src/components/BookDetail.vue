<script setup>
// BookDetail.vue — workspace 中选中教材的详情：标题/状态/进度 + 导出工具栏 + 质检/对比/并排 tab（2026-08-14 重构）
import { ref, watch } from 'vue'
import ComparePanel from './ComparePanel.vue'
import { authFetch, authedUrl } from '../auth'

const props = defineProps({
  book: Object,
  settings: Object,
})
const emit = defineEmits(['deleted'])

const STATUS_TEXT = {
  pending: '待解析',
  parsing: '解析中',
  parsed: '解析完成',
  structure_ok: '结构完成',
  failed: '解析失败',
}
const STATUS_PILL = {
  pending: 'pill',
  parsing: 'pill gold',
  parsed: 'pill green',
  structure_ok: 'pill green',
  failed: 'pill red',
}

const chapters = ref([])       // [{no, title}]
const chapter = ref(0)         // 0 = 整本
const importing = ref(false)
const deleting = ref(false)
const actionMsg = ref(null)    // {text, ok}

watch(() => props.book?.id, async (id) => {
  chapters.value = []
  chapter.value = 0
  actionMsg.value = null
  if (!id) return
  try {
    const r = await authFetch(`/api/books/${id}/chapters`)
    const d = await r.json()
    chapters.value = d.chapters || []
  } catch { /* 未重建的书忽略 */ }
}, { immediate: true })

function isReady(b) {
  return b.parse_status === 'parsed' || b.parse_status === 'structure_ok'
}

function chapterHref(b) {
  return chapter.value
    ? `/api/books/${b.id}/export?format=rebuilt&chapter=${chapter.value}`
    : `/api/books/${b.id}/export?format=rebuilt`
}

async function importObsidian(b) {
  importing.value = true
  actionMsg.value = null
  try {
    const r = await authFetch(`/api/books/${b.id}/import-obsidian`, { method: 'POST' })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '导入失败')
    actionMsg.value = { text: `✅ 已导入 Obsidian：${d.files} 个文件（图片转 OSS 外链）`, ok: true }
  } catch (e) {
    actionMsg.value = { text: `导入失败：${e.message}`, ok: false }
  } finally {
    importing.value = false
  }
}

async function deleteBook(b) {
  if (b.parse_status === 'parsing') return
  if (!confirm(`删除《${b.title}》？\n将移除服务器上该教材的全部解析产物（PDF、批次 md、结构重建产物），不可恢复。`)) return
  deleting.value = true
  actionMsg.value = null
  try {
    const r = await authFetch(`/api/books/${b.id}`, { method: 'DELETE' })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '删除失败')
    emit('deleted')
  } catch (e) {
    actionMsg.value = { text: `删除失败：${e.message}`, ok: false }
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <section class="card">
    <!-- 详情头 -->
    <div class="detail-head">
      <div class="detail-head-main">
        <h1 class="detail-title" :title="book.title">{{ book.title }}</h1>
        <div class="detail-sub">
          <span :class="['status-dot', book.parse_status]"></span>
          <span :class="['pill', STATUS_PILL[book.parse_status] || 'pill']">{{ STATUS_TEXT[book.parse_status] || book.parse_status }}</span>
          <span>#{{ book.id }}</span>
          <span>{{ book.page_count }} 页</span>
          <span v-if="book.parse_status === 'parsing'">进度 {{ book.parse_progress || '—' }}</span>
        </div>
      </div>

      <!-- 导出工具栏（解析完成后） -->
      <div v-if="isReady(book)" class="detail-actions">
        <select v-model="chapter" class="chapter-select" :disabled="importing || deleting">
          <option :value="0">整本</option>
          <option v-for="c in chapters" :key="c.no" :value="c.no">{{ c.no }}. {{ c.title }}</option>
        </select>
        <a class="btn" :href="authedUrl(chapterHref(book))" download>⬇ 下载 ZIP</a>
        <a class="btn ghost" :href="authedUrl(`/api/books/${book.id}/export?format=raw`)" download title="原始 OCR 合并版">原</a>
        <a class="btn ghost" :href="authedUrl(`/api/books/${book.id}/export?format=obsidian`)" download title="Obsidian 版（自包含本地图）">📓 Obsidian</a>
        <button v-if="settings?.obsidian_vault_configured" class="btn purple" :disabled="importing"
                @click="importObsidian(book)">
          {{ importing ? '导入中…' : '📥 导入' }}
        </button>
        <button class="link-btn danger" :disabled="deleting || book.parse_status === 'parsing'"
                @click="deleteBook(book)">🗑 删除</button>
      </div>

      <!-- 未完成时：解析进度 / 提示 -->
      <div v-else class="detail-actions">
        <span class="pill amber">解析完成后可用下载/导入</span>
      </div>
    </div>

    <!-- 解析中的进度条 -->
    <div v-if="book.parse_status === 'parsing'" class="detail-progress">
      <div class="bar" style="flex:1">
        <div class="fill" :style="{ width: (book.parse_progress || '').includes('/') ? '' : '100%' }"></div>
      </div>
      <span class="prog-text">{{ book.parse_progress || '…' }}</span>
    </div>

    <p v-if="actionMsg" class="msg" :class="actionMsg.ok ? 'ok' : 'err'">{{ actionMsg.text }}</p>

    <!-- 质检 / 对比 / 并排 -->
    <ComparePanel v-if="isReady(book)" :book-id="book.id" :book-title="book.title" />
  </section>
</template>
