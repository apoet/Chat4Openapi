<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'

const props = defineProps<{ content: string }>()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const ALLOWED_TAGS = [
  'a', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3', 'h4', 'h5',
  'h6', 'hr', 'li', 'ol', 'p', 'pre', 'strong', 'table', 'tbody', 'td', 'th',
  'thead', 'tr', 'ul',
]
const SAFE_PROTOCOLS = new Set(['http:', 'https:', 'mailto:'])

function hardenLinks(html: string): string {
  const template = document.createElement('template')
  template.innerHTML = html
  for (const anchor of template.content.querySelectorAll('a')) {
    const href = anchor.getAttribute('href')
    anchor.removeAttribute('target')
    anchor.removeAttribute('rel')
    if (!href) continue

    let url: URL
    try {
      url = new URL(href, window.location.href)
    } catch {
      anchor.removeAttribute('href')
      continue
    }
    if (!SAFE_PROTOCOLS.has(url.protocol)) {
      anchor.removeAttribute('href')
      continue
    }
    if ((url.protocol === 'http:' || url.protocol === 'https:')
      && url.origin !== window.location.origin) {
      anchor.setAttribute('target', '_blank')
      anchor.setAttribute('rel', 'noopener noreferrer')
    }
  }
  return template.innerHTML
}

const rendered = computed(() => {
  const sanitized = DOMPurify.sanitize(markdown.render(props.content), {
    ALLOWED_TAGS,
    ALLOWED_ATTR: ['class', 'href', 'title'],
    ALLOW_DATA_ATTR: false,
  })
  return hardenLinks(sanitized)
})
</script>

<template>
  <div class="markdown-body" v-html="rendered" />
</template>
