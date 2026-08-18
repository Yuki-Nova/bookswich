<script setup>
import { computed, onMounted, ref } from 'vue'
import SidebarPanel from './components/SidebarPanel.vue'
import UploadPanel from './components/UploadPanel.vue'
import BookDetail from './components/BookDetail.vue'
import LoginPanel from './components/LoginPanel.vue'
import { useParseTask } from './composables/useParseTask'
import { authFetch, logout, isLoggedIn } from './auth'

const loggedIn = ref(isLoggedIn())
const books = ref([])
const quota = ref(null)
const settings = ref(null)
const backendDown = ref(false)
const selectedBook = ref(null)   // 当前在 workspace 打开的教材
const railCollapsed = ref(false)  // 教材库 rail 是否折叠（MinerU 式可折叠边栏）

function onLoggedIn() {
  loggedIn.value = true
  refreshBooks(); refreshQuota(); refreshSettings()
}

function onLogout() {
  logout()
  loggedIn.value = false
  books.value = []
  quota.value = null
  selectedBook.value = null
}

async function refreshBooks() {
  try {
    const r = await authFetch('/api/books')
    const d = await r.json()
    books.value = d.books || []
    backendDown.value = false
  } catch { backendDown.value = true }
}

async function refreshQuota() {
  try {
    const r = await authFetch('/api/quota')
    quota.value = await r.json()
    backendDown.value = false
  } catch { backendDown.value = true }
}

async function refreshSettings() {
  try {
    const r = await authFetch('/api/settings')
    settings.value = await r.json()
    backendDown.value = false
  } catch { backendDown.value = true }
}

// 解析任务共享状态（rail 实时进度 + 上传触发共用）
const parseTask = useParseTask(books, refreshBooks, refreshQuota)

// 顶栏「上传」→ 回到上传空态
function openUpload() {
  selectedBook.value = null
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// 解析中的书（顶栏进度徽标用）
const busyBook = computed(() => (books.value || []).find(b => b.parse_status === 'parsing'))

onMounted(() => {
  if (loggedIn.value) { refreshBooks(); refreshQuota(); refreshSettings() }
})
</script>

<template>
  <LoginPanel v-if="!loggedIn" @logged-in="onLoggedIn" />
  <div v-else>
    <!-- 顶部导航 -->
    <header class="nav">
      <div class="nav-inner">
        <button class="nav-toggle" :title="railCollapsed ? '展开教材库' : '折叠教材库'"
                @click="railCollapsed = !railCollapsed">
          <svg v-if="railCollapsed" width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M7 4l5 5-5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <svg v-else width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M2 4.5h14M2 9h14M2 13.5h14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
          </svg>
        </button>

        <div class="brand">
          <span class="brand-mark">b</span>
          <span>bookswich</span>
          <span class="brand-sub">教材 PDF → Markdown</span>
        </div>

        <div class="nav-stats">
          <span v-if="backendDown" class="pill red"><span class="dot"></span>后端未连接</span>
          <span v-if="parseTask?.parsing && busyBook" class="pill gold">
            <span class="dot"></span>解析中 {{ parseTask.progress }}
          </span>
          <span v-if="quota" class="pill blue">
            <span class="dot"></span>优先 {{ quota.priority_used }}/{{ quota.daily_priority_pages }}
          </span>
          <span v-if="quota && quota.files_used" class="pill blue">
            <span class="dot"></span>文件 {{ quota.files_used }}/{{ quota.daily_file_limit }}
          </span>
          <span v-if="quota?.priority_exhausted" class="pill amber">
            <span class="dot"></span>已进普通队列
          </span>
          <span v-if="!quota?.has_api_key" class="pill amber">
            <span class="dot"></span>未配置 API Key
          </span>
          <span v-if="settings?.obsidian_vault_configured" class="pill purple">
            <span class="dot"></span>Obsidian 已连接
          </span>
          <button class="btn sm" @click="openUpload">＋ 上传 PDF</button>
          <button class="btn ghost sm" @click="onLogout" title="退出登录">退出</button>
        </div>
      </div>
    </header>

    <!-- 左 rail（教材库 + 任务 + 配额） / 右 workspace（上传空态或教材详情） -->
    <div class="layout">
      <aside class="rail" :class="{ collapsed: railCollapsed }">
        <SidebarPanel :books="books" :quota="quota" :settings="settings" :parse-task="parseTask"
                      :selected-id="selectedBook?.id" :collapsed="railCollapsed"
                      @select="selectedBook = $event"
                      @expand="railCollapsed = false"
                      @changed="refreshBooks(); refreshQuota()" />
      </aside>

      <main class="workspace">
        <UploadPanel v-if="!selectedBook" :quota="quota" @changed="refreshBooks(); refreshQuota()" />
        <BookDetail v-else :book="selectedBook" :settings="settings"
                    @deleted="selectedBook = null; refreshBooks(); refreshQuota()" />
      </main>
    </div>
  </div>
</template>
