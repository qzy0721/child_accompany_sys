import sys
import time
import queue
import threading
from typing import Optional
import sounddevice as sd

# 导入DashScope相关模块
import dashscope
from dashscope.audio.asr import (
    Recognition,
    RecognitionCallback,
    RecognitionResult
)

# 从config.py导入API Key
try:
    from config import Qwen_API_KEY
    dashscope.api_key = Qwen_API_KEY
except ImportError:
    print("❌ 无法从config.py导入Qwen_API_KEY，请确保config.py存在且包含Qwen_API_KEY")
    raise


class VoiceRecognizerCallback(RecognitionCallback):
    """语音识别回调类"""
    def __init__(self):
        super().__init__()
        self.results = []  # 存储识别结果
        self.partial_result = ""  # 部分识别结果
        self.result_event = threading.Event()  # 结果事件
        self.connection_ready = threading.Event()  # 连接就绪事件
        self.sentence_end_event = threading.Event()  # 句子结束事件
        self.last_sentence_end = True  # 标记上一个句子是否结束
        
    def on_open(self) -> None:
        """WebSocket连接成功"""
        print("✅ 云端连接已建立")
        self.connection_ready.set()
    
    def on_close(self) -> None:
        """连接关闭"""
        print("🔌 连接已关闭")
        self.result_event.set()
    
    def on_complete(self) -> None:
        """识别完成"""
        print("✅ 识别完成")
        self.result_event.set()
    
    def on_error(self, message) -> None:
        """错误处理"""
        print(f"❌ 识别错误: {message.message}")
        self.result_event.set()
    
    def on_event(self, result: RecognitionResult) -> None:
        """处理识别事件"""
        try:
            sentence = result.get_sentence()
            if 'text' in sentence:
                text = sentence['text']
                
                if RecognitionResult.is_sentence_end(sentence):
                    # 句子结束，添加到最终结果
                    if text.strip():
                        self.results.append(text)
                        print(f"\n✅ 识别到完整句子: {text}")
                        self.sentence_end_event.set()  # 触发句子结束事件
                        self.last_sentence_end = True
                else:
                    # 部分识别结果
                    if text.strip():
                        self.partial_result = text
                        print(f"\r部分识别: {text}", end='', flush=True)
                        self.last_sentence_end = False
        
        except Exception as e:
            print(f"\n❌ 事件处理出错: {e}")


