// useParseTask.js — 解析任务共享状态（2026-08-11 L-4：从 UploadPanel 上移）
// App 持有本 composable，SidebarPanel（实时进度）与 UploadPanel（触发按钮）共用同一进度源。
import { reactive, ref, watch } from 'vue'
import { authFetch } from '../auth'

export function useParseTask(booksRef, refreshBooks, refreshQuota) {
  const parsingId = ref(null)
  const parsing = ref(false)
  const progress = ref('')
  const parseMsg = ref(null)   // {text, ok} 解析相关的消息（启动/轮询失败/完成）
  let timer = null

  function schedulePoll() {
    if (timer) clearTimeout(timer)
    timer = setTimeout(poll, 4000)
  }

  async function poll() {
    if (!parsingId.value) return
    let d
    try {
      // 超时 + 失败保护：后端重启/网络抖动不中断轮询（挂起则 15s 后重试）
      const r = await authFetch(`/api/books/${parsingId.value}`, { signal: AbortSignal.timeout(15000) })
      d = await r.json()
    } catch (e) {
      parseMsg.value = { text: `⚠ 进度刷新失败，自动重试：${e.message}`, ok: false }
      schedulePoll()
      return
    }
    progress.value = d.parse_progress || ''
    if (d.parse_status === 'parsing') {
      schedulePoll()
    } else {
      parsing.value = false
      parsingId.value = null
      parseMsg.value = d.parse_status === 'parsed' || d.parse_status === 'structure_ok'
        ? { text: '✅ 解析完成，可下载 Markdown', ok: true }
        : { text: `解析结束：${d.parse_status}（进度 ${d.parse_progress}）`, ok: false }
      refreshBooks()
      refreshQuota()
    }
  }

  // 自动接管「解析中」的书（含刷新页面后恢复轮询）
  watch(booksRef, (list) => {
    const busy = (list || []).find(b => b.parse_status === 'parsing')
    if (busy && busy.id !== parsingId.value) {
      parsingId.value = busy.id
      parsing.value = true
      progress.value = busy.parse_progress || ''
      schedulePoll()
    }
  }, { deep: true, immediate: true })

  // 启动/续跑解析（返回是否成功；文件数满额前端拦截）
  async function startParse(b, quota) {
    if (quota && quota.files_remaining <= 0) {
      parseMsg.value = {
        text: `今日文件数已达上限（${quota.daily_file_limit} 份），请明天再试`,
        ok: false,
      }
      return false
    }
    parsingId.value = b.id
    parsing.value = true
    // 本地乐观更新：立即把该书标为 parsing，busyBook 才能马上匹配（否则要等 refreshBooks 网络往返）
    if (booksRef.value) {
      const target = booksRef.value.find(x => x.id === b.id)
      if (target) target.parse_status = 'parsing'
    }
    // 优先页数（1000 页/日）用完不拦：MinerU 自动进普通队列，只是慢
    parseMsg.value = quota?.priority_exhausted
      ? { text: '⚠ 已超优先额度（1000 页/日），解析进入普通队列，会较慢', ok: true }
      : null
    progress.value = b.parse_progress || ''
    try {
      const r = await authFetch(`/api/books/${b.id}/parse`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || '启动失败')
      schedulePoll()
      // 后端状态已更新为 parsing，立即刷新列表（busyBook 以服务端状态为准）
      refreshBooks()
      refreshQuota()
      return true
    } catch (e) {
      parsing.value = false
      parsingId.value = null
      parseMsg.value = { text: `解析启动失败：${e.message}`, ok: false }
      refreshBooks()
      return false
    }
  }

  // reactive 包装：组件里 props.parseTask.xxx 自动解包（含 ref 属性）
  return reactive({ parsingId, parsing, progress, parseMsg, startParse })
}
