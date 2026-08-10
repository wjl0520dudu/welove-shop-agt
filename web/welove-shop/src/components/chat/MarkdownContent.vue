<template>
  <rich-text class="markdown-content" :nodes="nodes" />
</template>

<script>
const BLOCK_STYLE = 'display:block;line-height:1.6;margin:0 0 8px;'
const LIST_STYLE = 'display:block;line-height:1.6;margin:0 0 8px;padding-left:20px;'
const LIST_ITEM_STYLE = 'display:list-item;margin:0 0 5px;'

function textNode(text) {
  return { type: 'text', text }
}

function inlineNodes(value) {
  const source = String(value || '')
  const nodes = []
  let cursor = 0

  while (cursor < source.length) {
    const boldStart = source.indexOf('**', cursor)
    const lineBreak = source.indexOf('\n', cursor)
    const next = [boldStart, lineBreak].filter(index => index >= 0)
    const nextIndex = next.length ? Math.min(...next) : -1

    if (nextIndex < 0) {
      nodes.push(textNode(source.slice(cursor)))
      break
    }
    if (nextIndex > cursor) {
      nodes.push(textNode(source.slice(cursor, nextIndex)))
      cursor = nextIndex
      continue
    }
    if (source.startsWith('\n', cursor)) {
      nodes.push({ name: 'br' })
      cursor += 1
      continue
    }

    const boldEnd = source.indexOf('**', cursor + 2)
    if (boldEnd < 0) {
      nodes.push(textNode('**'))
      cursor += 2
      continue
    }
    const content = source.slice(cursor + 2, boldEnd)
    if (content) {
      nodes.push({
        name: 'strong',
        attrs: { style: 'font-weight:700;color:#1d2939;' },
        children: [textNode(content)]
      })
    }
    cursor = boldEnd + 2
  }

  return nodes.length ? nodes : [textNode('')]
}

function markdownNodes(content) {
  const lines = String(content || '').replace(/\r\n?/g, '\n').split('\n')
  const nodes = []
  let paragraph = []
  let list = null

  const flushParagraph = () => {
    if (!paragraph.length) return
    nodes.push({
      name: 'div',
      attrs: { style: BLOCK_STYLE },
      children: inlineNodes(paragraph.join('\n'))
    })
    paragraph = []
  }
  const flushList = () => {
    if (!list) return
    nodes.push(list)
    list = null
  }
  const appendListItem = (type, value) => {
    flushParagraph()
    if (!list || list.name !== type) {
      flushList()
      list = { name: type, attrs: { style: LIST_STYLE }, children: [] }
    }
    list.children.push({
      name: 'li',
      attrs: { style: LIST_ITEM_STYLE },
      children: inlineNodes(value)
    })
  }

  for (const line of lines) {
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/)

    if (!line.trim()) {
      flushParagraph()
      flushList()
    } else if (heading) {
      flushParagraph()
      flushList()
      const level = heading[1].length
      nodes.push({
        name: level === 1 ? 'h3' : 'h4',
        attrs: { style: `display:block;font-weight:700;line-height:1.45;margin:0 0 8px;font-size:${level === 1 ? '1.2em' : '1.08em'};color:#1d2939;` },
        children: inlineNodes(heading[2])
      })
    } else if (unordered) {
      appendListItem('ul', unordered[1])
    } else if (ordered) {
      appendListItem('ol', ordered[1])
    } else {
      flushList()
      paragraph.push(line)
    }
  }

  flushParagraph()
  flushList()
  return nodes
}

export default {
  name: 'MarkdownContent',
  props: {
    content: { type: String, default: '' }
  },
  computed: {
    nodes() {
      // rich-text receives structured text nodes, never model-supplied HTML.
      return markdownNodes(this.content)
    }
  }
}
</script>

<style scoped>
.markdown-content {
  display: block;
  width: 100%;
  color: inherit;
  word-break: break-word;
}
</style>
