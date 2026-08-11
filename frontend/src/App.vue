<script setup>
import { onMounted, ref } from 'vue'
import UploadPanel from './components/UploadPanel.vue'

const books = ref([])
const quota = ref(null)
const settings = ref(null)
const backendDown = ref(false)

async function refreshBooks() {
  try {
    const r = await fetch('/api/books')
    const d = await r.json()
    books.value = d.books || []
    backendDown.value = false
  } catch { backendDown.value = true }
}

async function refreshQuota() {
  try {
    const r = await fetch('/api/quota')
    quota.value = await r.json()
    backendDown.value = false
  } catch { backendDown.value = true }
}

async function refreshSettings() {
  try {
    const r = await fetch('/api/settings')
    settings.value = await r.json()
    backendDown.value = false
  } catch { backendDown.value = true }
}

onMounted(() => { refreshBooks(); refreshQuota(); refreshSettings() })
</script>

<template>
  <div>
    <!-- 顶部导航 -->
    <header class="nav">
      <div class="nav-inner">
        <div class="brand">
          <span class="brand-mark">b</span>
          <span>bookswich</span>
        </div>
        <span class="brand-sub">教材 PDF → MinerU 解析 → Markdown</span>
        <div class="nav-stats">
          <span v-if="backendDown" class="pill red">
            <span class="dot"></span>后端未连接
          </span>
          <span v-if="quota" class="pill blue">
            <span class="dot"></span>
            优先配额 {{ quota.priority_used }}/{{ quota.daily_priority_pages }}
          </span>
          <span v-if="quota && quota.files_used" class="pill blue">
            <span class="dot"></span>文件 {{ quota.files_used }}/{{ quota.daily_file_limit }}
          </span>
          <span v-if="quota?.priority_exhausted" class="pill amber">
            <span class="dot"></span>⚠ 已进普通队列（较慢）
          </span>
          <span v-if="!quota?.has_api_key" class="pill amber">
            <span class="dot"></span>未配置 API Key
          </span>
          <span v-if="settings?.obsidian_vault_configured" class="pill purple">
            <span class="dot"></span>Obsidian 已连接
          </span>
        </div>
      </div>
    </header>

    <main class="page">
      <section class="hero">
        <h1>教材处理工作台</h1>
        <p>上传 PDF → 自动解析并修正格式 → 下载 Markdown / 导入 Obsidian</p>
      </section>

      <UploadPanel :books="books" :quota="quota" :settings="settings"
                   @changed="refreshBooks(); refreshQuota()" />
    </main>
  </div>
</template>
