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

  // 1.5 自动补齐因上下文截断而未闭合的语法（防止公式因截断展示为碎片文本）
  const openBlockLatex = (text.match(/\\\[/g) || []).length
  const closeBlockLatex = (text.match(/\\\]/g) || []).length
  if (openBlockLatex > closeBlockLatex) text += '\n\\]'

  const openInlineLatex = (text.match(/\\\(/g) || []).length
  const closeInlineLatex = (text.match(/\\\)/g) || []).length
  if (openInlineLatex > closeInlineLatex) text += '\\)'

  const openDoubleDollar = (text.match(/\$\$/g) || []).length
  if (openDoubleDollar % 2 === 1) text += '\n$$'

  const openBracketBlock = (text.match(/(?:^|\n)\s*\[\s*\n/g) || []).length
  const closeBracketBlock = (text.match(/(?:^|\n)\s*\]\s*(?:$|\n)/g) || []).length
  if (openBracketBlock > closeBracketBlock) text += '\n]'

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

/**
 * 优化思维链格式化：
 * 1. 彻底消除流式推理或历史记录中产生的碎片化单字/单词折行
 * 2. 保护真正的双换行段落和列表项排版
 */
export function cleanThought(text) {
  if (!text || typeof text !== 'string') return ''
  let t = text.replace(/\r\n/g, '\n')

  // 保护真正的段落换行（双换行）
  t = t.replace(/\n\s*\n+/g, '@@PARAGRAPH_BREAK@@')

  // 保护列表项换行（如 "- ", "* ", "1. ", "• "）
  t = t.replace(/\n(?=\s*[-*•·\d+\.])/g, '@@LIST_BREAK@@')

  // 规则：汉字与标点符号（包括全角标点、CJK标点如句号顿号引号）之间的单个换行直接剔除；汉字与英数之间单个换行剔除；英数之间的单个换行变为空格
  const CJK_CHARS = '[\\u4e00-\\u9fa5\\u3000-\\u303f\\uff00-\\uffef“”‘’《》、（）\\[\\]]'
  t = t.replace(new RegExp(`(${CJK_CHARS})\\n+(?=${CJK_CHARS})`, 'g'), '$1')
  t = t.replace(new RegExp(`(${CJK_CHARS})\\n+(?=[a-zA-Z0-9])`, 'g'), '$1')
  t = t.replace(new RegExp(`([a-zA-Z0-9])\\n+(?=${CJK_CHARS})`, 'g'), '$1')
  t = t.replace(/([a-zA-Z0-9])\n+(?=[a-zA-Z0-9])/g, '$1 ')

  // 还原真正的段落与列表换行
  t = t.replace(/@@PARAGRAPH_BREAK@@/g, '\n\n')
  t = t.replace(/@@LIST_BREAK@@/g, '\n')
  return t
}

/**
 * 高保真思维链富文本渲染
 */
export function renderThought(rawText) {
  if (!rawText) return ''
  const cleaned = cleanThought(rawText)
  try {
    return renderMarkdown(cleaned)
  } catch {
    return cleaned
  }
}
