<script setup>
// SidebarPanel.vue — 左侧边栏（2026-08-11 L-3）：限额卡片 + 解析任务卡片
import { computed } from 'vue'

const props = defineProps({
  books: Array,
  quota: Object,
  settings: Object,
  parseTask: Object,
})

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
  </div>
</template>
