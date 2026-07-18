<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiUrl } from './api'
import { guessExpression } from './expression'
import ChatPanel from './components/ChatPanel.vue'
import CompanionStage from './components/CompanionStage.vue'
import RoleSidebar from './components/RoleSidebar.vue'
import { useAsrStream } from './composables/useAsrStream'
import { useChatStream } from './composables/useChatStream'
import { useTtsQueue } from './composables/useTtsQueue'

const roles = ref([])
const selectedRole = ref(null)
const roleStatus = ref('加载中...')
const connected = ref(false)
const messageDraft = ref('')
const messages = ref([{ id: 0, role: 'system', text: '选择角色开始对话' }])
const stage = ref(null)
const generating = ref(false)
let messageId = 1
let sendGeneration = 0

const tts = useTtsQueue(stage)
const chat = useChatStream()
const asr = useAsrStream({
  onComplete: (text) => {
    if (!text) {
      addMessage('system', '没有识别到语音')
      return
    }
    messageDraft.value = text
  },
  onError: (message) => addMessage('system', `语音识别失败：${message}`),
})

watch(asr.draft, (text) => {
  if (asr.mode.value !== 'idle') messageDraft.value = text
})

function addMessage(role, text) {
  const item = { id: messageId++, role, text }
  messages.value.push(item)
  // Return Vue's proxied entry so streamed text mutations trigger rendering.
  return messages.value[messages.value.length - 1]
}

async function fetchExpressions(sentences) {
  if (!sentences.length) return []
  try {
    const response = await fetch(apiUrl('/api/chat/expressions'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sentences,
        available_expressions: stage.value?.getExpressions() || ['happy', 'sad', 'angry', 'surprised', 'relaxed', 'neutral'],
        available_actions: stage.value?.getActions() || ['none'],
      }),
    })
    if (!response.ok) throw new Error('表情分析失败')
    return (await response.json()).expressions || []
  } catch {
    return []
  }
}

async function sendMessage() {
  const text = messageDraft.value.trim()
  if (!text || generating.value || chat.sending.value) return
  if (!selectedRole.value) {
    addMessage('system', '请先在左侧选择角色，或通过“新建角色”创建一位陪伴者')
    return
  }

  const activeGeneration = ++sendGeneration
  generating.value = true
  messageDraft.value = ''
  const sentences = []
  let assistantMessage = null
  let statusMessage = null
  let hasAssistantText = false

  try {
    await tts.ensureAudioReady()
    if (activeGeneration !== sendGeneration) return

    await chat.send({
      roleName: selectedRole.value,
      message: text,
      onStart: () => {
        tts.stop()
        addMessage('user', text)
        assistantMessage = addMessage('assistant', '思考中...')
        statusMessage = addMessage('system', '思考中...')
        hasAssistantText = false
      },
      onDelta: (delta) => {
        if (!assistantMessage || !delta) return
        assistantMessage.text = hasAssistantText ? `${assistantMessage.text}${delta}` : delta
        hasAssistantText = true
      },
      onText: (content) => {
        if (assistantMessage) assistantMessage.text = content || '...'
        hasAssistantText = Boolean(content)
      },
      onSentence: async (sentence) => {
        const expression = guessExpression(sentence)
        sentences.push(sentence)
        statusMessage.text = `已生成 ${sentences.length} 句...`
        await tts.enqueue({ text: sentence, roleName: selectedRole.value, ...expression })
      },
      onDone: async (content) => {
        if (assistantMessage) assistantMessage.text = content
        if (statusMessage) statusMessage.text = sentences.length ? '文本完成，正在匹配表情...' : '完成'
        const expressions = await fetchExpressions(sentences)
        if (activeGeneration !== sendGeneration) return
        for (const item of expressions) {
          const index = item.sentence_index
          if (!Number.isInteger(index) || index < 0 || index >= sentences.length) continue
          tts.patch(index, item)
        }
        if (statusMessage) statusMessage.text = sentences.length ? `完成，共 ${sentences.length} 句` : '完成'
      },
      onError: (error) => {
        if (assistantMessage) assistantMessage.text = `出错：${error}`
        if (statusMessage) statusMessage.text = ''
      },
    })
  } finally {
    if (activeGeneration === sendGeneration) generating.value = false
  }
}

function cancelGeneration() {
  sendGeneration += 1
  generating.value = false
  chat.cancel()
}

async function toggleVoice() {
  if (asr.mode.value === 'idle') {
    tts.stop()
    cancelGeneration()
  }
  await asr.toggle()
}

async function loadRoles() {
  roleStatus.value = '加载中...'
  try {
    const response = await fetch(apiUrl('/api/roles'))
    if (!response.ok) throw new Error('角色加载失败')
    roles.value = (await response.json()).roles || []
    roleStatus.value = ''
    if (roles.value.length && !selectedRole.value) await selectRole(roles.value[0])
  } catch {
    roleStatus.value = '角色加载失败'
  }
}