class VoiceRecognizer:
    def __init__(self, model_path="model/vosk-model-cn-0.22", samplerate=16000):
        """
        初始化语音识别器（使用DashScope实时语音识别API）
        :param model_path: 保留参数，用于兼容原有接口（不使用）
        :param samplerate: 音频采样率 (默认16kHz，支持8000和16000)
        """
        # 设置WebSocket API URL
        dashscope.base_websocket_api_url = 'wss://dashscope.aliyuncs.com/api-ws/v1/inference'
        
        # 模型配置
        self.model_name = "paraformer-realtime-v2"  # 实时语音识别模型
        
        # 音频配置
        if samplerate not in [8000, 16000]:
            print("⚠️  采样率必须是8000或16000Hz，已自动调整为16000Hz")
            samplerate = 16000
        self.samplerate = samplerate
        
        # 音频格式和块大小
        self.audio_format = "pcm"
        self.block_size = 3200  # 每块音频帧数
        
        # 录音超时时间（秒）
        self.recording_timeout = 15
        
        # 音频队列和录音状态
        self.audio_queue = queue.Queue()
        self.is_recording = False
        self.recognition = None
        self.callback = None
        
        # 检查音频设备
        try:
            devices = sd.query_devices()
            input_devices = [d for d in devices if d['max_input_channels'] > 0]
            
            if input_devices:
                # 尝试使用第一个输入设备
                self.device_info = input_devices[0]
                print(f"🎤 音频设备: {self.device_info['name']}")
            else:
                print("⚠️ 未找到可用的音频输入设备")
                self.device_info = None
                
        except Exception as e:
            print(f"⚠️ 音频设备查询失败: {e}")
            self.device_info = None
        
        print("✅ 语音识别器初始化完成")
        print(f"📊 采样率: {samplerate}Hz")
        print(f"🔗 使用模型: {self.model_name}")
    
    def _audio_callback(self, indata, frames, time_info, status):
        """音频输入回调函数"""
        if status:
            print(f"音频状态: {status}", file=sys.stderr)
        
        # 将音频数据放入队列
        if self.is_recording and self.recognition:
            self.audio_queue.put(bytes(indata))
    
    def _create_recognition_session(self):
        """创建语音识别会话"""
        # 创建回调对象
        self.callback = VoiceRecognizerCallback()
        
        # 创建识别对象，启用语义标点
        self.recognition = Recognition(
            model=self.model_name,
            format=self.audio_format,
            sample_rate=self.samplerate,
            semantic_punctuation_enabled=True,
            callback=self.callback
        )
        
        # 启动识别
        print("🚀 启动语音识别...")
        self.recognition.start()
        
        # 等待连接就绪
        if not self.callback.connection_ready.wait(timeout=10):
            raise TimeoutError("连接服务器超时")
        
        print("✅ 识别会话创建成功")
        return True
    
    def _audio_sender_thread(self, timeout):
        """音频发送线程"""
        start_time = time.time()
        audio_data_sent = False
        
        while self.is_recording:
            # 检查超时
            if time.time() - start_time > timeout:
                print(f"\n⏱️ 录音超时（{timeout}秒）")
                break
            
            # 检查是否检测到句子结束（VAD静音检测）
            if self.callback and self.callback.sentence_end_event.is_set():
                print("\n✅ 检测到静音，结束录音")
                break
            
            # 从队列获取音频数据
            try:
                data = self.audio_queue.get(timeout=0.5)
                
                # 发送音频帧
                if self.recognition:
                    self.recognition.send_audio_frame(data)
                    audio_data_sent = True
                    
            except queue.Empty:
                # 如果长时间没有音频数据，可能是麦克风问题
                if audio_data_sent and time.time() - start_time > 2:
                    print("\n⚠️ 长时间未收到音频数据，可能麦克风已断开")
                    break
                continue
            
            # 检查是否有错误
            if self.callback and self.callback.result_event.is_set():
                break
        
        # 停止录音
        self.is_recording = False
    
    def recognize_from_microphone(self, timeout=None):
        """
        从麦克风实时识别语音
        :param timeout: 最长录音时间(秒)，如果为None则使用默认的15秒
        :return: 识别的文本
        """
        if timeout is None:
            timeout = self.recording_timeout
        
        print(f"\n🔊 实时语音识别开始 (最长录音时间: {timeout}秒)")
        print("   请开始说话，系统会自动检测语音并识别...")
        print("   说话结束后会自动停止（检测到静音）")
        
        # 重置状态
        self.is_recording = False
        
        # 检查音频设备
        if not self.device_info:
            print("❌ 没有可用的音频输入设备")
            return ""
        
        try:
            # 创建识别会话
            if not self._create_recognition_session():
                return ""
            
            # 开始录音
            self.is_recording = True
            
            # 创建音频流
            stream = sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=self.block_size,
                dtype='int16',
                channels=1,
                callback=self._audio_callback
            )
            
            # 启动音频发送线程
            sender_thread = threading.Thread(
                target=self._audio_sender_thread,
                args=(timeout,),
                daemon=True
            )
            
            # 启动音频流
            with stream:
                print("🎤 麦克风已开启，请说话...")
                sender_thread.start()
                
                # 等待音频发送线程完成
                sender_thread.join()
            
            # 停止识别
            if self.recognition:
                print("\n🛑 停止识别...")
                self.recognition.stop()
                
                # 等待识别完成
                if self.callback and not self.callback.result_event.wait(timeout=5):
                    print("⚠️  等待识别结果超时")
            
        except Exception as e:
            print(f"\n❌ 识别过程中出错: {e}")
        finally:
            # 确保停止识别
            if self.recognition:
                try:
                    self.recognition.stop()
                except:
                    pass
            
            # 清除音频队列
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break
        
        # 获取识别结果
        result_text = ""
        if self.callback:
            if self.callback.results:
                # 合并所有识别结果
                result_text = " ".join(self.callback.results)
                print(f"\n🎯 识别完成: {result_text}")
            elif self.callback.partial_result:
                result_text = self.callback.partial_result
                print(f"\n⚠️  未检测到完整句子，返回部分识别结果: {result_text}")
            else:
                print("\n⚠️  未获取到任何识别结果")
        
        return result_text.strip()


    def recognize_from_bytes(self, audio_bytes: bytes, audio_format: str = "wav") -> str:
        """
        从音频字节数据进行语音识别（用于 Web 端上传）
        
        Args:
            audio_bytes: WAV 格式的音频数据 (推荐 16kHz, 16-bit, mono PCM)
            audio_format: 音频格式 ("wav" 或 "pcm")
        
        Returns:
            识别的文本字符串
        """
        import io
        import wave
        
        # 重置状态
        self.is_recording = False
        
        try:
            # 解析音频数据
            if audio_format == "wav":
                with wave.open(io.BytesIO(audio_bytes), 'rb') as wf:
                    nchannels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    src_sample_rate = wf.getframerate()
                    pcm_data = wf.readframes(wf.getnframes())
                
                if nchannels != 1:
                    print(f"⚠️ 音频通道数: {nchannels}，仅支持单声道")
                    return ""
                if sampwidth != 2:
                    print(f"⚠️ 音频位深: {sampwidth*8}bit，仅支持16bit")
                    return ""
            else:
                pcm_data = audio_bytes
                src_sample_rate = self.samplerate
            
            # 重采样（如果需要）
            if src_sample_rate != self.samplerate:
                try:
                    import numpy as np
                    audio_array = np.frombuffer(pcm_data, dtype=np.int16)
                    new_length = int(len(audio_array) * self.samplerate / src_sample_rate)
                    if new_length > 0:
                        # 使用线性插值进行简单重采样
                        indices = np.linspace(0, len(audio_array) - 1, new_length)
                        resampled = np.interp(indices, np.arange(len(audio_array)), audio_array.astype(np.float64))
                        pcm_data = np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()
                except ImportError:
                    print(f"⚠️ 需要 numpy 进行重采样 ({src_sample_rate}Hz -> {self.samplerate}Hz)")
                    return ""
            
            print(f"📥 收到音频数据: {len(pcm_data)} bytes, {src_sample_rate}Hz")
            
            # 创建识别会话
            if not self._create_recognition_session():
                return ""
            
            # 分块发送所有音频数据
            chunk_size = self.block_size * 2  # block_size frames × 2 bytes per sample
            for i in range(0, len(pcm_data), chunk_size):
                chunk = pcm_data[i:i + chunk_size]
                if chunk and self.recognition:
                    self.recognition.send_audio_frame(chunk)
            
            # 停止识别并等待结果
            if self.recognition:
                self.recognition.stop()
                if self.callback and not self.callback.result_event.wait(timeout=10):
                    print("⚠️ 等待识别结果超时")
        
        except Exception as e:
            print(f"❌ 音频识别失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.recognition:
                try:
                    self.recognition.stop()
                except Exception:
                    pass
            
            # 清除音频队列
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break
        
        # 获取识别结果
        result_text = ""
        if self.callback:
            if self.callback.results:
                result_text = " ".join(self.callback.results)
            elif self.callback.partial_result:
                result_text = self.callback.partial_result
        
        print(f"🎯 识别结果: {result_text}" if result_text else "⚠️ 未获取到识别结果")
        return result_text.strip()


def test_audio_devices():
    """测试音频设备"""
    print("=== 音频设备测试 ===")
    try:
        devices = sd.query_devices()
        print(f"发现 {len(devices)} 个音频设备:")
        
        input_devices = []
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                input_devices.append((i, device))
                print(f"  [{i}] {device['name']}")
        
        if not input_devices:
            print("⚠️ 未找到可用的音频输入设备")
        else:
            print(f"✅ 找到 {len(input_devices)} 个音频输入设备")
            
        return len(input_devices) > 0
    except Exception as e:
        print(f"❌ 音频设备查询失败: {e}")
        return False


if __name__ == "__main__":
    try:
        # 使用示例 - 与原始代码完全相同的调用方式
        print("=== 语音识别模块启动 ===")
        
        # 检查API Key
        if not hasattr(dashscope, 'api_key') or not dashscope.api_key:
            print("\n❌ DashScope API Key未设置")
            print("请确保config.py中正确设置了Qwen_API_KEY")
            sys.exit(1)
        
        # 测试音频设备
        has_audio_input = test_audio_devices()
        
        if not has_audio_input:
            print("\n❌ 没有可用的音频输入设备，无法继续")
            sys.exit(1)
        
        # 初始化识别器（与原始代码调用方式完全相同）
        recognizer = VoiceRecognizer()
        
        # 麦克风实时识别测试
        print("\n=== 麦克风实时识别测试 ===")
        
        # 可选：自定义超时时间
        # text = recognizer.recognize_from_microphone(timeout=20)
        
        # 使用默认超时时间（15秒）
        text = recognizer.recognize_from_microphone()
        
        print(f"\n🎯 最终识别结果: {text}")
        
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()