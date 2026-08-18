#!/usr/bin/env node
/**
 * C5 前端构建产物门禁（2026-08-18）
 *
 * 在 `vite build` 之后运行，检查 dist 产物：
 *   1. 关键组件文案确实进入 JS bundle（防构建未生效 / tree-shake 误删 / 空构建）
 *   2. 关键设计 token / 类名确实进入 CSS（防设计语言回退）
 *   3. 已删除的旧类名在产物中「零残留」（防前端回退到旧设计 / stale 产物）
 *
 * 用法：
 *   npm run build                     # vite build
 *   node scripts/verify_build.mjs     # 独立跑（需先 build）
 *   npm run verify:build              # 一键门禁（见 package.json）
 *
 * 退出码：0 = 全过；1 = 任一检查失败。输出 machine-readable JSON 到 stdout。
 * 核心逻辑在 `analyze()`，可被 vitest 直接 import 测试。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))
export const DIST = path.resolve(__dirname, '..', 'dist', 'assets')

/** 必须出现在业务 JS bundle 中的稳定文案（取自各组件核心 UI）。避免高频变动的临时文案。 */
export const REQUIRED_TEXT = [
  '上传 PDF',              // App.vue 顶栏按钮
  '教材 PDF → Markdown',    // App.vue brand 标语 + LoginPanel
  '下载 ZIP',               // BookDetail 导出工具栏
  '解析任务',               // SidebarPanel 卡标题
  '访问受保护',             // LoginPanel
  '章节对比',               // ComparePanel tab 标签
]

/** 必须出现的 CSS 设计 token / 签名样式（暗色工作台 v3 的锚点）。匹配时容忍压缩（去空白）。 */
export const REQUIRED_CSS = [
  '--accent: #e5b14f',   // 金色签名色
  '--bg: #0b0d11',       // 深炭画布
  'color-scheme: dark',  // 深色模式声明（压缩后为 color-scheme:dark）
  '.rail',               // MinerU 式可折叠边栏
  '.workspace',
]

/**
 * 已删除的旧类名（v3 重构移除的 v1/v2 浅色 SaaS 风格），产物中必须零出现。
 * 注意：`.hero` 用词边界匹配，避免误伤 v3 合法的 `.empty-hero`。
 */
export const FORBIDDEN_CSS = [
  '.hero',
  '.sidebar',   // 旧侧栏（v3 改名 .rail）
  '.side-card', // 旧侧栏卡
  '.side-book', // 旧侧栏教材项
]

/** 主体业务 bundle（含 Vue 运行时 + 组件）。排除 pdf / pdf.worker 大块。 */
export function businessBundles() {
  return fs.readdirSync(DIST)
    .filter(f => /^index-.*\.js$/.test(f))
}

export function cssBundles() {
  return fs.readdirSync(DIST)
    .filter(f => /^index-.*\.css$/.test(f))
}

/** 渲染 `通过 x / 共 y` 的可读计数 */
export function lossless(total, failed) {
  return { passed: total - failed, total }
}

/** 正则转义字面量中的特殊字符 */
function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 核心检查函数（纯函数，可测试）。返回完整报告对象。
 * @param {string} jsText  业务 JS bundle 拼接文本
 * @param {string} cssText 业务 CSS bundle 拼接文本
 */
export function analyze(jsText, cssText) {
  // CSS 容忍压缩：去所有空白后再做子串匹配（处理 color-scheme:dark 等被压缩的空格）
  const cssMin = cssText.replace(/\s+/g, '')
  const missingText = REQUIRED_TEXT.filter(t => !jsText.includes(t))
  const missingCss = REQUIRED_CSS.filter(s => !cssMin.includes(s.replace(/\s+/g, '')))
  // 已删除旧类名「零残留」检测：
  //   - CSS 形态：带点、双向词边界（前不能是 [-.\w]，避免 .empty-hero 内 .hero 被命中）
  //   - JS 形态：仅对足够独特的类名做裸词检测（避免 hero 这类泛词在全词里误报）
  const residualCss = FORBIDDEN_CSS.filter(s => {
    const name = s.slice(1) // 去点：hero / sidebar / side-card / side-book
    const cssRe = new RegExp(`(?<![-.\\w])\\.${escapeRe(name)}(?![\\w-])`)
    if (cssRe.test(cssText)) return true
    if (name.length >= 6) {
      const jsRe = new RegExp(`(?<![\\w-])${escapeRe(name)}(?![\\w-])`)
      if (jsRe.test(jsText)) return true
    }
    return false
  })

  const report = {
    ok: missingText.length === 0 && missingCss.length === 0 && residualCss.length === 0,
    missingText,   // 应进 JS 而未进的文案
    missingCss,    // 应进 CSS 而未进的设计 token
    forbiddenResidual: residualCss, // 已删除旧类名仍残留
    checks: {
      textInBundle: lossless(REQUIRED_TEXT.length, missingText.length),
      designTokenInCss: lossless(REQUIRED_CSS.length, missingCss.length),
      noForbiddenResidual: lossless(0, residualCss.length),
    },
  }
  return report
}

function main() {
  const jsFiles = businessBundles()
  const cssFiles = cssBundles()
  if (jsFiles.length === 0 || cssFiles.length === 0) {
    console.error('未找到 dist/assets 下的业务 bundle。请先执行 `npm run build`。')
    process.exit(1)
  }

  let jsText = ''
  for (const f of jsFiles) jsText += fs.readFileSync(path.join(DIST, f), 'utf8')
  let cssText = ''
  for (const f of cssFiles) cssText += fs.readFileSync(path.join(DIST, f), 'utf8')

  const report = analyze(jsText, cssText)
  const { jsBundles, cssBundles: cb } = (() => ({ jsBundles: jsFiles, cssBundles: cssFiles }))()
  report.jsBundles = jsBundles
  report.cssBundles = cb

  console.log(JSON.stringify(report, null, 2))
  if (!report.ok) {
    console.error('\n[verify_build] 构建产物门禁未通过，见上方报告。')
    process.exit(1)
  }
  console.log('[verify_build] 构建产物门禁通过 ✓')
}

// CLI 直跑守卫：仅当作为脚本直接运行时才执行 main()（import 时跳过，便于测试）
if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main()
}
