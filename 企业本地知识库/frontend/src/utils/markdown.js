import { marked } from 'marked'
import katex from 'katex'
import 'katex/dist/katex.min.css'

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true
})

/**
 * 工业级 Markdown 与 LaTeX 数学公式渲染器
 * 解决大模型输出中：
 * 1. 单字符/项目符号（如 "•\n"、"·\n"）孤立成行
 * 2. 块级公式 "\["、"\]" 或 "["、"]" 单独折行成只有1~2个字符的碎行
 * 3. LaTeX 公式未解析为富文本数学排版导致包含原始 \text{} 等代码碎片
 */
export function renderMarkdown(rawText) {
  if (!rawText || typeof rawText !== 'string') return ''

  let text = rawText

  // 1. 规范化孤独的项目符号（如 "•\n"、"·\n" 单独占一行），将其与后文紧凑合并为标准列表项
  text = text.replace(/(^|\n)\s*([•·◦▪])\s*\n+/g, '$1$2 ')
  // 将行首的特殊圆点符号替换为 Markdown 标准无序列表项 "- "
  text = text.replace(/(^|\n)\s*[•·◦▪]\s+/g, '$1- ')

  // 2. 兜底容错：若大模型输出了孤立成行的 "[" 与 "]" 包裹数学表达式
  // 例如：
  // [
  // ax^2 + bx + c > 0
  // ]
  // 识别并重构成标准 LaTeX 块级公式 \[ ... \]
  text = text.replace(/(^|\n)\s*\[\s*\n+([a-zA-Z0-9_\^+\-=<>\\/\s\u4e00-\u9fa5{}]+?)\n+\s*\](?=\s*($|\n))/g, (m, prefix, content) => {
    if (/[\^_\-=<>\\{}]/.test(content)) {
      return `${prefix}\n\\[\n${content.trim()}\n\\]\n`
    }
    return m
  })

  // 3. 提取并保护 LaTeX 数学公式（防止被 marked 的下划线斜体、反斜杠转义、HTML标签转义损坏）
  const mathItems = []

  // 3.1 块级独立公式: $$ ... $$
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
    const id = mathItems.length
    try {
      const html = katex.renderToString(formula.trim(), {
        displayMode: true,
        throwOnError: false,
        strict: false
      })
      mathItems.push(html)
      return `\n\n@@KATEX_BLOCK_${id}@@\n\n`
    } catch (e) {
      return match
    }
  })

  // 3.2 块级独立公式: \[ ... \]
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, (match, formula) => {
    const id = mathItems.length
    try {
      const html = katex.renderToString(formula.trim(), {
        displayMode: true,
        throwOnError: false,
        strict: false
      })
      mathItems.push(html)
      return `\n\n@@KATEX_BLOCK_${id}@@\n\n`
    } catch (e) {
      return match
    }
  })

  // 3.3 行内公式: \( ... \)
  text = text.replace(/\\\(([\s\S]*?)\\\)/g, (match, formula) => {
    const id = mathItems.length
    try {
      const html = katex.renderToString(formula.trim(), {
        displayMode: false,
        throwOnError: false,
        strict: false
      })
      mathItems.push(html)
      return `@@KATEX_INLINE_${id}@@`
    } catch (e) {
      return match
    }
  })

  // 3.4 行内公式: $ ... $ (排查货币格式与空串)
  text = text.replace(/(^|[^\\])\$([^\$\n]+?)\$/g, (match, prefix, formula) => {
    if (/^\s*\d+(\.\d+)?\s*$/.test(formula)) {
      return match
    }
    const id = mathItems.length
    try {
      const html = katex.renderToString(formula.trim(), {
        displayMode: false,
        throwOnError: false,
        strict: false
      })
      mathItems.push(html)
      return `${prefix}@@KATEX_INLINE_${id}@@`
    } catch (e) {
      return match
    }
  })

  // 4. Markdown 编译
  let html = marked.parse(text)

  // 5. 还原占位符为高质量 KaTeX 渲染结构
  html = html.replace(/<p>\s*@@KATEX_BLOCK_(\d+)@@\s*<\/p>/g, (_, id) => {
    return `<div class="katex-display-wrapper">${mathItems[Number(id)] || ''}</div>`
  })
  html = html.replace(/@@KATEX_BLOCK_(\d+)@@/g, (_, id) => {
    return `<div class="katex-display-wrapper">${mathItems[Number(id)] || ''}</div>`
  })
  html = html.replace(/@@KATEX_INLINE_(\d+)@@/g, (_, id) => {
    return mathItems[Number(id)] || ''
  })

  return html
}
