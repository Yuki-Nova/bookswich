/**
 * C5 构建产物门禁核心逻辑测试（verify_build.mjs 的 analyze()）。
 *
 * 用合成文本直接测纯函数 analyze(jsText, cssText)，验证三类门禁：
 *   1. 关键文案缺失 → 失败
 *   2. 关键设计 token 缺失 → 失败（且容忍压缩空白）
 *   3. 已删除旧类名残留 → 失败（词边界匹配，不误伤 .empty-hero）
 */
import { describe, it, expect } from 'vitest'
import { analyze, REQUIRED_TEXT, REQUIRED_CSS } from '../verify_build.mjs'

/** 构造一份「合法」的合成产物文本：包含全部必需文案 + 设计 token + 无禁用类名 */
function validText() {
  let js = REQUIRED_TEXT.join(' ')
  let css = REQUIRED_CSS.map(s => s.replace(/\s+/g, '')).join(' ') // 模拟压缩后的 CSS
  return { js, css }
}

describe('verify_build · analyze', () => {
  it('合法产物（全文案 + 全 design token + 无残留）→ ok', () => {
    const { js, css } = validText()
    const r = analyze(js, css)
    expect(r.ok).toBe(true)
    expect(r.missingText).toEqual([])
    expect(r.missingCss).toEqual([])
    expect(r.forbiddenResidual).toEqual([])
  })

  it('关键文案缺失 → 失败并列出缺失项', () => {
    const { css } = validText()
    const r = analyze('缺少文案的 bundle', css)
    expect(r.ok).toBe(false)
    expect(r.missingText.length).toBeGreaterThan(0)
    expect(r.missingText).toContain(REQUIRED_TEXT[0]) // '上传 PDF'
  })

  it('design token 缺失 → 失败并列出缺失项', () => {
    const { js } = validText()
    const r = analyze(js, '.rail .workspace')
    expect(r.ok).toBe(false)
    expect(r.missingCss).toContain('--accent: #e5b14f')
  })

  it('CSS 压缩（去空格）也能命中 design token → 不误报', () => {
    // Real 产物是压缩后的 index-*.css，color-scheme: dark 变成 color-scheme:dark
    const js = REQUIRED_TEXT.join(' ')
    const css = 'html{color-scheme:dark}body{--accent:#e5b14f;--bg:#0b0d11}.rail{}.workspace{}'
    const r = analyze(js, css)
    expect(r.ok).toBe(true)
    expect(r.missingCss).toEqual([])
  })

  it('已删除旧类名 .sidebar 残留 → 失败', () => {
    const { js } = validText()
    const r = analyze(js, '... .sidebar { width: 280px } ...')
    expect(r.ok).toBe(false)
    expect(r.forbiddenResidual).toContain('.sidebar')
  })

  it('词边界：合法 .empty-hero 不误报为 .hero 残留', () => {
    const { js } = validText()
    // 完整必需 design token + 合法的新类名 .empty-hero（含 .empty- 前缀的 hero）
    const css = REQUIRED_CSS.map(s => s.replace(/\s+/g, '')).join(' ') + ' .empty-hero { text-align:center }'
    const r = analyze(js, css)
    expect(r.ok).toBe(true)
    expect(r.forbiddenResidual).toEqual([])
  })

  it('禁用类名在 JS bundle 中出现同样视为残留', () => {
    const { css } = validText()
    const r = analyze('... class="side-book" ...', css)
    expect(r.ok).toBe(false)
    expect(r.forbiddenResidual).toContain('.side-book')
  })
})
