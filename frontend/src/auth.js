// auth.js — B5-A 网页登录 + 统一 token 注入（2026-08-18）
// 登录后 token 存 localStorage，所有 fetch 经 authFetch() 自动带 X-Auth-Token；
// 401 时清 token 并提示重新登录。

const TOKEN_KEY = 'bookswich_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

export function isLoggedIn() {
  return !!getToken()
}

// 登出：清 token，可选触发回调（如刷新回登录态）
export function logout() {
  setToken('')
}

// 统一 fetch 包装：自动带 X-Auth-Token；401 时清 token（页面响应 401 处理）
export async function authFetch(url, options = {}) {
  const token = getToken()
  const opts = { ...options }
  opts.headers = { ...(options.headers || {}) }
  if (token) opts.headers['X-Auth-Token'] = token

  let res
  try {
    res = await fetch(url, opts)
  } catch (e) {
    throw e
  }
  if (res.status === 401) {
    // 会话失效：清 token（由调用方/App 决定是否跳登录）
    logout()
  }
  return res
}

// 供 <a download href> 用的 URL：把 token 作为 ?token= 附加（download 链接带不了 header）
// 无 token 时原样返回（本地未配置鉴权时不受影响）
export function authedUrl(url) {
  const token = getToken()
  if (!token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(token)}`
}
