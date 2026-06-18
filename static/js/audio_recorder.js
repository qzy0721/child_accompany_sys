/**
 * 浏览器端麦克风录制模块
 * 用于 NiceGUI 儿童陪伴智能助手的语音输入功能
 * 
 * 流程：录制 → 转WAV(16kHz/16bit/mono) → 发送后端ASR → 返回文本
 */

/**
 * 录制音频并发送到后端进行语音识别
 * @param {number} maxSeconds - 最长录制时间（秒）
 * @returns {Promise<string>} 识别出的文本
 */
window.recordAudio = async function(maxSeconds = 8) {
    // 检测浏览器支持
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.error('浏览器不支持麦克风访问');
        return '';
    }

    let stream = null;
    let mediaRecorder = null;
    const chunks = [];

    try {
        // 获取麦克风权限
        stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                channelCount: 1,
                sampleRate: 16000,
                echoCancellation: true,
                noiseSuppression: true
            }
        });

        // 选择支持的 MIME 类型
        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : 'audio/webm';

        mediaRecorder = new MediaRecorder(stream, { mimeType });

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                chunks.push(event.data);
            }
        };

        // 开始录制
        mediaRecorder.start();
        console.log('🎤 录音开始...');

        // 等待录制完成
        const audioBlob = await new Promise((resolve, reject) => {
            mediaRecorder.onstop = () => {
                const blob = new Blob(chunks, { type: mimeType });
                resolve(blob);
            };
            mediaRecorder.onerror = (e) => {
                reject(new Error('录音失败: ' + e.error));
            };

            // 定时停止
            setTimeout(() => {
                if (mediaRecorder.state === 'recording') {
                    mediaRecorder.stop();
                }
            }, maxSeconds * 1000);
        });

        // 释放麦克风
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }

        console.log('🔄 转换音频格式...');

        // 转换为 WAV (16kHz, 16-bit, mono PCM)
        const wavBlob = await convertToWav(audioBlob);

        console.log('📤 发送音频到后端...');

        // 发送到后端语音识别接口
        const formData = new FormData();
        formData.append('audio', wavBlob, 'recording.wav');

        const response = await fetch('/api/speech-to-text', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('服务器响应错误: ' + response.status);
        }

        const data = await response.json();
        console.log('✅ 识别完成:', data.text);
        return data.text || '';

    } catch (err) {
        console.error('❌ 语音输入失败:', err.message);
        return '';
    } finally {
        // 确保释放资源
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
    }
};

/**
 * 将浏览器录制的音频 Blob 转换为 WAV 格式 (16kHz, 16-bit, mono PCM)
 * 使用 Web Audio API 进行解码和重采样
 */
async function convertToWav(blob) {
    // 使用 OfflineAudioContext 进行解码
    const sampleRate = 16000;
    const audioContext = new OfflineAudioContext(1, 1, sampleRate);

    try {
        const arrayBuffer = await blob.arrayBuffer();
        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

        // 获取单声道 PCM 数据 (已经是 16kHz 因为 OfflineAudioContext 会自动重采样)
        const channelData = audioBuffer.getChannelData(0);

        // 将 Float32Array 转换为 Int16Array
        const int16Data = new Int16Array(channelData.length);
        for (let i = 0; i < channelData.length; i++) {
            // Clamp to [-1, 1] and convert to int16
            const sample = Math.max(-1, Math.min(1, channelData[i]));
            int16Data[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
        }

        // 构建 WAV 文件
        const dataSize = int16Data.length * 2;  // 2 bytes per sample
        const wavBuffer = new ArrayBuffer(44 + dataSize);
        const view = new DataView(wavBuffer);

        // RIFF chunk descriptor
        writeString(view, 0, 'RIFF');
        view.setUint32(4, 36 + dataSize, true);  // File size - 8
        writeString(view, 8, 'WAVE');

        // fmt sub-chunk
        writeString(view, 12, 'fmt ');
        view.setUint32(16, 16, true);            // Subchunk1 size (PCM)
        view.setUint16(20, 1, true);             // Audio format (PCM = 1)
        view.setUint16(22, 1, true);             // Number of channels (mono)
        view.setUint32(24, sampleRate, true);    // Sample rate
        view.setUint32(28, sampleRate * 2, true); // Byte rate
        view.setUint16(32, 2, true);             // Block align
        view.setUint16(34, 16, true);            // Bits per sample

        // data sub-chunk
        writeString(view, 36, 'data');
        view.setUint32(40, dataSize, true);

        // Write PCM samples
        const pcmView = new Int16Array(wavBuffer, 44);
        pcmView.set(int16Data);

        return new Blob([wavBuffer], { type: 'audio/wav' });

    } catch (err) {
        console.error('音频转换失败:', err);
        throw err;
    }
}

function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
    }
}

console.log('✅ 音频录制模块已加载');
