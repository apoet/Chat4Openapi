<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { SkillSummary } from '../api/contracts'

const props = withDefaults(defineProps<{
  modelValue: number[]
  skills: SkillSummary[]
  disabled?: boolean
  max?: number
}>(), {
  disabled: false,
  max: 32,
})

const emit = defineEmits<{ 'update:modelValue': [value: number[]] }>()
const { t } = useI18n()
const open = ref(false)

const selectedSkills = computed(() => props.modelValue.map((id) => ({
  id,
  name: props.skills.find((skill) => skill.id === id)?.name ?? t('chat.unknownSkill'),
})))

watch(() => props.disabled, (disabled) => {
  if (disabled) open.value = false
}, { flush: 'sync' })

function isSkillDisabled(id: number): boolean {
  return props.disabled || (!props.modelValue.includes(id) && props.modelValue.length >= props.max)
}

function toggleMenu(): void {
  if (!props.disabled) open.value = !open.value
}

function toggleSkill(id: number): void {
  if (props.disabled) return
  if (props.modelValue.includes(id)) {
    emit('update:modelValue', props.modelValue.filter((value) => value !== id))
    return
  }
  if (props.modelValue.length < props.max) emit('update:modelValue', [...props.modelValue, id])
}

function removeSkill(id: number): void {
  if (!props.disabled) emit('update:modelValue', props.modelValue.filter((value) => value !== id))
}
</script>

<template>
  <div class="skill-multi-select">
    <div class="skill-select-chips">
      <span v-if="selectedSkills.length === 0" class="skill-auto-label">{{ t('chat.autoSelect') }}</span>
      <span v-for="skill in selectedSkills" :key="skill.id" class="skill-chip">
        {{ skill.name }}
        <button
          type="button"
          :aria-label="t('chat.removeSkill', { name: skill.name })"
          :disabled="disabled"
          @click="removeSkill(skill.id)"
        >×</button>
      </span>
    </div>
    <button
      type="button"
      class="skill-select-trigger"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-label="t('chat.selectSkills')"
      :disabled="disabled"
      @click="toggleMenu"
    >
      {{ t('chat.chooseSkills') }}
    </button>
    <ul v-if="open && !disabled" class="skill-select-menu" role="listbox" :aria-label="t('chat.candidateSkills')" aria-multiselectable="true">
      <li
        v-for="skill in skills"
        :key="skill.id"
        role="option"
        :aria-selected="modelValue.includes(skill.id)"
        :aria-disabled="isSkillDisabled(skill.id)"
      >
        <label>
          <input
            type="checkbox"
            :aria-label="skill.name"
            :checked="modelValue.includes(skill.id)"
            :disabled="isSkillDisabled(skill.id)"
            @change="toggleSkill(skill.id)"
          />
          <span>{{ skill.name }}</span>
        </label>
      </li>
      <li v-if="skills.length === 0" class="skill-select-empty">{{ t('chat.noRunningSkills') }}</li>
    </ul>
  </div>
</template>
