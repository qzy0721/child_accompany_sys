<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { apiUrl } from './api'

const loading = ref(true)
const saving = ref(false)
const applying = ref(false)
const notice = ref('')
const errorMessage = ref('')
const serverInstanceId = ref('')
const enablingDefaultVoice = ref(false)
const persistedDefaultProvider = ref('cosyvoice')

const defaultRole = reactive({
  roleName: '',
  voiceEnabled: false,
})

const form = reactive({
  llmApiKey: '',
  llmApiUrl: '',
  llmModel: '',
  dashscopeApiKey: '',
  dashscopeWorkspaceId: '',
  defaultTtsProvider: 'cosyvoice',
  ossAccessKeyId: '',
  ossAccessKeySecret: '',
  ossEndpoint: '',
  ossBucketName: '',
})

const keyStatus = reactive({
  llmApiKey: { configured: false, hint: '' },
  dashscopeApiKey: { configured: false, hint: '' },
  ossAccessKeyId: { configured: false, hint: '' },
  ossAccessKeySecret: { configured: false, hint: '' },
})

const showSecret = reactive({
  llmApiKey: false,
  dashscopeApiKey: false,
  ossAccessKeyId: false,
  ossAccessKeySecret: false,
})

const dashscopeReady = computed(() => (
  keyStatus.dashscopeApiKey.configured || Boolean(form.dashscopeApiKey.trim())
))
const ossAccessKeyIdReady = computed(() => (
  keyStatus.ossAccessKeyId.configured || Boolean(form.ossAccessKeyId.trim())
))
const ossAccessKeySecretReady = computed(() => (
  keyStatus.ossAccessKeySecret.configured || Boolean(form.ossAccessKeySecret.trim())
))
const ossLocationReady = computed(() => (
  Boolean(form.ossEndpoint.trim()) && Boolean(form.ossBucketName.trim())
))
const qwenAvailable = computed(() => dashscopeReady.value)
const cosyVoiceAvailable = computed(() => (
  dashscopeReady.value
  && ossAccessKeyIdReady.value
  && ossAccessKeySecretReady.value
  && ossLocationReady.value
))
const selectedProviderAvailable = computed(() => (
  form.defaultTtsProvider === 'cosyvoice' ? cosyVoiceAvailable.value : qwenAvailable.value
))
const defaultProviderDirty = computed(() => (
  form.defaultTtsProvider !== persistedDefaultProvider.value
))
const ossPartiallyConfigured = computed(() => {
  const configuredCount = [
    ossAccessKeyIdReady.value,
    ossAccessKeySecretReady.value,
  ].filter(Boolean).length
  return configuredCount === 1
})
const voiceConfigurationMessage = computed(() => {
  if (!dashscopeReady.value) return '填写 DashScope API Key 后，Qwen3-TTS 即可使用。'
  if (!cosyVoiceAvailable.value) return 'Qwen3-TTS 已可用；补全 OSS 配置后可启用 CosyVoice。'
  return '两个语音引擎均已就绪，可为不同角色分别选择。'
})

const canSave = computed(() => (
  form.llmApiUrl.trim()
  && form.llmModel.trim()
  && (keyStatus.llmApiKey.configured || form.llmApiKey.trim())
  && (keyStatus.dashscopeApiKey.configured || form.dashscopeApiKey.trim())
  && selectedProviderAvailable.value
  && !ossPartiallyConfigured.value
))

const canEnableDefaultVoice = computed(() => (
  !defaultRole.voiceEnabled
  && !defaultProviderDirty.value
  && keyStatus.dashscopeApiKey.configured
  && (
    form.defaultTtsProvider !== 'cosyvoice'
    || (keyStatus.ossAccessKeyId.configured && keyStatus.ossAccessKeySecret.configured)
  )
))

function secretType(name) {
  return showSecret[name] ? 'text' : 'password'
}

function statusLabel(status) {
  return status.configured ? status.hint || '已配置' : '尚未配置'
}

async function readError(response, fallback) {
  const body = await response.json().catch(() => ({}))
  return body.detail || body.message || fallback
}

async function fetchStatus() {
  const response = await fetch(apiUrl('/api/settings/status'), {
    cache: 'no-store',
    headers: { 'Cache-Control': 'no-store' },
  })
  if (!response.ok) throw new Error(await readError(response, '服务设置载入失败'))
  return response.json()
}

async function fetchDefaultRoleStatus() {
  const response = await fetch(apiUrl('/api/roles/default/status'), {
    cache: 'no-store',
    headers: { 'Cache-Control': 'no-store' },
  })
  if (!response.ok) throw new Error(await readError(response, '默认角色状态载入失败'))
  return response.json()
}

