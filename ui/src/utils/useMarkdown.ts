import { Marked } from 'marked'
import { createHighlighter, type Highlighter } from 'shiki'
import katex from 'katex'

let highlighter: Highlighter | null = null
createHighlighter({
  langs: [
    'ts', 'python', 'bash', 'json', 'yaml', 'html', 'css',
    'vue', 'sql', 'markdown', 'xml', 'toml', 'ini', 'js',
    'jsx', 'tsx', 'go', 'rust', 'shell', 'diff', 'text',
  ],
  themes: ['github-dark', 'github-light'],
}).then(h => { highlighter = h })

function shikiHighlight(code: string, lang: string): string {
  if (!highlighter) {
    return `<pre class="shiki"><code>${code.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</code></pre>`
  }
  try {
    return highlighter.codeToHtml(code, {
      lang: highlighter.getLoadedLanguages().includes(lang as any) ? lang as any : 'text',
      themes: { dark: 'github-dark', light: 'github-light' },
    })
  } catch {
    return `<pre class="shiki"><code>${code.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</code></pre>`
  }
}

const marked = new Marked({
  breaks: true,
  gfm: true,
  renderer: {
    code({ text, lang }) {
      return shikiHighlight(text, lang || 'text')
    },
  },
})

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, { displayMode, throwOnError: false, trust: true })
  } catch {
    return displayMode ? `<pre class="math-block">${tex}</pre>` : `<code>${tex}</code>`
  }
}

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
