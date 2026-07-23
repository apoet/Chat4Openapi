<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <div
    class="chat-loading-indicator"
    role="status"
    aria-live="polite"
    :aria-label="t('chat.processing')"
  >
    <span class="sr-only">{{ t('chat.processing') }}</span>
    <span class="chat-loading-dot" aria-hidden="true" />
    <span class="chat-loading-dot" aria-hidden="true" />
    <span class="chat-loading-dot" aria-hidden="true" />
  </div>
</template>

<style scoped>
.chat-loading-indicator {
  width: fit-content;
  min-width: 58px;
  margin: 14px 0;
  padding: 15px 17px;
  display: flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #ded9cf;
  border-radius: 14px 14px 14px 4px;
  background: #fff;
  box-shadow: 0 2px 12px rgba(17, 25, 40, .07);
}
.chat-loading-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #6558e8;
  animation: chat-loading-pulse 1.15s ease-in-out infinite;
}
.chat-loading-dot:nth-of-type(2) { animation-delay: .14s; }
.chat-loading-dot:nth-of-type(3) { animation-delay: .28s; }
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@keyframes chat-loading-pulse {
  0%, 60%, 100% { opacity: .3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-4px); }
}
@media (prefers-reduced-motion: reduce) {
  .chat-loading-dot { animation: none; opacity: .65; }
  .chat-loading-dot:nth-of-type(2) { opacity: .85; }
  .chat-loading-dot:nth-of-type(3) { opacity: 1; }
}
</style>