function applyStatus(data) {
  keyStatus.llmApiKey = data.llm_api_key
  keyStatus.dashscopeApiKey = data.dashscope_api_key
  keyStatus.ossAccessKeyId = data.oss_access_key_id
  keyStatus.ossAccessKeySecret = data.oss_access_key_secret
  form.llmApiUrl = data.llm_api_url || ''
  form.llmModel = data.llm_model || ''
  form.dashscopeWorkspaceId = data.dashscope_workspace_id || ''
  form.ossEndpoint = data.oss_endpoint || ''
  form.ossBucketName = data.oss_bucket_name || ''
  const savedProvider = data.default_tts_provider || 'cosyvoice'
  persistedDefaultProvider.value = savedProvider
  form.defaultTtsProvider = savedProvider
  if (savedProvider === 'cosyvoice' && !cosyVoiceAvailable.value && qwenAvailable.value) {
    form.defaultTtsProvider = 'qwen_tts'
  }
  serverInstanceId.value = data.server_instance_id || ''
}

function applyDefaultRoleStatus(data) {
  defaultRole.roleName = data.role_name || '默认角色'
  defaultRole.voiceEnabled = Boolean(data.voice_enabled)
}

async function loadStatus() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [settingsStatus, defaultRoleStatus] = await Promise.all([
      fetchStatus(),
      fetchDefaultRoleStatus(),
    ])
    applyStatus(settingsStatus)
    applyDefaultRoleStatus(defaultRoleStatus)
  } catch (error) {
    errorMessage.value = error.message || '服务设置载入失败'
  } finally {
    loading.value = false
  }
}

async function enableDefaultVoice() {
  if (!canEnableDefaultVoice.value || enablingDefaultVoice.value) return

  enablingDefaultVoice.value = true
  notice.value = ''
  errorMessage.value = ''
  try {
    const response = await fetch(apiUrl('/api/roles/default/enable-voice'), {
      method: 'POST',
      headers: { 'Cache-Control': 'no-store' },
    })
    if (!response.ok) throw new Error(await readError(response, '默认角色语音启用失败'))

    defaultRole.voiceEnabled = true
    notice.value = `已为 ${defaultRole.roleName} 启用语音`
  } catch (error) {
    errorMessage.value = error.message || '默认角色语音启用失败'
  } finally {
    enablingDefaultVoice.value = false
  }
}

function clearSecretInputs() {
  form.llmApiKey = ''
  form.dashscopeApiKey = ''
  form.ossAccessKeyId = ''
  form.ossAccessKeySecret = ''
  Object.keys(showSecret).forEach((key) => { showSecret[key] = false })
}

function sleep(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

async function waitForRestart(previousInstanceId) {
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    await sleep(500)
    try {
      const data = await fetchStatus()
      if (data.server_instance_id && data.server_instance_id !== previousInstanceId) {
        applying.value = false
        notice.value = '配置已生效，可按需为默认角色启用语音。'
        await loadStatus()
        return
      }
    } catch {
      // Uvicorn 正在切换子进程，下一轮继续探测。
    }
  }

  applying.value = false
  errorMessage.value = '配置已保存，但服务未在 30 秒内恢复。请检查后端日志后重新打开此页面。'
}

