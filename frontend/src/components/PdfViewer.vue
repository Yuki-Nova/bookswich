<script setup>
// PdfViewer.vue — 网页内嵌 PDF 阅览器（pdf.js canvas 懒加载渲染，所见即所得，无下载弹窗）
// pdfjs-dist 按需动态 import（只在打开预览时加载，不拖累首屏）
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  pdfUrl: { type: String, required: true },
  startPage: { type: Number, default: 1 },
})

const root = ref(null)
const pages = ref(null)
const loading = ref(false)
const error = ref('')
const totalPages = ref(0)

let pdfDoc = null
let io = null
let pdfjsLib = null
const rendered = new Set()

async function ensurePdfjs() {
  if (pdfjsLib) return pdfjsLib
  pdfjsLib = await import('pdfjs-dist')
  const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
  pdfjsLib.GlobalWorkerOptions.workerSrc = worker.default
  return pdfjsLib
}

async function renderPage(pageNo, holder) {
  if (rendered.has(pageNo) || !pdfDoc) return
  rendered.add(pageNo)
  try {
    const page = await pdfDoc.getPage(pageNo)
    const viewport1 = page.getViewport({ scale: 1 })
    const holderWidth = holder.clientWidth || (root.value ? root.value.clientWidth - 24 : 720)
    const scale = holderWidth / viewport1.width
    const viewport = page.getViewport({ scale })

    const canvas = document.createElement('canvas')
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.floor(viewport.width * dpr)
    canvas.height = Math.floor(viewport.height * dpr)
    canvas.style.width = '100%'
    canvas.style.height = 'auto'
    canvas.style.display = 'block'

    const ctx = canvas.getContext('2d', { alpha: false })
    const transform = dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null
    await page.render({ canvasContext: ctx, viewport, transform }).promise
    holder.insertBefore(canvas, holder.firstChild)
    holder.classList.add('rendered')
  } catch {
    rendered.delete(pageNo)
  }
}

function buildPlaceholders(aspect) {
  const frag = document.createDocumentFragment()
  for (let i = 1; i <= totalPages.value; i++) {
    const holder = document.createElement('div')
    holder.className = 'pdf-page'
    holder.dataset.page = String(i)
    if (aspect) holder.style.aspectRatio = aspect
    const label = document.createElement('span')
    label.className = 'pdf-page-no'
    label.textContent = String(i)
    holder.appendChild(label)
    frag.appendChild(holder)
  }
  pages.value.appendChild(frag)
}

function setupObserver() {
  io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) renderPage(Number(e.target.dataset.page), e.target)
    }
  }, { root: root.value, rootMargin: '400px 0px' })
  pages.value.querySelectorAll('.pdf-page').forEach((el) => io.observe(el))
}

function scrollToStart() {
  const target = pages.value.querySelector(`.pdf-page[data-page="${props.startPage}"]`)
  if (target) target.scrollIntoView({ block: 'start' })
}

async function load() {
  loading.value = true
  error.value = ''
  totalPages.value = 0
  rendered.clear()
  if (io) { io.disconnect(); io = null }
  if (pages.value) pages.value.innerHTML = ''
  pdfDoc = null
  try {
    const lib = await ensurePdfjs()
    const resp = await fetch(props.pdfUrl)
    if (!resp.ok) throw new Error(`PDF 加载失败（HTTP ${resp.status}）`)
    const data = await resp.arrayBuffer()
    pdfDoc = await lib.getDocument({ data }).promise
    totalPages.value = pdfDoc.numPages

    // 取第一页比例作占位 aspect（教材页尺寸基本一致 → 未渲染时滚动高度也准确）
    let aspect = ''
    try {
      const p1 = await pdfDoc.getPage(1)
      const v = p1.getViewport({ scale: 1 })
      aspect = `${v.width} / ${v.height}`
    } catch { /* 忽略 */ }

    buildPlaceholders(aspect)
    setupObserver()
    requestAnimationFrame(() => scrollToStart())
  } catch (e) {
    error.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

watch(() => props.pdfUrl, load)
onMounted(load)
onBeforeUnmount(() => { if (io) io.disconnect(); io = null; pdfDoc = null })
</script>

<template>
  <div ref="root" class="pdf-viewer">
    <p v-if="loading" class="msg pdf-msg">⏳ 加载 PDF…</p>
    <p v-else-if="error" class="msg err pdf-msg">{{ error }}</p>
    <div ref="pages" class="pdf-pages"></div>
  </div>
</template>
