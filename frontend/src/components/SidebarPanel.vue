<script setup>
// SidebarPanel.vue — 左 rail：限额卡 + 解析任务卡 + 教材库列表（2026-08-14 重构：选书为主，操作移入 workspace）
import { computed } from 'vue'

const props = defineProps({
  books: Array,
  quota: Object,
  settings: Object,
  parseTask: Object,
  selectedId: Number,   // workspace 当前打开的教材（高亮）
  collapsed: Boolean,   // 折叠态：只渲染图标条
})
const emit = defineEmits(['select', 'changed', 'expand'])

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
</script>

<template>
  <!-- 折叠态：图标条 -->
  <div v-if="collapsed" class="rail-stack rail-collapsed">
    <button class="rail-icon" title="教材库（展开）" @click="emit('expand')">
      📚
      <span v-if="books.length" class="rail-badge">{{ books.length }}</span>
    </button>
    <button class="rail-icon" :title="busyBook ? `解析中：${busyBook.title}` : '解析任务（展开）'" @click="emit('expand')">
      ⏳
      <span v-if="busyBook" class="rail-dot"></span>
    </button>
    <button class="rail-icon" title="MinerU 额度（展开）" @click="emit('expand')">
      ⚡
    </button>
  </div>

  <!-- 展开态：三卡 -->
  <div v-else class="rail-stack">
    <!-- 教材库 -->
    <section class="card rail-card">
      <h3>教材库 <span v-if="books.length" class="side-count">（{{ books.length }}）</span></h3>
      <div v-if="books.length" class="book-list">
        <div v-for="b in books" :key="b.id" class="book-row"
             :class="{ selected: b.id === selectedId }" @click="emit('select', b)">
          <span :class="['status-dot', b.parse_status]"></span>
          <div class="book-row-main">
            <div class="book-row-title" :title="b.title">{{ b.title }}</div>
            <div class="book-row-meta">#{{ b.id }} · {{ b.page_count }} 页 · {{ b.parse_progress || '—' }}</div>
          </div>
          <div class="book-row-ops">
            <button v-if="b.parse_status === 'pending' || b.parse_status === 'failed'"
                    class="btn ghost sm" @click.stop="startParse(b)">
              {{ b.parse_status === 'failed' ? '重试' : '解析' }}
            </button>
            <span v-else-if="b.parse_status === 'parsing'" class="pill gold sm-pill">解析中</span>
          </div>
        </div>
      </div>
      <div v-else class="task-empty">暂无教材，上传一份 PDF 开始</div>
    </section>

    <!-- 解析任务 -->
    <section class="card rail-card">
      <h3>解析任务</h3>
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

    <!-- 限额 -->
    <section class="card rail-card">
      <h3>MinerU 额度</h3>
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
  </div>
</template>

<style scoped>
.side-count { color: var(--text-3); font-weight: 400; font-size: 11px; }
.sm-pill { padding: 2px 8px; font-size: 11px; }
</style>
