<script setup>
// LoginPanel.vue — B5-A 登录页：密码 → POST /api/auth/login → 存 token
import { ref } from 'vue'
import { setToken } from '../auth'

const emit = defineEmits(['logged-in'])

const password = ref('')
const loading = ref(false)
const error = ref('')

// 首次挂载时若已有登录态，尝试用它探活（后端可达则视为已登录）
async function login() {
  if (!password.value) { error.value = '请输入密码'; return }
  loading.value = true
  error.value = ''
  try {
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password.value }),
    })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(d.detail || '登录失败')
    setToken(d.token)
    emit('logged-in')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <form class="login-card" @submit.prevent="login">
      <div class="login-logo">b</div>
      <h1 class="login-title">bookswich</h1>
      <p class="login-sub">教材 PDF → Markdown · 访问受保护</p>
      <input v-model="password" type="password" class="login-input" placeholder="访问密码"
             autocomplete="current-password" autofocus />
      <button class="btn login-btn" type="submit" :disabled="loading">
        {{ loading ? '登录中…' : '登 录' }}
      </button>
      <p v-if="error" class="login-error">{{ error }}</p>
    </form>
  </div>
</template>

<style scoped>
.login-wrap { display: flex; align-items: center; justify-content: center; min-height: 100vh;
  background: var(--bg, #141820); }
.login-card { width: 320px; padding: 40px 32px; border-radius: 14px; text-align: center;
  background: var(--card, #1b2130); border: 1px solid rgba(255, 216, 102, .12);
  box-shadow: 0 12px 40px rgba(0,0,0,.4); }
.login-logo { width: 56px; height: 56px; margin: 0 auto 14px; border-radius: 14px;
  background: linear-gradient(135deg, #ffd866, #ff9a3c); color: #141820;
  display: flex; align-items: center; justify-content: center; font-size: 30px; font-weight: 800; }
.login-title { margin: 0 0 4px; font-size: 22px; color: #f0f2f6; }
.login-sub { margin: 0 0 26px; font-size: 13px; color: #8a92a6; }
.login-input { width: 100%; padding: 11px 14px; margin-bottom: 16px; border-radius: 8px;
  border: 1px solid #333c4e; background: #11151f; color: #f0f2f6; font-size: 15px;
  box-sizing: border-box; }
.login-input:focus { outline: none; border-color: #ffd866; }
.login-btn { width: 100%; padding: 11px; font-size: 15px; }
.login-error { margin: 12px 0 0; color: #ff6b6b; font-size: 13px; }
</style>
