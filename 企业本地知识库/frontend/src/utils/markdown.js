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
 * 工业级思维链碎片清洗与排版规范化：
 * 彻底消除流式推理或历史记录中产生的碎片化单字、单数字、短词与符号孤立折行（如 "3\n8\n0"、"元\n/" 等）
 * 精准保护真正的列表项、标题与完整段落换行
 */
export function cleanThought(text) {
  if (!text || typeof text !== 'string') return ''
  const rawLines = text.replace(/\r\n/g, '\n').split('\n')
  const merged = []

  for (let i = 0; i < rawLines.length; i++) {
    const cur = rawLines[i].trim()
    if (!cur) {
      const prev = merged.length > 0 ? merged[merged.length - 1].trim() : ''
      // 只有当前面内容是完整句子结尾（。！？!?），且不是列表项，且长度充足时才保留段落空行
      if (prev && /[。！？!?]$/.test(prev) && !/^[-*+•·\d+\.]/.test(prev) && prev.length > 5) {
        if (merged[merged.length - 1] !== '') {
          merged.push('')
        }
      }
      continue
    }

    if (merged.length === 0) {
      merged.push(cur)
      continue
    }

    const prev = merged[merged.length - 1]
    if (prev === '') {
      merged.push(cur)
      continue
    }

    const isCurList = /^([-*+•·]|\d+\.|\(\d+\))\s+/.test(cur)
    const isCurHeader = /^[#]{1,6}\s+/.test(cur)
    const isPrevHeader = /^[#]{1,6}\s+/.test(prev)
    const isPrevList = /^([-*+•·]|\d+\.|\(\d+\))\s+/.test(prev)

    // 绝对不合并的情况：当前行是列表项、当前行是标题、前一行是标题
    if (isCurList || isCurHeader || isPrevHeader) {
      merged.push(cur)
      continue
    }

    // 如果前一行是列表项：只有当当前行是碎片（<=4 字符）或以连接标点开头时才合并进列表项，否则作为新行
    if (isPrevList) {
      if (cur.length <= 4 || /^[/\\+*%=<>~,，;；)）\]】}、]/.test(cur)) {
        merged[merged.length - 1] = prev + cur
      } else {
        merged.push(cur)
      }
      continue
    }

    // 针对普通正文段落：
    // 如果当前行或前一行是短碎片（<= 4个字符，如 "3"、"8"、"0"、"元"、"/"、"晚" 等）
    // 或者前一行没有以标点句末符（。！？!?）结尾
    // 或者当前行以标点符号开头
    const shouldMerge = (
      cur.length <= 4 ||
      prev.length <= 4 ||
      !/[。！？!?]$/.test(prev) ||
      /^[/\\+*%=<>~,，;；)）\]】}、]/.test(cur) ||
      /[/\\+*%=<>~(（\[【{、]$/.test(prev)
    )

    if (shouldMerge) {
      const prevLastChar = prev.slice(-1)
      const curFirstChar = cur.charAt(0)
      let separator = ''
      if (/[a-zA-Z]/.test(prevLastChar) && /[a-zA-Z]/.test(curFirstChar)) {
        separator = ' '
      } else if (/[0-9]/.test(prevLastChar) && /[a-zA-Z]/.test(curFirstChar)) {
        separator = ' '
      }
      merged[merged.length - 1] = prev + separator + cur
    } else {
      merged.push(cur)
    }
  }

  return merged.join('\n')
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
