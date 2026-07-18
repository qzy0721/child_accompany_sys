<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'

const message = defineModel('message', { default: '' })
const props = defineProps({
  messages: { type: Array, default: () => [] },
  connected: { type: Boolean, default: false },
  canChat: { type: Boolean, default: false },
  sending: { type: Boolean, default: false },
  voiceMode: { type: String, default: 'idle' },
  voiceStatus: { type: String, default: '' },
  ttsStatus: { type: String, default: '就绪' },
  queueLength: { type: Number, default: 0 },
})

const emit = defineEmits(['send', 'toggle-voice'])
const messagesElement = ref(null)
const composerElement = ref(null)
let scrollFrame = 0
let resizeFrame = 0
let stickToBottom = true

function updateStickToBottom() {
  const element = messagesElement.value
  if (!element) return
  stickToBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 48
}

function queueScrollToLatest() {
  if (!stickToBottom || scrollFrame) return
  scrollFrame = window.requestAnimationFrame(() => {
    scrollFrame = 0
    const element = messagesElement.value
    if (element && stickToBottom) element.scrollTop = element.scrollHeight
  })
}

watch(() => props.messages, queueScrollToLatest, { deep: true, flush: 'post' })

function queueComposerResize() {
  if (resizeFrame) return
  resizeFrame = window.requestAnimationFrame(() => {
    resizeFrame = 0
    const element = composerElement.value
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 132)}px`
    element.style.overflowY = element.scrollHeight > 132 ? 'auto' : 'hidden'
  })
}

watch(message, queueComposerResize, { flush: 'post' })

onBeforeUnmount(() => {
  if (scrollFrame) window.cancelAnimationFrame(scrollFrame)
  if (resizeFrame) window.cancelAnimationFrame(resizeFrame)
})

function submit() {
  if (message.value.trim() && !props.sending && props.voiceMode === 'idle') emit('send')
}

function handleComposerKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  submit()
}
</script>

<template>
  <main class="chat-panel">
    <header class="chat-header">
      <h1><span class="connection-dot" :class="{ offline: !connected }"></span>虚拟陪伴助手</h1>
      <span class="muted-text">{{ connected ? '已连接' : '离线' }}</span>
    </header>

    <section ref="messagesElement" class="messages" aria-live="polite" @scroll.passive="updateStickToBottom">
      <div v-for="item in messages" :key="item.id" class="message" :class="item.role">{{ item.text }}</div>
    </section>

    <div class="status-bar">
      <span>队列: {{ queueLength }}{{ ttsStatus !== '就绪' ? ` · ${ttsStatus}` : '' }}</span>
      <span>{{ voiceStatus }}</span>
    </div>

    <form class="input-bar" @submit.prevent="submit">
      <textarea
        ref="composerElement"
        v-model="message"
        rows="1"
        :readonly="voiceMode !== 'idle'"
        :aria-busy="sending || voiceMode !== 'idle'"
        :placeholder="voiceMode !== 'idle' ? '正在识别...' : sending ? '正在生成回复...' : canChat ? '输入消息...' : '可先输入消息，选择角色后发送'"
        @keydown="handleComposerKeydown"
      ></textarea>
      <button class="btn btn-primary" :disabled="sending || voiceMode !== 'idle' || !message.trim()" type="submit">{{ sending ? '生成中...' : '发送' }}</button>
      <button
        class="btn btn-secondary voice-button"
        :class="{ recording: voiceMode === 'recording' || voiceMode === 'stopping', connecting: voiceMode === 'connecting' }"
        :disabled="!canChat || sending"
        :aria-pressed="voiceMode !== 'idle'"
        type="button"
        @click="emit('toggle-voice')"
      >{{ voiceMode === 'connecting' ? '连接中' : voiceMode === 'idle' ? '语音' : '停止' }}</button>
    </form>
  </main>
</template>
