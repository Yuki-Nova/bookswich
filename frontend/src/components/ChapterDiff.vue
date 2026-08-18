<script setup>
// ChapterDiff.vue — 按章 raw vs rebuilt 行级 diff（2026-08-11 第二步）
// eq 连续块折叠为计数行；del 红 / add 绿 逐行
import { ref, watch } from 'vue'
import { authFetch } from '../auth'

const props = defineProps({
  bookId: Number,
  bookTitle: String,
  chapters: Array,
  initialChapter: Number,   // ComparePanel「对比」按钮选中的章
})

const chapterNo = ref(0)
const diff = ref(null)
const loading = ref(false)
const error = ref('')

// ⚠ 顺序关键:先注册 chapterNo 监听(fetch),再注册 initialChapter 初始化——
// immediate 回调同步设置 chapterNo 时必须已有监听器,否则 diff 永不加载
watch(chapterNo, async (no) => {
  if (!no) return
  loading.value = true
  error.value = ''
  diff.value = null
  try {
    const r = await authFetch(`/api/books/${props.bookId}/compare/chapter/${no}`)
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '加载失败')
    diff.value = d
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

watch(() => props.initialChapter, (no) => {
  if (no) { chapterNo.value = no; return }
  // 未点「对比」时默认第一章
  if (props.chapters?.length && chapterNo.value === 0) chapterNo.value = props.chapters[0].no
}, { immediate: true })
</script>

<template>
  <div>
    <div class="diff-toolbar">
      <select v-model="chapterNo" class="chapter-select diff-ch">
        <option v-for="ch in chapters || []" :key="ch.no" :value="ch.no">{{ ch.no }}. {{ ch.title }}</option>
      </select>
      <span v-if="diff" class="diff-meta">
        <span class="d-add">+{{ diff.rebuilt_lines }}</span>
        <span class="d-del">−{{ diff.raw_lines }}</span>
        行 · {{ diff.page_range }}
      </span>
      <span class="diff-legend">
        <span class="lg-add">■ 重建后</span>
        <span class="lg-del">■ 原始</span>
      </span>
    </div>

    <p v-if="loading" class="msg">⏳ 生成 diff…</p>
    <p v-else-if="error" class="msg err">{{ error }}</p>
    <p v-else-if="!chapterNo" class="msg">无章节可对比</p>

    <div v-else-if="diff" class="diff-view">
      <div v-for="(item, i) in diff.diff" :key="i" class="diff-line">
        <span v-if="item.t === 'eq'" class="diff-eq">… {{ item.n }} 行相同 …</span>
        <template v-else-if="item.t === 'del'">
          <span class="dmark del">−</span><span class="dtext del">{{ item.a }}</span>
        </template>
        <template v-else>
          <span class="dmark add">+</span><span class="dtext add">{{ item.b }}</span>
        </template>
      </div>
    </div>
  </div>
</template>
