<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AgentConfig } from '../api/contracts'

const props = withDefaults(defineProps<{
  modelValue: number | null
  agents: AgentConfig[]
  disabled?: boolean
  snapshotName?: string | null
}>(), {
  disabled: false,
  snapshotName: null,
})

const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()
const { t } = useI18n()

const selectedIsMissing = computed(() => props.modelValue !== null
  && !props.agents.some((agent) => agent.id === props.modelValue))

function update(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  emit('update:modelValue', value ? Number(value) : null)
}
</script>

<template>
  <label class="agent-select">
    <span>{{ t('chat.agent') }}</span>
    <select :value="modelValue ?? ''" :disabled="disabled" @change="update">
      <option v-if="modelValue === null" value="" disabled>{{ t('chat.conversationAgent') }}</option>
      <option v-if="selectedIsMissing" :value="modelValue">{{ snapshotName || t('chat.unknownAgent') }}</option>
      <option v-for="agent in agents" :key="agent.id" :value="agent.id">
        {{ agent.name }}{{ agent.is_default ? ` — ${t('chat.defaultAgent')}` : '' }}
      </option>
    </select>
  </label>
</template>
