<script setup>
// SideBySideView.vue — 并排预览：左网页内嵌 PDF 阅览器（pdf.js）+ 右 rebuilt Markdown 渲染
// 章节切换联动：PDF 按章 page_range 起始页定位；右栏拉取 as=markdown 原文
import { ref, watch, computed } from 'vue'
import { marked } from 'marked'
import markedKatex from 'marked-katex-extension'
import DOMPurify from 'dompurify'
import PdfViewer from './PdfViewer.vue'
import 'katex/dist/katex.min.css'
import { authFetch, authedUrl } from '../auth'

// KaTeX 公式渲染：$...$ 行内 / $$...$$ 块级（坏公式不崩页面，原样展示）
// nonStandard: 中文教材公式常紧贴中文/换行（`即$t$分布`、列表项内 $(G→F→t)$），
// 标准模式要求 $ 前有空格或行首 → 开启非标准宽松匹配
marked.use(markedKatex({
  throwOnError: false,
  output: 'html',
  nonStandard: true,
}))

// 同行块级公式规范化：MinerU/导出常有 `$$公式$$` 与正文同行（甚至跨多行）的写法，
// marked-katex-extension 的 block 规则要求 $$ 独立成行 → 预先把这类 $$...$$ 拆成独立行
function normalizeInlineDisplay(md) {
  return md.replace(/\$\$(?!\$)([\s\S]+?)\$\$/g, (m, body) => `\n$$\n${body.trim()}\n$$\n`)
}

const props = defineProps({
  bookId: Number,
  bookTitle: String,
  chapters: Array,
  initialChapter: Number,
})

const chapterNo = ref(0)
const md = ref('')
const loading = ref(false)
const error = ref('')
const copied = ref(false)

// 复制当前章节 Markdown（MinerU 式「复制」按钮）
async function copyMarkdown() {
  if (!md.value) return
  try {
    await navigator.clipboard.writeText(md.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch { /* 剪贴板被拒（非 https / 权限）忽略 */ }
}

// 章节下拉切换 → 右栏加载 markdown
watch(chapterNo, async (no) => {
  if (!no) return
  loading.value = true
  error.value = ''
  md.value = ''
  try {
    const r = await authFetch(`/api/books/${props.bookId}/compare/chapter/${no}?as=markdown`)
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '加载失败')
    md.value = d.markdown || ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

watch(() => props.initialChapter, (no) => {
  if (no) { chapterNo.value = no; return }
  if (props.chapters?.length && chapterNo.value === 0) chapterNo.value = props.chapters[0].no
}, { immediate: true })

// 当前章的 PDF 起始页（page_range "p12-28" → 12；解析失败回退 1）
const pdfPage = computed(() => {
  const ch = (props.chapters || []).find(c => c.no === chapterNo.value)
  const m = /p(\d+)/.exec(ch?.page_range || '')
  return m ? parseInt(m[1], 10) : 1
})

const pdfUrl = computed(() =>
  props.bookId ? authedUrl(`/api/books/${props.bookId}/pdf`) : ''
)

// markdown 渲染：相对图片路径 → 后端 media 端点（附 token query）；URL 原样
const renderedHtml = computed(() => {
  if (!md.value) return ''
  marked.use({
    renderer: {
      image({ href, title, text }) {
        let src = href || ''
        if (src && !/^(https?:|data:)/i.test(src)) {
          src = authedUrl(`/api/books/${props.bookId}/media/${src.replace(/^(\.\/|\/)/, '')}`)
        }
        const t = title ? ` title="${title}"` : ''
        return `<img src="${src}" alt="${text || ''}"${t} loading="lazy">`
      },
    },
  })
  const raw = marked.parse(normalizeInlineDisplay(md.value), { async: false })
  return DOMPurify.sanitize(raw)
})
</script>

<template>
  <div>
    <div class="diff-toolbar">
      <select v-model="chapterNo" class="chapter-select diff-ch">
        <option v-for="ch in chapters || []" :key="ch.no" :value="ch.no">{{ ch.no }}. {{ ch.title }}</option>
      </select>
      <span v-if="chapterNo" class="diff-meta">
        <template v-if="pdfPage > 1">PDF 第 {{ pdfPage }} 页起</template>
        <template v-else>PDF 起始页未知</template>
        <span class="d-add"> · 左 PDF / 右 Markdown</span>
      </span>
      <button class="link-btn sbs-copy" :disabled="!md" @click="copyMarkdown">
        {{ copied ? '✓ 已复制' : '⧉ 复制 Markdown' }}
      </button>
    </div>

    <p v-if="loading" class="msg">⏳ 加载章节…</p>
    <p v-else-if="error" class="msg err">{{ error }}</p>
    <p v-else-if="!chapterNo" class="msg">无章节可预览</p>

    <div v-else class="sbs-view">
      <!-- 左栏：网页内嵌 PDF 阅览器 -->
      <div class="sbs-pane sbs-pdf">
        <div class="sbs-pane-label">原始 PDF</div>
        <PdfViewer :pdf-url="pdfUrl" :start-page="pdfPage" />
      </div>
      <!-- 右栏：重建后 Markdown 渲染 -->
      <div class="sbs-pane sbs-md">
        <div class="sbs-pane-label">重建 Markdown</div>
        <div v-if="!md" class="msg sbs-msg">该章节无内容</div>
        <article v-else class="md-body" v-html="renderedHtml"></article>
      </div>
    </div>
  </div>
</template>
