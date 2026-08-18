// useParseTask 单元测试（C2，2026-08-18）
// 覆盖核心行为：文件配额拦截 / startParse / 解析中接管 / 解析完成清理
// useParseTask 返回 reactive({...}) —— ref 属性自动解包，访问 t.parsing（非 .value）
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'

vi.mock('../auth', () => ({
  authFetch: vi.fn(),
  getToken: vi.fn(() => 'tok'),
  setToken: vi.fn(),
  isLoggedIn: vi.fn(() => true),
}))

import { useParseTask } from './useParseTask'
import * as auth from '../auth'

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
})
afterEach(() => {
  vi.useRealTimers()
})

function makeArgs() {
  const books = ref([])
  return { books, refreshBooks: vi.fn(), refreshQuota: vi.fn() }
}

describe('useParseTask', () => {
  it('文件数配额满 → 前端拦截，不发起请求', async () => {
    const { books, refreshBooks, refreshQuota } = makeArgs()
    const t = useParseTask(books, refreshBooks, refreshQuota)
    const ok = await t.startParse({ id: 1, title: 'b1' }, { files_remaining: 0, priority_exhausted: false })
    expect(ok).toBe(false)
    expect(auth.authFetch).not.toHaveBeenCalled()
    expect(t.parseMsg.text).toContain('文件数已达上限')
  })

  it('配额充足 → startParse 发起 POST /parse 并返回 true', async () => {
    const { books, refreshBooks, refreshQuota } = makeArgs()
    const t = useParseTask(books, refreshBooks, refreshQuota)
    auth.authFetch.mockResolvedValue({ ok: true, json: async () => ({ status: 'started' }) })
    const ok = await t.startParse({ id: 3, title: 'b3' }, { files_remaining: 10, priority_exhausted: false })
    expect(ok).toBe(true)
    expect(auth.authFetch).toHaveBeenCalledWith('/api/books/3/parse', { method: 'POST' })
    expect(refreshBooks).toHaveBeenCalled()
    expect(refreshQuota).toHaveBeenCalled()
  })

  it('解析中的书自动接管（booksRef 出现 parsing 书 → 设 parsing 态）', async () => {
    const { books, refreshBooks, refreshQuota } = makeArgs()
    const t = useParseTask(books, refreshBooks, refreshQuota)
    auth.authFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ id: 5, parse_status: 'parsing', parse_progress: '2/10' }),
    })
    books.value = [{ id: 5, parse_status: 'parsing', parse_progress: '1/10' }]
    await nextTick()
    expect(t.parsing).toBe(true)
    expect(t.progress).toBe('1/10')
    // 推进假定时器触发首次轮询
    await vi.advanceTimersByTimeAsync(4000)
    expect(auth.authFetch).toHaveBeenCalledWith('/api/books/5', expect.any(Object))
  })

  it('解析完成 → 清理状态并刷新列表', async () => {
    const { books, refreshBooks, refreshQuota } = makeArgs()
    const t = useParseTask(books, refreshBooks, refreshQuota)
    auth.authFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ id: 7, parse_status: 'structure_ok', parse_progress: '5/5' }),
    })
    books.value = [{ id: 7, parse_status: 'parsing', parse_progress: '3/5' }]
    await nextTick()
    expect(t.parsing).toBe(true)
    await vi.advanceTimersByTimeAsync(4000)
    await nextTick()
    expect(t.parsing).toBe(false)
    expect(t.parseMsg.text).toContain('解析完成')
    expect(refreshBooks).toHaveBeenCalled()
    expect(refreshQuota).toHaveBeenCalled()
  })
})