/**
 * Markdown 渲染组合式函数
 *
 * 基于 marked + highlight.js + KaTeX 的 Markdown 渲染工具。
 * 支持代码高亮、数学公式 (行内 $$ 和块级 $$...$$)。
 */

import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import katex from 'katex'

const marked = new Marked(
  { breaks: true, gfm: true },
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code: string, lang: string) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      return hljs.highlightAuto(code).value
    },
  }),
)

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, { displayMode, throwOnError: false, trust: true })
  } catch {
    return displayMode ? `<pre class="math-block">${tex}</pre>` : `<code>${tex}</code>`
  }
}

/**
 * 将 Markdown 文本渲染为 HTML,支持 KaTeX 数学公式。
 *
 * - $$...$$ → 块级公式
 * - $...$   → 行内公式
 * - 含中文的公式内容不会被解析 (启发式过滤)
 */
export function renderMd(text: string): string {
  const blocks: string[] = []
  let processed = text.replace(/\$\$([\s\S]*?)\$\$/g, (_m, tex) => {
    if (/[一-鿿]/.test(tex)) return _m
    const placeholder = `%%MATH_BLOCK_${blocks.length}%%`
    blocks.push(renderMath(tex.trim(), true))
    return placeholder
  })
  processed = processed.replace(/\$([^$\n]+?)\$/g, (_m, tex) => {
    if (/[一-鿿]/.test(tex)) return _m
    const placeholder = `%%MATH_INLINE_${blocks.length}%%`
    blocks.push(renderMath(tex.trim(), false))
    return placeholder
  })
  let html = marked.parse(processed) as string
  blocks.forEach((block, i) => {
    html = html.replace(`%%MATH_BLOCK_${i}%%`, block)
    html = html.replace(`%%MATH_INLINE_${i}%%`, block)
  })
  return html
}
