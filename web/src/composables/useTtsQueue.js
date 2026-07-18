import { ref } from 'vue'
import { apiUrl } from '../api'

export function useTtsQueue(stageRef) {
  const status = ref('就绪')
  const queueLength = ref(0)
  let audioContext = null
  let analyser = null
  let analyserConnected = false
  let audioData = null
  let currentAudio = null
  let currentSource = null
  let currentItem = null
  let audioQueue = []
  let pending = []
  let inFlight = []
  let busy = false
  let playing = false
  let nextIndex = 0
  let generation = 0

  function stage() {
    return stageRef.value
  }

  function updateQueueLength() {
    queueLength.value = audioQueue.length
  }

  async function ensureAudioReady() {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)()
      analyser = audioContext.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.3
      audioData = new Uint8Array(analyser.fftSize)
    }
    if (audioContext.state === 'suspended') await audioContext.resume()
  }

  function volume() {
    if (!analyser || !audioData) return 0
    analyser.getByteTimeDomainData(audioData)
    let sum = 0
    for (const value of audioData) {
      const normalized = (value - 128) / 128
      sum += normalized * normalized
    }
    return Math.sqrt(sum / audioData.length)
  }

  async function fetchTts(text, roleName) {
    const response = await fetch(apiUrl('/api/tts'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, role_name: roleName }),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || '语音合成失败')
    }
    const data = await response.json()
    return { url: apiUrl(data.url), durationMs: data.duration_ms }
  }

  async function enqueue({ text, roleName, expression, intensity, action }) {
    const index = nextIndex++
    pending.push({ text, roleName, expression, intensity, action, index })
    process()
    return index
  }

  async function process() {
    if (busy) return
    const activeGeneration = generation
    busy = true
    try {
      while (pending.length && activeGeneration === generation) {
        const pendingItem = pending.shift()
        const index = pendingItem.index
        status.value = `合成 ${index + 1}...`
        let result
        inFlight.push(pendingItem)
        try {
          result = await fetchTts(pendingItem.text, pendingItem.roleName)
        } catch (error) {
          status.value = error.message || '语音合成失败'
          continue
        } finally {
          const inFlightIndex = inFlight.indexOf(pendingItem)
          if (inFlightIndex >= 0) inFlight.splice(inFlightIndex, 1)
        }
        if (activeGeneration !== generation) return
        audioQueue.push({ ...pendingItem, ...result })
        updateQueueLength()
        if (!playing) playNext()
      }
    } finally {
      if (activeGeneration === generation) {
        busy = false
      }
    }
  }

  function playNext() {
    if (!audioQueue.length) {
      playing = false
      currentItem = null
      status.value = '就绪'
      updateQueueLength()
      return
    }

    playing = true
    currentItem = audioQueue.shift()
    updateQueueLength()
    if (currentItem.expression) stage()?.setExpression(currentItem.expression, currentItem.intensity)
    if (currentItem.action && currentItem.action !== 'none') stage()?.playAction(currentItem.action)
    else stage()?.stopAction()

    status.value = `播放 ${currentItem.index + 1}`
    const audio = new Audio(currentItem.url)
    audio.crossOrigin = 'anonymous'
    currentAudio = audio
    let mouthTimer = null

    if (audioContext && analyser) {
      const source = audioContext.createMediaElementSource(audio)
      source.connect(analyser)
      if (!analyserConnected) {
        analyser.connect(audioContext.destination)
        analyserConnected = true
      }
      currentSource = source
      mouthTimer = window.setInterval(() => {
        if (!currentAudio?.paused) stage()?.setMouthOpen(Math.min(volume() * 3.5, 1))
      }, 50)
    }

    const playingItem = currentItem
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true
      if (mouthTimer) window.clearInterval(mouthTimer)
      try { currentSource?.disconnect() } catch {}
      currentSource = null
      currentAudio = null
      if (currentItem === playingItem) currentItem = null
      stage()?.setMouthOpen(0)
      stage()?.clearExpression()
      stage()?.stopAction()
      playing = false
      playNext()
    }
    audio.onended = finish
    audio.onerror = finish
    audio.play().catch(finish)
  }

  function patch(index, expression) {
    for (const item of pending) {
      if (item.index === index) Object.assign(item, expression)
    }
    for (const item of inFlight) {
      if (item.index === index) Object.assign(item, expression)
    }
    for (const item of audioQueue) {
      if (item.index === index) Object.assign(item, expression)
    }
    if (currentItem?.index === index && currentAudio) {
      const previousAction = currentItem.action || 'none'
      Object.assign(currentItem, expression)
      stage()?.setExpression(currentItem.expression, currentItem.intensity)
      const nextAction = currentItem.action || 'none'
      if (nextAction !== previousAction) {
        if (nextAction !== 'none') stage()?.playAction(nextAction)
        else stage()?.stopAction()
      }
    }
  }

  function stop() {
    generation += 1
    currentAudio?.pause()
    if (currentAudio) currentAudio.currentTime = 0
    try { currentSource?.disconnect() } catch {}
    currentAudio = null
    currentSource = null
    currentItem = null
    audioQueue = []
    pending = []
    inFlight = []
    busy = false
    playing = false
    nextIndex = 0
    status.value = '就绪'
    updateQueueLength()
    stage()?.setMouthOpen(0)
    stage()?.clearExpression()
    stage()?.stopAction()
  }

  async function dispose() {
    stop()
    await audioContext?.close()
    audioContext = null
  }

  return { status, queueLength, ensureAudioReady, enqueue, patch, stop, dispose }
}
