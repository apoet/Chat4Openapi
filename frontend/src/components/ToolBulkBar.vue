<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { ToolBatchAction } from '../api/contracts'

defineProps<{
  selectedCount: number
  visibleCount: number
  pending: boolean
  error: string
  summary: string
  failures: string[]
}>()

defineEmits<{
  selectVisible: []
  clear: []
  action: [action: ToolBatchAction]
}>()

const { t } = useI18n()
</script>

<template>
  <section class="tool-bulk-bar" :aria-label="t('tools.bulk.label')">
    <strong>{{ t('tools.bulk.selected', { count: selectedCount }) }}</strong>
    <div class="tool-bulk-actions">
      <button class="secondary-action" :disabled="pending || visibleCount === 0" @click="$emit('selectVisible')">
        {{ t('tools.bulk.selectVisible') }}
      </button>
      <button class="secondary-action" :disabled="pending || selectedCount === 0" @click="$emit('clear')">
        {{ t('tools.bulk.clear') }}
      </button>
      <button class="secondary-action" :disabled="pending || selectedCount === 0" @click="$emit('action', 'enable')">
        {{ t('tools.bulk.enable') }}
      </button>
      <button class="secondary-action" :disabled="pending || selectedCount === 0" @click="$emit('action', 'disable')">
        {{ t('tools.bulk.disable') }}
      </button>
      <button class="danger-action" :disabled="pending || selectedCount === 0" @click="$emit('action', 'delete')">
        {{ t('tools.bulk.delete') }}
      </button>
    </div>
    <p v-if="error" class="tool-bulk-error" role="alert">{{ error }}</p>
    <p v-if="summary" class="tool-bulk-summary" role="status">{{ summary }}</p>
    <ul v-if="failures.length" class="tool-bulk-failures" role="alert">
      <li v-for="failure in failures" :key="failure">{{ failure }}</li>
    </ul>
  </section>
</template>