async function selectRole(roleName) {
  if (selectedRole.value === roleName) return
  cancelGeneration()
  tts.stop()
  selectedRole.value = roleName
  await loadChatHistory(roleName)
}

async function loadChatHistory(roleName) {
  try {
    const response = await fetch(apiUrl('/api/history'))
    if (!response.ok) throw new Error('历史记录载入失败')
    const history = (await response.json()).history || []
    const roleHistory = history.filter((item) => item.role_name === roleName)
    messages.value = []
    if (!roleHistory.length) {
      addMessage('system', `开始和 ${roleName} 对话`)
      return
    }
    addMessage('system', `已载入 ${roleHistory.length} 轮历史`)
    for (const turn of roleHistory.slice(-10)) {
      for (const item of turn.messages || []) addMessage(item.role === 'user' ? 'user' : 'assistant', item.content)
    }
  } catch {
    messages.value = []
    addMessage('system', '历史记录载入失败')
  }
}

async function deleteRole(roleName) {
  if (!window.confirm(`确定删除角色“${roleName}”吗？`)) return
  try {
    const response = await fetch(apiUrl(`/api/roles/${encodeURIComponent(roleName)}`), { method: 'DELETE' })
    if (!response.ok) throw new Error('删除失败')
    if (selectedRole.value === roleName) selectedRole.value = null
    await loadRoles()
    addMessage('system', `角色“${roleName}”已删除`)
  } catch {
    addMessage('system', '删除角色失败')
  }
}

async function uploadVrm(file) {
  addMessage('system', `正在加载 VRM：${file.name}...`)
  try {
    const result = await stage.value?.loadFile(file)
    const expressions = result?.expressions?.slice(0, 6).join(', ') || '默认表情'
    addMessage('system', `模型已切换：${file.name} - ${expressions}`)
  } catch (error) {
    addMessage('system', `VRM 加载失败：${error.message || '未知错误'}`)
  }
}

async function showMemories() {
  try {
    const response = await fetch(apiUrl('/api/memory'))
    const data = await response.json()
    if (!data.total) {
      addMessage('system', '还没有长期记忆')
      return
    }
    addMessage('system', `长期记忆 ${data.total} 条：`)
    for (const memory of data.memories.slice(-5)) addMessage('system', `#${memory.id} ${memory.content}`)
  } catch {
    addMessage('system', '获取记忆失败')
  }
}

async function generateMemory() {
  addMessage('system', '正在生成长期记忆...')
  try {
    const response = await fetch(apiUrl('/api/memory/generate'), { method: 'POST' })
    const data = await response.json()
    addMessage('system', data.memory || data.message || '暂无可提取的记忆')
  } catch {
    addMessage('system', '生成记忆失败')
  }
}

async function clearMemories() {
  if (!window.confirm('确定清空所有长期记忆吗？')) return
  try {
    await fetch(apiUrl('/api/memory'), { method: 'DELETE' })
    addMessage('system', '长期记忆已清空')
  } catch {
    addMessage('system', '清空记忆失败')
  }
}

async function clearHistory() {
  if (!window.confirm('确定清空所有对话历史吗？')) return
  try {
    await fetch(apiUrl('/api/history'), { method: 'DELETE' })
    await fetch(apiUrl('/api/chat/history'), { method: 'DELETE' })
    messages.value = []
    addMessage('system', '对话历史已清空')
  } catch {
    addMessage('system', '清空历史失败')
  }
}

async function checkHealth() {
  try {
    const response = await fetch(apiUrl('/api/health'))
    connected.value = response.ok && (await response.json()).status === 'ok'
  } catch {
    connected.value = false
  }
}

onMounted(async () => {
  await checkHealth()
  await loadRoles()
})

onBeforeUnmount(async () => {
  cancelGeneration()
  await tts.dispose()
  await asr.dispose()
})
</script>

<template>
  <div class="app-shell">
    <RoleSidebar
      :roles="roles"
      :selected-role="selectedRole"
      :role-status="roleStatus"
      @select-role="selectRole"
      @delete-role="deleteRole"
      @upload-vrm="uploadVrm"
      @show-memories="showMemories"
      @generate-memory="generateMemory"
      @clear-memories="clearMemories"
      @clear-history="clearHistory"
    >
      <template #stage>
        <CompanionStage ref="stage" />
      </template>
    </RoleSidebar>

    <ChatPanel
      v-model:message="messageDraft"
      :messages="messages"
      :connected="connected"
      :can-chat="Boolean(selectedRole)"
      :sending="generating || chat.sending.value"
      :voice-mode="asr.mode.value"
      :voice-status="asr.status.value"
      :tts-status="tts.status.value"
      :queue-length="tts.queueLength.value"
      @send="sendMessage"
      @toggle-voice="toggleVoice"
    />
  </div>
</template>