async function saveSettings() {
  if (!canSave.value || saving.value || applying.value) {
    if (ossPartiallyConfigured.value) errorMessage.value = 'OSS Access Key ID 与 Secret 需要成对配置'
    else if (!selectedProviderAvailable.value) errorMessage.value = '当前默认语音引擎配置不完整，请更换引擎或补齐所需配置'
    else errorMessage.value = '请先填写所有必填配置项'
    return
  }

  saving.value = true
  notice.value = ''
  errorMessage.value = ''
  const previousInstanceId = serverInstanceId.value
  const payload = {
    llm_api_key: form.llmApiKey || null,
    llm_api_url: form.llmApiUrl,
    llm_model: form.llmModel,
    dashscope_api_key: form.dashscopeApiKey || null,
    dashscope_workspace_id: form.dashscopeWorkspaceId,
    default_tts_provider: form.defaultTtsProvider,
    oss_access_key_id: form.ossAccessKeyId || null,
    oss_access_key_secret: form.ossAccessKeySecret || null,
    oss_endpoint: form.ossEndpoint,
    oss_bucket_name: form.ossBucketName,
  }

  try {
    const response = await fetch(apiUrl('/api/settings'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) throw new Error(await readError(response, '配置保存失败'))

    const result = await response.json()
    clearSecretInputs()
    if (!result.restart_required) {
      notice.value = result.message || '配置已保存'
      await loadStatus()
      return
    }

    applying.value = true
    notice.value = '配置已保存，正在重新连接服务...'
    await waitForRestart(previousInstanceId)
  } catch (error) {
    if (error instanceof TypeError && previousInstanceId) {
      applying.value = true
      notice.value = '连接已中断，正在确认服务是否完成重启...'
      await waitForRestart(previousInstanceId)
      return
    }
    errorMessage.value = error.message || '配置保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(loadStatus)
</script>

<template>
  <main class="settings-page">
    <header class="settings-header">
      <div>
        <p class="page-eyebrow">Virtual Companion</p>
        <h1>服务设置</h1>
        <p class="page-summary">在本机保存模型与语音服务配置。密钥不会回传到浏览器。</p>
      </div>
      <a class="btn btn-secondary settings-back-link" href="./">返回陪伴空间</a>
    </header>

    <p v-if="notice" class="settings-notice" aria-live="polite">{{ notice }}</p>
    <p v-if="errorMessage" class="settings-error" role="alert">{{ errorMessage }}</p>

    <section v-if="loading" class="settings-loading">正在载入服务设置...</section>

    <form v-else class="settings-form" @submit.prevent="saveSettings">
      <section class="settings-section">
        <div class="settings-section-heading">
          <div>
            <p class="section-kicker">对话能力</p>
            <h2>LLM 配置</h2>
          </div>
          <span class="settings-section-note">均为必填</span>
        </div>

        <div class="settings-fields">
          <label class="settings-field settings-field-wide">
            <span>LLM API Key <b>*</b></span>
            <span class="secret-input-wrap">
              <input v-model="form.llmApiKey" :type="secretType('llmApiKey')" autocomplete="new-password" :placeholder="keyStatus.llmApiKey.configured ? '留空以保留当前密钥' : '填写 API Key'" />
              <button type="button" class="secret-toggle" @click="showSecret.llmApiKey = !showSecret.llmApiKey">{{ showSecret.llmApiKey ? '隐藏' : '显示' }}</button>
            </span>
            <small :class="{ configured: keyStatus.llmApiKey.configured }">{{ statusLabel(keyStatus.llmApiKey) }}{{ keyStatus.llmApiKey.configured ? '，留空将保留' : '' }}</small>
          </label>

          <label class="settings-field settings-field-wide">
            <span>LLM API 地址 <b>*</b></span>
            <input v-model="form.llmApiUrl" inputmode="url" placeholder="https://api.example.com/v1" required />
          </label>

          <label class="settings-field settings-field-wide">
            <span>模型名称 <b>*</b></span>
            <input v-model="form.llmModel" placeholder="例如：deepseek-v4-flash" required />
          </label>
        </div>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <div>
            <p class="section-kicker">语音与识别</p>
            <h2>DashScope / 百炼</h2>
          </div>
          <span class="settings-section-note">Workspace 可选</span>
        </div>

        <div class="settings-fields">
          <label class="settings-field settings-field-wide">
            <span>DashScope API Key <b>*</b></span>
            <span class="secret-input-wrap">
              <input v-model="form.dashscopeApiKey" :type="secretType('dashscopeApiKey')" autocomplete="new-password" :placeholder="keyStatus.dashscopeApiKey.configured ? '留空以保留当前密钥' : '填写 DashScope API Key'" />
              <button type="button" class="secret-toggle" @click="showSecret.dashscopeApiKey = !showSecret.dashscopeApiKey">{{ showSecret.dashscopeApiKey ? '隐藏' : '显示' }}</button>
            </span>
            <small :class="{ configured: keyStatus.dashscopeApiKey.configured }">{{ statusLabel(keyStatus.dashscopeApiKey) }}{{ keyStatus.dashscopeApiKey.configured ? '，留空将保留' : '' }}</small>
          </label>

          <label class="settings-field settings-field-wide">
            <span>Workspace ID <em>可选</em></span>
            <input v-model="form.dashscopeWorkspaceId" placeholder="未使用业务空间时留空" />
            <small>用于实时 ASR 的业务空间专属连接。</small>
          </label>

          <fieldset class="settings-provider-field settings-field-wide">
            <legend>默认语音引擎</legend>
            <div class="settings-provider-options">
              <label :class="{ active: form.defaultTtsProvider === 'cosyvoice', unavailable: !cosyVoiceAvailable }">
                <input v-model="form.defaultTtsProvider" value="cosyvoice" type="radio" :disabled="!cosyVoiceAvailable" />
                <span><strong>CosyVoice</strong><small>{{ cosyVoiceAvailable ? '已就绪' : '需要 OSS' }}</small></span>
              </label>
              <label :class="{ active: form.defaultTtsProvider === 'qwen_tts', unavailable: !qwenAvailable }">
                <input v-model="form.defaultTtsProvider" value="qwen_tts" type="radio" :disabled="!qwenAvailable" />
                <span><strong>Qwen3-TTS</strong><small>{{ qwenAvailable ? '已就绪' : '需要 DashScope' }}</small></span>
              </label>
            </div>
            <small>{{ voiceConfigurationMessage }}</small>
          </fieldset>
        </div>
      </section>

      <section class="settings-section" :class="{ 'settings-section-muted': form.defaultTtsProvider !== 'cosyvoice' }">
        <div class="settings-section-heading">
          <div>
            <p class="section-kicker">CosyVoice 专用</p>
            <h2>阿里云 OSS</h2>
          </div>
          <span class="settings-section-note">使用 Qwen 时可留空</span>
        </div>

        <div class="settings-fields settings-fields-two-column">
          <label class="settings-field">
            <span>Access Key ID</span>
            <span class="secret-input-wrap">
              <input v-model="form.ossAccessKeyId" :type="secretType('ossAccessKeyId')" autocomplete="new-password" :placeholder="keyStatus.ossAccessKeyId.configured ? '留空以保留当前密钥' : 'CosyVoice 使用时填写'" />
              <button type="button" class="secret-toggle" @click="showSecret.ossAccessKeyId = !showSecret.ossAccessKeyId">{{ showSecret.ossAccessKeyId ? '隐藏' : '显示' }}</button>
            </span>
            <small :class="{ configured: keyStatus.ossAccessKeyId.configured }">{{ statusLabel(keyStatus.ossAccessKeyId) }}</small>
          </label>

          <label class="settings-field">
            <span>Access Key Secret</span>
            <span class="secret-input-wrap">
              <input v-model="form.ossAccessKeySecret" :type="secretType('ossAccessKeySecret')" autocomplete="new-password" :placeholder="keyStatus.ossAccessKeySecret.configured ? '留空以保留当前密钥' : 'CosyVoice 使用时填写'" />
              <button type="button" class="secret-toggle" @click="showSecret.ossAccessKeySecret = !showSecret.ossAccessKeySecret">{{ showSecret.ossAccessKeySecret ? '隐藏' : '显示' }}</button>
            </span>
            <small :class="{ configured: keyStatus.ossAccessKeySecret.configured }">{{ statusLabel(keyStatus.ossAccessKeySecret) }}</small>
          </label>

          <label class="settings-field">
            <span>OSS Endpoint</span>
            <input v-model="form.ossEndpoint" placeholder="oss-cn-shanghai.aliyuncs.com" />
          </label>

          <label class="settings-field">
            <span>Bucket 名称</span>
            <input v-model="form.ossBucketName" placeholder="cosyvoice-reference-voice" />
          </label>
        </div>
        <p v-if="ossPartiallyConfigured" class="settings-inline-warning">OSS Access Key ID 与 Secret 需要成对配置。</p>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <div>
            <p class="section-kicker">默认陪伴角色</p>
            <h2>语音注册</h2>
          </div>
          <span class="settings-section-note">{{ defaultRole.voiceEnabled ? '语音已启用' : '自动注册' }}</span>
        </div>

        <div class="default-voice-action">
          <div>
            <strong>{{ defaultRole.roleName || '默认角色' }}</strong>
            <p v-if="defaultRole.voiceEnabled">已配置复刻音色，可在对话中使用语音回复。</p>
            <p v-else>将按“默认语音引擎”注册音色；CosyVoice 需要 OSS，Qwen3-TTS 不需要。</p>
          </div>
          <button
            class="btn btn-secondary"
            type="button"
            :disabled="!canEnableDefaultVoice || enablingDefaultVoice"
            @click="enableDefaultVoice"
          >
            {{ defaultRole.voiceEnabled ? '语音已启用' : enablingDefaultVoice ? '正在注册...' : '重试注册' }}
          </button>
        </div>
        <small v-if="!defaultRole.voiceEnabled && !canEnableDefaultVoice" class="default-voice-hint">
          {{ defaultProviderDirty ? '请先保存默认语音引擎并等待服务重启。' : '请先保存所选语音引擎需要的配置；服务重启后会自动注册音色。' }}
        </small>
      </section>

      <footer class="settings-footer">
        <p>保存后会短暂中断当前对话和录音，并自动重新连接服务。</p>
        <button class="btn btn-primary settings-save-button" :disabled="!canSave || saving || applying" type="submit">
          {{ applying ? '正在应用配置...' : saving ? '正在保存...' : '保存并应用配置' }}
        </button>
      </footer>
    </form>

    <div v-if="applying" class="settings-applying" role="status" aria-live="assertive">
      <div>
        <span class="settings-spinner" aria-hidden="true"></span>
        <h2>正在重启服务</h2>
        <p>新配置生效后会回到此页面。</p>
      </div>
    </div>
  </main>
</template>
