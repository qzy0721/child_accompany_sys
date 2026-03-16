#tts.py

import pyaudio
import threading
import time
import numpy as np
import torch
import torchaudio
from config import INDEX_TTS_MODEL_DIR, INDEX_TTS_CONFIG_PATH, TTS_SAMPLE_RATE
from indextts.infer import IndexTTS   # pyright: ignore[reportMissingImports]

class IndexTTSClient:
    def __init__(self, reference_audio_path):
        # 初始化IndexTTS模型
        self.tts = IndexTTS(
            model_dir=INDEX_TTS_MODEL_DIR,
            cfg_path=INDEX_TTS_CONFIG_PATH
        )
        # 使用传入的参考音频
        self.reference_audio = reference_audio_path
        
        self.audio_queue = []
        self.is_playing = False
        self.play_thread = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        
        # 初始化音频播放器
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=TTS_SAMPLE_RATE,
            output=True,
            frames_per_buffer=1024
        )
    
    def synthesize(self, text):
        """合成文本为语音并加入播放队列"""
        if not text.strip():
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

    def close(self):
        """释放资源"""
        self.stop_playback()
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()
