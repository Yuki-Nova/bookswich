// auth.js 单元测试（C2 补充，2026-08-18）
// @vitest-environment jsdom
// 覆盖 B5-A 核心：token 存取 / authFetch 注入 X-Auth-Token / 401 清理 / authedUrl 附加 token
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// jsdom 提供 localStorage
import { getToken, setToken, isLoggedIn, logout, authFetch, authedUrl } from '../auth'

const TOKEN_KEY = 'bookswich_token'

beforeEach(() => {
  localStorage.clear()
})

describe('auth 模块', () => {
  it('setToken/getToken/isLoggedIn 基本存取', () => {
    expect(isLoggedIn()).toBe(false)
    setToken('tok123')
    expect(getToken()).toBe('tok123')
    expect(isLoggedIn()).toBe(true)
    expect(localStorage.getItem(TOKEN_KEY)).toBe('tok123')
  })

  it('logout 清 token', () => {
    setToken('tok')
    logout()
    expect(isLoggedIn()).toBe(false)
    expect(getToken()).toBe('')
  })

  it('authFetch 带 token 时注入 X-Auth-Token', async () => {
    setToken('tok456')
    const mockFetch = vi.fn(() => Promise.resolve({ status: 200 }))
    // 用 fetch mock：authFetch 内部调用全局 fetch
    vi.stubGlobal('fetch', mockFetch)
    await authFetch('/api/books')
    expect(mockFetch).toHaveBeenCalledWith('/api/books', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Auth-Token': 'tok456' }),
    }))
    vi.unstubAllGlobals()
  })

  it('authFetch 返回 401 时清 token', async () => {
    setToken('tok')
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ status: 401 })))
    const res = await authFetch('/api/books')
    expect(res.status).toBe(401)
    expect(getToken()).toBe('')  // 401 → logout
    vi.unstubAllGlobals()
  })

  it('无 token 时 authFetch 不带 X-Auth-Token', async () => {
    const mockFetch = vi.fn(() => Promise.resolve({ status: 200 }))
    vi.stubGlobal('fetch', mockFetch)
    await authFetch('/api/books')
    const arg = mockFetch.mock.calls[0][1]
    expect(arg.headers['X-Auth-Token']).toBeUndefined()
    vi.unstubAllGlobals()
  })

  it('authedUrl 有 token 时附加 ?token=', () => {
    setToken('url-tok')
    expect(authedUrl('/api/books/1/pdf')).toBe('/api/books/1/pdf?token=url-tok')
    expect(authedUrl('/api/books/1/export?format=raw')).toBe('/api/books/1/export?format=raw&token=url-tok')
  })

  it('authedUrl 无 token 时原样返回', () => {
    expect(authedUrl('/api/books/1/pdf')).toBe('/api/books/1/pdf')
  })
})