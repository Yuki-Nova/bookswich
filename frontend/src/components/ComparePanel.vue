<script setup>
// ComparePanel.vue — 解析质检报告（2026-08-11 第一步：对比预览占位转真功能）
// 摘要卡 + 警告区 + 章节明细表；「章节对比」tab 交给 ChapterDiff
import { ref, watch } from 'vue'
import ChapterDiff from './ChapterDiff.vue'
import SideBySideView from './SideBySideView.vue'

const props = defineProps({
  bookId: Number,
  bookTitle: String,
})

const tab = ref('report')      // report | diff | sidebyside
const report = ref(null)
const loading = ref(false)
const error = ref('')
const diffTarget = ref(0)      // 「对比」按钮选中的章 → 传给 ChapterDiff / SideBySideView

// 章节表「对比」→ 切到对比 tab 并选中该章
function openDiff(no) {
  diffTarget.value = no
  tab.value = 'diff'
}

watch(() => props.bookId, async (id) => {
  if (!id) return
  loading.value = true
  error.value = ''
  report.value = null
  try {
    const r = await fetch(`/api/books/${id}/compare`)
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '加载失败')
    report.value = d
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}, { immediate: true })

const GATE_TEXT = {
  unbalanced: '未闭合标签',
  merged: '合并单元格',
  impure: '游离文本',
  ragged: '行列不齐',
  cols: '列数超限',
  rows: '行数超限',
  cell_too_long: '单格超长',
  empty: '无行',
}
</script>

<template>
  <section class="card compare-card">
    <div class="compare-head">
      <h2>📊 解析质检 <span v-if="bookTitle" class="cmp-sub">《{{ bookTitle }}》</span></h2>
      <div class="cmp-tabs">
        <button class="cmp-tab" :class="{ on: tab === 'report' }" @click="tab = 'report'">质检报告</button>
        <button class="cmp-tab" :class="{ on: tab === 'diff' }" @click="tab = 'diff'">章节对比</button>
        <button class="cmp-tab" :class="{ on: tab === 'sidebyside' }" @click="tab = 'sidebyside'">并排预览</button>
      </div>
    </div>

    <p v-if="loading" class="msg">⏳ 正在生成质检报告…</p>
    <p v-else-if="error" class="msg err">{{ error }}</p>

    <template v-else-if="report">
      <!-- 报告 tab -->
      <div v-if="tab === 'report'">
        <div class="cmp-summary">
          <div class="cmp-stat"><b>{{ report.chapter_count }}</b><span>章节</span></div>
          <div class="cmp-stat"><b>{{ report.pages_covered }}</b><span>覆盖页</span></div>
          <div class="cmp-stat"><b>{{ report.tables.converted }}/{{ report.tables.converted + report.tables.kept }}</b><span>表转MD</span></div>
          <div class="cmp-stat"><b>{{ report.images.referenced }}</b><span>图片引用</span></div>
          <div class="cmp-stat warn" :class="{ bad: report.images.missing.length }"><b>{{ report.images.missing.length }}</b><span>缺图</span></div>
          <div class="cmp-stat warn" :class="{ bad: report.warnings.length }"><b>{{ report.warnings.length }}</b><span>警告</span></div>
        </div>

        <div class="cmp-meta">
          正文 {{ (report.rebuilt_chars / 1000).toFixed(1) }}K 字 · 原始 OCR {{ (report.raw_chars / 1000).toFixed(1) }}K 字
          · 前置丢弃 {{ (report.pre_matter_chars / 1000).toFixed(1) }}K 字
        </div>

        <!-- 警告区 -->
        <div v-if="report.warnings.length || report.images.missing.length" class="cmp-alerts">
          <div v-for="w in report.warnings" :key="w" class="cmp-alert">⚠ {{ w }}</div>
          <div v-if="report.images.missing.length" class="cmp-alert">
            🖼 缺图 {{ report.images.missing.length }} 张：{{ report.images.missing.join('、') }}
          </div>
        </div>

        <!-- 表格门禁原因分布 -->
        <div v-if="report.tables.kept" class="cmp-gates">
          <span class="cmp-gate-title">保留 HTML 的表格原因：</span>
          <span v-for="(n, k) in report.tables.reasons" :key="k" class="cmp-gate-pill" :title="k">
            {{ GATE_TEXT[k] || k }} ×{{ n }}
          </span>
        </div>

        <!-- 章节明细 -->
        <table class="cmp-table">
          <thead>
            <tr><th>#</th><th>章节</th><th>页</th><th>字符</th><th>图</th><th>表 转/保</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="ch in report.chapters" :key="ch.no">
              <td>{{ ch.no }}</td>
              <td class="cmp-ch-title" :title="ch.title">{{ ch.title }}</td>
              <td>{{ ch.page_range }}</td>
              <td>{{ ch.char_count }}</td>
              <td>{{ ch.image_count }}</td>
              <td>{{ ch.tables.converted }}/{{ ch.tables.kept }}</td>
              <td>
                <button class="link-btn" @click="openDiff(ch.no)">对比</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!report.chapters.length" class="msg">无章节（无编号教材兜底为「全文」）</p>
      </div>

      <ChapterDiff v-else-if="tab === 'diff'" :book-id="bookId" :book-title="bookTitle"
                   :chapters="report.chapters" :initial-chapter="diffTarget" />

      <SideBySideView v-else-if="tab === 'sidebyside'" :book-id="bookId" :book-title="bookTitle"
                      :chapters="report.chapters" :initial-chapter="diffTarget" />
    </template>
  </section>
</template>
