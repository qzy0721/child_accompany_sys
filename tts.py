#tts.py

import os
import io
import wave
import pyaudio
import threading
import time
import numpy as np
import torch
import torchaudio
from typing import Optional
from config import INDEX_TTS_MODEL_DIR, INDEX_TTS_CONFIG_PATH, TTS_SAMPLE_RATE, TTS_TEMP_DIR
from indextts.infer import IndexTTS   # pyright: ignore[reportMissingImports]

class IndexTTSClient:
    def __init__(self, reference_audio_path):
        """
        初始化 TTS 客户端（懒加载模式）
        - 构造函数仅存储配置，不加载模型
        - 模型在首次调用 synthesize() 时按需加载
        """
        # 仅存储配置参数，不立即加载模型
        self.reference_audio = reference_audio_path
        
        # 懒加载标志
        self._initialized = False
        self.tts = None
        self.p = None
        self.stream = None
        
        self.audio_queue = []
        self.is_playing = False
        self.play_thread = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        
        self._init_event = threading.Event()  # 模型加载完成事件
    
    def _ensure_initialized(self) -> bool:
        """
        确保 TTS 模型已初始化（懒加载入口）
        只有第一次调用 synthesize() 时才会触发模型加载。
        
        Returns:
            bool: 初始化是否成功
        """
        if self._initialized:
            return True
        
        # 防止多线程重复初始化
        if self._init_event.is_set():
            # 另一个线程正在初始化，等待完成
            self._init_event.wait()
            return self._initialized
        
        try:
            print("🔊 正在加载语音合成模型（IndexTTS）...")
            
            # 加载 IndexTTS 模型（最耗时步骤）
            self.tts = IndexTTS(
                model_dir=INDEX_TTS_MODEL_DIR,
                cfg_path=INDEX_TTS_CONFIG_PATH
            )
            
            # 初始化音频播放器
            self.p = pyaudio.PyAudio()
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=TTS_SAMPLE_RATE,
                output=True,
                frames_per_buffer=1024
            )
            
            self._initialized = True
            print("✅ 语音合成模型加载完成")
            
        except Exception as e:
            print(f"❌ TTS 模型加载失败: {e}")
            self._initialized = False
        finally:
            self._init_event.set()
        
        return self._initialized
    
    def synthesize(self, text):
        """合成文本为语音并加入播放队列"""
        if not text.strip():
            return
        
        # 懒加载：首次调用时才初始化模型
        if not self._ensure_initialized():
            print("⚠️ TTS 模型未就绪，跳过语音合成")
            return
        
        try:
            # 使用IndexTTS合成语音
            result = self.tts.infer(
                audio_prompt=self.reference_audio, 
                text=text,
                output_path=None,  
                verbose=False,
                max_text_tokens_per_sentence=100,
            )
            
            # 根据返回类型处理结果
            if isinstance(result, tuple) and len(result) == 2:
                # 返回格式为 (采样率, 音频数据)
                sr, wav_data = result
            elif isinstance(result, str):
                # 返回的是文件路径
                wav_data, sr = torchaudio.load(result)
                wav_data = wav_data.numpy()[0]  
            else:
                raise ValueError(f"Unexpected return type from infer_fast: {type(result)}")
            
            # 确保音频数据是int16类型
            wav_data = wav_data.astype(np.int16)
            
            # 如果需要重采样
            if sr != TTS_SAMPLE_RATE:
                wav_tensor = torch.from_numpy(wav_data).float().unsqueeze(0)
                resampler = torchaudio.transforms.Resample(
                    orig_freq=sr, 
                    new_freq=TTS_SAMPLE_RATE
                )
                wav_tensor = resampler(wav_tensor)
                wav_data = wav_tensor.squeeze().numpy().astype(np.int16)
            
            # 将音频数据加入队列
            with self.lock:
                self.audio_queue.append(wav_data)
            
            # 如果没有在播放，启动播放线程
            if not self.is_playing:
                self.start_playback()
        
        except Exception as e:
            print(f"TTS合成失败: {e}")
            import traceback
            traceback.print_exc()

    def start_playback(self):
        """启动音频播放线程"""
        if self.is_playing:
            return
            
        self.is_playing = True
        self.stop_event.clear()
        
        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join()
            
        self.play_thread = threading.Thread(target=self._play_audio)
        self.play_thread.daemon = True
        self.play_thread.start()

    def _play_audio(self):
        """内部方法：播放音频队列中的内容"""
        while self.is_playing and not self.stop_event.is_set():
            with self.lock:
                if not self.audio_queue:
                    self.is_playing = False
                    break
                
                audio_data = self.audio_queue.pop(0)
            
            # 将音频数据转换为字节
            audio_bytes = audio_data.tobytes()
            
            # 分块播放音频
            chunk_size = 1024
            for i in range(0, len(audio_bytes), chunk_size):
                if self.stop_event.is_set():
                    break
                chunk = audio_bytes[i:i+chunk_size]
                self.stream.write(chunk)
        
        # 清空队列
        with self.lock:
            self.audio_queue.clear()

    def stop_playback(self):
        """停止所有播放"""
        self.stop_event.set()
        with self.lock:
            self.audio_queue.clear()
        
        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join(timeout=0.5)
        
        self.is_playing = False

    def synthesize_to_bytes(self, text: str) -> Optional[bytes]:
        """
        合成语音并返回 WAV 字节（用于 Web 端播放，不通过 PyAudio）
        
        Args:
            text: 要合成的文本
        
        Returns:
            WAV 格式的音频字节，失败返回 None
        """
        if not text.strip():
            return None
        
        if not self._ensure_initialized():
            print("⚠️ TTS 模型未就绪，跳过语音合成")
            return None
        
        try:
            result = self.tts.infer(
                audio_prompt=self.reference_audio, 
                text=text,
                output_path=None,  
                verbose=False,
                max_text_tokens_per_sentence=100,
            )
            
            # 根据返回类型处理结果
            if isinstance(result, tuple) and len(result) == 2:
                sr_val, wav_data = result
            elif isinstance(result, str):
                wav_data, sr_val = torchaudio.load(result)
                wav_data = wav_data.numpy()[0]  
            else:
                raise ValueError(f"Unexpected return type from infer: {type(result)}")
            
            # 确保音频数据是int16类型
            wav_data = wav_data.astype(np.int16)
            
            # 如果需要重采样
            if sr_val != TTS_SAMPLE_RATE:
                wav_tensor = torch.from_numpy(wav_data).float().unsqueeze(0)
                resampler = torchaudio.transforms.Resample(
                    orig_freq=sr_val, 
                    new_freq=TTS_SAMPLE_RATE
                )
                wav_tensor = resampler(wav_tensor)
                wav_data = wav_tensor.squeeze().numpy().astype(np.int16)
            
            # 转换为 WAV 字节
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(TTS_SAMPLE_RATE)
                wf.writeframes(wav_data.tobytes())
            
            return buffer.getvalue()
        
        except Exception as e:
            print(f"TTS合成失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def save_to_temp(self, text: str) -> Optional[str]:
        """
        合成语音并保存到临时文件，返回文件路径。
        用于 NiceGUI 通过 URL 提供音频文件。
        
        Args:
            text: 要合成的文本
        
        Returns:
            临时文件路径，失败返回 None
        """
        wav_bytes = self.synthesize_to_bytes(text)
        if wav_bytes is None:
            return None
        
        os.makedirs(TTS_TEMP_DIR, exist_ok=True)
        
        import uuid
        filename = f"tts_{uuid.uuid4().hex[:8]}.wav"
        filepath = os.path.join(TTS_TEMP_DIR, filename)
        
        with open(filepath, 'wb') as f:
            f.write(wav_bytes)
        
        return filepath

    def close(self):
        """释放资源"""
        self.stop_playback()
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.p:
            self.p.terminate()
