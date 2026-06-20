
"""
儿童陪伴智能助手 — NiceGUI 版本
现代化 Web 界面，支持浏览器端语音输入和 TTS 音频播放。

启动方式:
    python gui_nice.py
    然后打开浏览器访问 http://localhost:8080
"""

import os
import asyncio
import queue
import threading
import base64
import re
import sys
import os
import json
from typing import Optional

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nicegui import ui, app
from config import (
    SYSTEM_PROMPT, MAX_HISTORY, MAX_BUFFER_LENGTH,
    HISTORY_FILE, SYSTEM_PROMPT_FILE, REFERENCE_AUDIO_PATH,
    TTS_TEMP_DIR, LOGGER_PATH,
)
from api import call_qwen_stream
from MemoryGenerate import MemoryGenerate
from PromptOptimizer import PromptOptimizer
from logger import Logger

# ============================================================
# 日志初始化
# ============================================================
_logger = Logger(LOGGER_PATH)
sys.stdout = _logger
sys.stderr = _logger

# ============================================================
# 类型占位符（模块级初始化以支持 global 声明）
# ============================================================
IndexTTSClient = None
VoiceRecognizer = None

# ============================================================
# 全局应用状态
# ============================================================

class AppState:
    """应用全局状态（所有用户共享）"""
    def __init__(self):
        self.messages: list = []
        self.current_role: str = "熊大"
        self.interaction_count: int = 0
        self.tts_client = None
        self.voice_recognizer = None
        self.memory_generator: Optional[MemoryGenerate] = None
        self.roles: list = ["熊大"]  # 基础角色，后台初始化后从 JSON 加载覆盖
        self._memory_ready: bool = False
        self._audio_ready: bool = False
        self._tts_loading: bool = False
        self._tts_ready: bool = False

state = AppState()

# ============================================================
# 辅助函数
# ============================================================

def split_tts_buffer(buffer: str) -> tuple:
    """
    对缓冲区内容按句子分割。
    返回: (待播放句子列表, 剩余缓冲区)
    不执行实际的 TTS 合成——由调用方异步处理。
    """
    sentences = re.split(r'(?<=[.!?。！？])', buffer)
    if len(sentences) > 1:
        to_speak = [s.strip() for s in sentences[:-1] if s.strip()]
        return to_speak, sentences[-1]
    
    if len(buffer) >= MAX_BUFFER_LENGTH:
        return [buffer[:MAX_BUFFER_LENGTH].strip()], buffer[MAX_BUFFER_LENGTH:]
    
    return [], buffer


async def play_tts_web(text: str):
    """
    合成语音并推送到浏览器音频队列（按序播放，不重叠）。
    合成在 thread pool 中运行，不阻塞事件循环。
    """
    if not state._tts_ready or not state.tts_client or not text.strip():
        return
    
    try:
        # CPU 密集型合成放到线程池，避免阻塞事件循环
        wav_bytes = await asyncio.to_thread(state.tts_client.synthesize_to_bytes, text)
        if wav_bytes:
            b64 = base64.b64encode(wav_bytes).decode('utf-8')
            # 推送到浏览器端的音频队列（JS 端逐个顺序播放）
            ui.run_javascript(f'window.enqueueTTS && window.enqueueTTS("{b64}")')
    except Exception as e:
        print(f"TTS 播放失败: {e}")


def construct_system_prompt(role_name: str) -> str:
    """构建指定角色的系统提示词（含长期记忆）"""
    prompt = PromptOptimizer.get_prompt_by_role(role_name)
    if not prompt:
        prompt = SYSTEM_PROMPT
    
    if state.memory_generator:
        try:
            memories = state.memory_generator.get_memories(limit=5)
            if memories:
                memory_text = "\n\n【长期记忆】\n" + "\n".join(
                    f"- {m['content']}" for m in memories
                )
                prompt += memory_text
        except Exception:
            pass
    
    return prompt


def save_history():
    """保存对话历史到文件"""
    history = [m for m in state.messages if m['role'] in ('user', 'assistant')]
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存历史失败: {e}")


def load_history():
    """从文件加载对话历史"""
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
        state.messages.extend(history[-MAX_HISTORY * 2:])
    except (FileNotFoundError, json.JSONDecodeError):
        pass


# ============================================================
# 异步流式 AI 响应包装器
# ============================================================

async def async_qwen_stream(messages):
    """将同步 call_qwen_stream 包装为异步生成器，不阻塞事件循环"""
    q: queue.Queue = queue.Queue()
    error_holder: list = []
    
    def runner():
        try:
            for chunk in call_qwen_stream(messages):
                q.put(('chunk', chunk))
            q.put(('done', None))
        except Exception as e:
            error_holder.append(e)
            q.put(('error', str(e)))
    
    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    
    while True:
        try:
            msg_type, data = q.get(timeout=0.05)
        except queue.Empty:
            await asyncio.sleep(0.01)
            continue
        
        if msg_type == 'chunk':
            yield data
        elif msg_type == 'done':
            break
        elif msg_type == 'error':
            if error_holder:
                raise error_holder[0]
            raise RuntimeError(data)


# ============================================================
# 后台初始化
# ============================================================

def _ensure_system_prompt_file() -> list:
    """确保 system_prompt.json 存在，首次运行时自动创建。
    返回角色名称列表。
    """
    import json as _json
    from datetime import datetime as _datetime

    if os.path.exists(SYSTEM_PROMPT_FILE):
        try:
            with open(SYSTEM_PROMPT_FILE, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            if isinstance(data, list) and len(data) > 0:
                return [entry['role_name'] for entry in data if 'role_name' in entry]
        except (_json.JSONDecodeError, KeyError):
            print("⚠️ system_prompt.json 损坏，将重新创建")

    # 文件不存在或损坏 — 用 config.py 的基础数据创建
    print("📝 首次运行，创建 system_prompt.json ...")
    default_entry = {
        "role_name": "熊大",
        "system_prompt": SYSTEM_PROMPT,
        "reference_audio_path": REFERENCE_AUDIO_PATH,
        "timestamp": _datetime.now().isoformat()
    }
    with open(SYSTEM_PROMPT_FILE, 'w', encoding='utf-8') as f:
        _json.dump([default_entry], f, ensure_ascii=False, indent=2)
    print("system_prompt.json 已创建（熊大）")
    return ["熊大"]


async def background_init():
    """后台加载重量级组件（TTS 模型、语音识别、记忆模块、角色列表）"""
    global IndexTTSClient, VoiceRecognizer
    
    print("🚀 开始后台初始化...")
    
    # 1. 加载角色列表（轻量，IO 操作）
    #    首次运行时自动创建 system_prompt.json
    try:
        state.roles = _ensure_system_prompt_file()
        if state.current_role not in state.roles and state.roles:
            state.current_role = state.roles[0]
        print(f"角色列表加载完成: {state.roles}")
    except Exception as e:
        print(f"⚠️ 角色列表加载失败: {e}")
        state.roles = ["熊大"]
    
    # 2. 初始化记忆模块
    try:
        state.memory_generator = MemoryGenerate()
        state._memory_ready = True
        print("记忆模块就绪")
    except Exception as e:
        print(f"⚠️ 记忆模块初始化失败: {e}")
    
    # 3. 初始化语音识别（DashScope）
    try:
        from sr import VoiceRecognizer as _SR
        VoiceRecognizer = _SR
        state.voice_recognizer = VoiceRecognizer()
        state._audio_ready = True
        print("语音识别模块就绪")
    except Exception as e:
        print(f"⚠️ 语音识别初始化失败: {e}")
    
    # 4. 异步加载 TTS 模型（最耗时，在 thread pool 中运行）
    try:
        from tts import IndexTTSClient as _TTS
        IndexTTSClient = _TTS
        
        # 获取当前角色的参考音频
        ref_audio = PromptOptimizer.get_reference_audio_by_role(state.current_role)
        if not ref_audio:
            ref_audio = REFERENCE_AUDIO_PATH
        
        state.tts_client = IndexTTSClient(ref_audio)
        
        # 在 thread pool 中加载模型（5-20 秒，不阻塞）
        print("🔊 正在后台加载语音合成模型...")
        success = await asyncio.to_thread(state.tts_client._ensure_initialized)
        state._tts_ready = success
        state._tts_loading = False
        
        if success:
            print("语音合成模型加载完成")
        else:
            print("⚠️ 语音合成模型加载失败")
    except Exception as e:
        print(f"⚠️ TTS 初始化失败: {e}")
        state._tts_loading = False
    
    print("后台初始化完成")


async def reload_tts_for_role(role_name: str):
    """切换角色时重新加载 TTS（异步）"""
    if state._tts_loading:
        return
    
    state._tts_loading = True
    state._tts_ready = False
    
    try:
        if state.tts_client:
            try:
                state.tts_client.close()
            except Exception:
                pass
        
        ref_audio = PromptOptimizer.get_reference_audio_by_role(role_name)
        if not ref_audio:
            ref_audio = REFERENCE_AUDIO_PATH
        
        if IndexTTSClient is None:
            from tts import IndexTTSClient as _TTS
            globals()['IndexTTSClient'] = _TTS
        
        state.tts_client = IndexTTSClient(ref_audio)
        success = await asyncio.to_thread(state.tts_client._ensure_initialized)
        state._tts_ready = success
    except Exception as e:
        print(f"⚠️ 切换角色 TTS 失败: {e}")
    finally:
        state._tts_loading = False


# ============================================================
# API 端点 — 语音识别
# ============================================================

def register_api_routes():
    """注册自定义 FastAPI 路由（语音识别端点）"""
    from fastapi import UploadFile, File
    from fastapi.responses import JSONResponse
    
    async def speech_to_text(audio: UploadFile = File(...)):
        """接收浏览器上传的音频 WAV，返回 DashScope ASR 识别文本"""
        if not state.voice_recognizer:
            return JSONResponse(
                {'text': '', 'error': '语音识别模块未初始化'}, 
                status_code=503
            )
        
        try:
            audio_bytes = await audio.read()
            text = await asyncio.to_thread(
                state.voice_recognizer.recognize_from_bytes,
                audio_bytes,
                'wav'
            )
            return {'text': text}
        except Exception as e:
            print(f"语音识别 API 错误: {e}")
            return JSONResponse(
                {'text': '', 'error': str(e)}, 
                status_code=500
            )
    
    app.add_api_route(
        '/api/speech-to-text',
        speech_to_text,
        methods=['POST'],
        response_model=None,
    )
    print("API 路由已注册: POST /api/speech-to-text")


# ============================================================
# 主页面
# ============================================================

@ui.page('/')
def chat_page():
    """主聊天页面"""
    
    # ----- 注入自定义 JavaScript -----
    ui.add_head_html('<script src="/static/js/audio_recorder.js"></script>')
    
    # ----- 浏览器端 TTS 音频队列（顺序播放，不重叠）-----
    ui.add_head_html('''
        <script>
        (function() {
            const queue = [];
            let playing = false;
            
            function playNext() {
                if (queue.length === 0) { playing = false; return; }
                playing = true;
                const b64 = queue.shift();
                const audio = new Audio("data:audio/wav;base64," + b64);
                audio.onended = playNext;
                audio.onerror = playNext;
                audio.play().catch(playNext);
            }
            
            window.enqueueTTS = function(b64) {
                queue.push(b64);
                if (!playing) playNext();
            };
        })();
        </script>
    ''')
    
    # ================ 自定义样式（儿童友好设计系统）================
    ui.add_head_html('''
        <!-- Material Icons -->
        <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
        <!-- Google Font: 圆体/可爱风格中文字体 -->
        <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --primary: #FF6B6B;
                --primary-dark: #EE5A5A;
                --primary-light: #FFE0E0;
                --secondary: #4ECDC4;
                --accent: #FFE66D;
                --bg: #FFF5F5;
                --surface: #FFFFFF;
                --text: #2D3436;
                --text-secondary: #636E72;
                --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
                --shadow-md: 0 4px 16px rgba(0,0,0,0.08);
                --shadow-lg: 0 8px 32px rgba(0,0,0,0.10);
                --radius-sm: 10px;
                --radius-md: 16px;
                --radius-lg: 24px;
                --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            }
            
            * { font-family: 'Noto Sans SC', -apple-system, 'Microsoft YaHei', sans-serif; font-size: 15px; }
            
            body {
                background: linear-gradient(160deg, #FFF5F5 0%, #FFF0E6 30%, #FFFAF0 60%, #F0FFF4 100%);
                background-attachment: fixed;
                min-height: 100vh;
            }
            /* 隐藏 select 下拉箭头图标 */
            .q-select__dropdown-icon { display: none !important; }
            
            /* === Header === */
            .app-header {
                background: linear-gradient(135deg, #e55c5c 0%, #e57050 50%, #e88a40 100%) !important;
                box-shadow: 0 2px 16px rgba(200, 70, 70, 0.3);
            }
            
            /* === Chat Bubbles === */
            .q-message {
                margin-bottom: 12px;
                animation: fadeInUp 0.3s ease-out;
            }
            .q-message[aria-label*="你"] .q-message-text {
                background: linear-gradient(135deg, #FF6B6B, #FF8E6E) !important;
                color: white !important;
                border-radius: 18px 18px 4px 18px !important;
                box-shadow: var(--shadow-sm);
            }
            .q-message:not([aria-label*="你"]) .q-message-text {
                background: #FFFFFF !important;
                border-radius: 18px 18px 18px 4px !important;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);
                border: 1px solid #F0F0F0;
            }
            .q-message-name {
                font-weight: 600 !important;
                font-size: 0.9em !important;
                color: var(--text-secondary) !important;
            }
            .q-message-text {
                font-size: 15px !important;
            }
            
            /* === Buttons === */
            .btn-send {
                background: linear-gradient(135deg, #FF6B6B, #FF8E6E) !important;
                border-radius: 14px !important;
                box-shadow: 0 4px 14px rgba(255, 107, 107, 0.3);
                transition: all var(--transition);
            }
            .btn-send:hover {
                transform: translateY(-1px);
                box-shadow: 0 6px 20px rgba(255, 107, 107, 0.4);
            }
            
            /* === Input === */
            .chat-input textarea {
                border-radius: 16px !important;
                border: 2px solid #F0E0E0 !important;
                background: var(--surface) !important;
                transition: all var(--transition);
                padding: 12px 16px !important;
                font-size: 15px !important;
            }
            .chat-input textarea:focus {
                border-color: var(--primary) !important;
                box-shadow: 0 0 0 3px rgba(255, 107, 107, 0.1);
            }
            
            /* === Status Bar === */
            .status-pill {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                padding: 3px 10px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 500;
            }
            .status-ready { background: #E8F5E9; color: #2E7D32; }
            .status-loading { background: #FFF3E0; color: #E65100; }
            .status-pending { background: #F5F5F5; color: #9E9E9E; }
            
            /* === Animations === */
            @keyframes fadeInUp {
                from { opacity: 0; transform: translateY(12px); }
                to   { opacity: 1; transform: translateY(0); }
            }
            @keyframes pulse-dot {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.4; }
            }
            .typing-dot {
                animation: pulse-dot 1.4s infinite;
            }
            .typing-dot:nth-child(2) { animation-delay: 0.2s; }
            .typing-dot:nth-child(3) { animation-delay: 0.4s; }
            
            /* === Scrollbar === */
            ::-webkit-scrollbar { width: 6px; }
            ::-webkit-scrollbar-track { background: transparent; }
            ::-webkit-scrollbar-thumb {
                background: #E0D0D0;
                border-radius: 3px;
            }
            ::-webkit-scrollbar-thumb:hover { background: #D0C0C0; }
            
            /* === Mobile Responsive === */
            @media (max-width: 600px) {
                .app-header .q-toolbar__title { font-size: 1rem !important; }
                .hide-mobile { display: none !important; }
            }
        </style>
    ''')
    
    # ===================== 页面状态 =====================
    # 使用局部变量存储 UI 元素引用
    ui_elements = {
        'chat_area': None,
        'input_text': None,
        'send_btn': None,
        'voice_btn': None,
        'memory_btn': None,
        'clear_btn': None,
        'role_select': None,
        'new_role_btn': None,
        'status_label': None,
        'tts_spinner': None,
        'is_processing': False,
    }
    
    # ===================== HEADER =====================
    with ui.header(elevated=True).classes('app-header'):
        with ui.row().classes('items-center w-full gap-2 px-3 py-1'):
            # Logo + 标题
            ui.label('儿童陪伴智能助手').classes('text-h5 text-white').style('font-weight: 700;')
            ui.space()
            
            # 角色选择器
            role_select = ui.select(
                options=state.roles,
                value=state.current_role,
                label='当前角色',
                on_change=lambda e: on_role_change(e.value)
            ).classes('w-40').props('dense outlined dark rounded hide-dropdown-icon')
            ui_elements['role_select'] = role_select
            
            # 新角色按钮
            new_role_btn = ui.button(
                '+ 新角色',
                on_click=lambda: show_new_role_dialog(),
            ).props('size=sm rounded').style('background: white; color: #e55c5c; font-weight: 600')
            ui_elements['new_role_btn'] = new_role_btn
    
    # ===================== CHAT AREA =====================
    chat_container = ui.column().classes('w-full max-w-3xl mx-auto px-4 py-2')
    ui_elements['chat_area'] = chat_container
    
    # ===================== INPUT AREA (浮动设计) =====================
    with ui.footer().classes('bg-transparent'):
        with ui.card().classes('w-full max-w-3xl mx-auto mb-2 shadow-lg rounded-2xl no-shadow'):
            with ui.column().classes('w-full gap-2 p-3'):
                # 输入框
                input_text = ui.textarea(
                    placeholder='输入你的消息...',
                ).classes('chat-input flex-grow w-full').props('outlined rows=2 dense clearable autogrow')
                ui_elements['input_text'] = input_text
                
                # 按钮行
                with ui.row().classes('w-full items-center gap-2'):
                    ui.space()
                    
                    voice_btn = ui.button(
                        '🎤', color='blue-5',
                        on_click=lambda: on_voice_clicked()
                    ).props('rounded glossy size=md')
                    ui_elements['voice_btn'] = voice_btn
                    
                    memory_btn = ui.button(
                        '🧠', color='purple-5',
                        on_click=lambda: on_memory_clicked()
                    ).props('rounded glossy size=md')
                    ui_elements['memory_btn'] = memory_btn
                    
                    clear_btn = ui.button(
                        '清空', color='grey-5',
                        on_click=lambda: on_clear_clicked()
                    ).props('rounded flat size=md')
                    ui_elements['clear_btn'] = clear_btn
                    
                    send_btn = ui.button(
                        '发送',
                        on_click=lambda: on_send_clicked()
                    ).classes('btn-send').props('size=md rounded glossy')
                    ui_elements['send_btn'] = send_btn
        
        # 状态栏（胶囊式）
        with ui.row().classes('w-full justify-center pb-2'):
            status_label = ui.html('').classes('text-caption')
            ui_elements['status_label'] = status_label
    
    # ===================== 状态更新定时器 =====================
    def update_status():
        """定时更新状态栏 — 胶囊式状态指示"""
        parts = []
        parts.append('<span class="status-pill status-ready">聊天就绪</span>')
        if state._audio_ready:
            parts.append('<span class="status-pill status-ready">语音就绪</span>')
        else:
            parts.append('<span class="status-pill status-pending">语音加载中</span>')
        if state._tts_ready:
            parts.append('<span class="status-pill status-ready">语音合成就绪</span>')
        elif state._tts_loading:
            parts.append('<span class="status-pill status-loading">语音合成加载中</span>')
        else:
            parts.append('<span class="status-pill status-pending">语音合成待机</span>')
        
        ui_elements['status_label'].set_content(' '.join(parts))
    
    ui.timer(2.0, update_status)
    
    def sync_role_options():
        """定时同步角色下拉框选项（后台初始化完成后会更新 state.roles）"""
        current = state.roles
        if current and ui_elements['role_select'].options != current:
            ui_elements['role_select'].set_options(current)
    
    ui.timer(1.0, sync_role_options)
    
    # ===================== 核心功能函数 =====================
    
    async def on_send_clicked():
        """发送消息"""
        if ui_elements['is_processing']:
            ui.notify('请等待当前回复完成', type='warning')
            return
        
        user_text = ui_elements['input_text'].value.strip()
        if not user_text:
            return
        
        # 清空输入框
        ui_elements['input_text'].value = ''
        
        # 显示用户消息
        with chat_container:
            ui.chat_message(text=user_text, name='你', sent=True)
        
        # 添加到消息列表
        state.messages.append({'role': 'user', 'content': user_text})
        
        # 开始处理
        ui_elements['is_processing'] = True
        ui_elements['send_btn'].disable()
        
        await stream_ai_response()
        
        ui_elements['send_btn'].enable()
        ui_elements['is_processing'] = False
    
    
    async def stream_ai_response():
        """流式获取 AI 响应并实时更新"""
        from nicegui.elements.html import Html
        
        # 创建助手消息气泡
        with chat_container:
            msg_element = ui.chat_message(
                text='思考中...',
                name=state.current_role,
                sent=False
            )
        
        full_response = ""
        buffer = ""
        chunk_count = 0
        
        def _update_msg(text: str):
            """更新 chatbot 消息内容（clear + rebuild）"""
            msg_element.clear()
            with msg_element:
                Html(text.replace('\n', '<br />'), sanitize=False)
        
        try:
            async for chunk in async_qwen_stream(state.messages):
                # 过滤不可打印字符
                clean = ''.join(c for c in chunk if c.isprintable() or c in '\n')
                if not clean:
                    continue
                
                full_response += clean
                buffer += clean
                chunk_count += 1
                
                # 每 3 个 chunk 更新一次 UI，避免过于频繁的 DOM 操作
                if chunk_count % 3 == 0:
                    _update_msg(full_response)
                
                # 分句 TTS（异步，不阻塞）
                sentences, buffer = split_tts_buffer(buffer)
                for sentence in sentences:
                    await play_tts_web(sentence)
            
            # 最终更新
            _update_msg(full_response if full_response else '(无响应)')
            
            # 播放剩余缓冲
            if buffer.strip():
                await play_tts_web(buffer.strip())
            
            # 保存到消息列表和历史
            state.messages.append({'role': 'assistant', 'content': full_response})
            save_history()
            
            # 自动记忆生成（每 3 次交互）
            state.interaction_count += 1
            if state.interaction_count % 3 == 0 and state._memory_ready:
                asyncio.create_task(auto_generate_memory())
        
        except Exception as e:
            _update_msg(f'出错了: {str(e)}')
            print(f"AI 响应错误: {e}")
    
    
    async def on_voice_clicked():
        """语音输入按钮点击"""
        if ui_elements['is_processing']:
            ui.notify('请等待当前回复完成', type='warning')
            return
        
        if not state._audio_ready:
            ui.notify('语音识别模块尚未就绪，请稍候', type='warning')
            return
        
        ui_elements['voice_btn'].disable()
        ui.notify('正在聆听...', type='info', position='top', timeout=8000)
        
        try:
            # 调用浏览器录音
            text = await ui.run_javascript(
                'return recordAudio(8);',
                timeout=15.0
            )
            
            if text and text.strip():
                # 将识别结果填入输入框并自动发送
                ui_elements['input_text'].value = text.strip()
                await on_send_clicked()
            else:
                ui.notify('未识别到语音内容，请重试', type='warning')
        except asyncio.TimeoutError:
            ui.notify('录音超时，请重试', type='warning')
        except Exception as e:
            print(f"语音输入错误: {e}")
            ui.notify(f'语音输入失败: {str(e)}', type='negative')
        finally:
            ui_elements['voice_btn'].enable()
    
    
    def on_memory_clicked():
        """手动触发记忆生成"""
        if not state._memory_ready:
            ui.notify('记忆模块尚未就绪', type='warning')
            return
        
        ui_elements['memory_btn'].disable()
        
        async def do_memory():
            try:
                result = await asyncio.to_thread(
                    state.memory_generator.generate_memory,
                    max_history_messages=10
                )
                if result:
                    ui.notify(f'记忆已生成: {result[:50]}...', type='positive')
                else:
                    ui.notify('⚠️ 记忆生成失败或无可提取内容', type='warning')
            except Exception as e:
                ui.notify(f'记忆生成失败: {str(e)}', type='negative')
            finally:
                ui_elements['memory_btn'].enable()
        
        ui.timer(0.01, do_memory, once=True)  # timer 回调保留 slot 上下文
    
    
    async def auto_generate_memory():
        """自动记忆生成（后台静默运行）"""
        try:
            if state.memory_generator:
                await asyncio.to_thread(
                    state.memory_generator.generate_memory,
                    max_history_messages=10
                )
                print("自动记忆已更新")
        except Exception as e:
            print(f"自动记忆更新失败: {e}")
    
    
    def on_clear_clicked():
        """清空对话（带确认）"""
        async def do_clear():
            result = await ui.run_javascript('''
                return confirm("确定要清空当前对话记录吗？");
            ''', timeout=10.0)
            
            if result:
                clear_conversation_internal()
                ui.notify('对话已清空', type='info')
        
        ui.timer(0.01, do_clear, once=True)
    
    
    def clear_conversation_internal():
        """内部清空对话"""
        # 清空消息列表
        state.messages = []
        state.interaction_count = 0
        
        # 重建系统提示词
        system_prompt = construct_system_prompt(state.current_role)
        state.messages.append({'role': 'system', 'content': system_prompt})
        
        # 清空聊天显示
        chat_container.clear()
        
        # 显示问候语
        greeting = f"嘿嘿，俺是{state.current_role}！今天想跟俺聊点啥子呀？"
        with chat_container:
            ui.chat_message(text=greeting, name=state.current_role, sent=False)
        
        # 保存空的对话历史
        save_history()
    
    
    def on_role_change(new_role: str):
        """角色切换（由下拉框触发）"""
        # 防止程序化修改 value 时递归触发
        if ui_elements.get('_suppress_role_change'):
            return
        
        if new_role == state.current_role:
            return
        
        # 新角色创建后自动切换时跳过确认
        skip_confirm = ui_elements.get('_skip_role_confirm', False)
        
        async def do_switch():
            if not skip_confirm:
                # 确认对话框
                result = await ui.run_javascript(f'''
                    return confirm("切换到角色「{new_role}」吗？\\n当前对话将被清空。");
                ''', timeout=10.0)
                
                if not result:
                    # 用户取消——恢复原选择（抑制递归回调）
                    ui_elements['_suppress_role_change'] = True
                    try:
                        ui_elements['role_select'].value = state.current_role
                    finally:
                        ui_elements['_suppress_role_change'] = False
                    return
            
            state.current_role = new_role
            
            # 清空对话
            clear_conversation_internal()
            
            # 后台重新加载 TTS
            if IndexTTSClient is not None:
                asyncio.create_task(reload_tts_for_role(new_role))
            
            ui.notify(f'已切换到角色「{new_role}」', type='positive')
        
        ui.timer(0.01, do_switch, once=True)
    
    
    async def show_new_role_dialog():
        """显示新建角色对话框（两阶段：输入名称 → 上传参考音频）"""
        ui_elements['new_role_btn'].disable()
        
        with ui.dialog() as dialog, ui.card().classes('p-6 gap-3 max-w-md rounded-2xl shadow-xl'):
            with ui.row().classes('items-center gap-2'):
                ui.label('创建新角色').classes('text-h5').style('font-weight: 700;')
            
            # ===== 阶段 1：输入角色名称 =====
            phase1 = ui.column().classes('gap-2 w-full')
            with phase1:
                ui.label('请输入角色名称，AI 将自动生成角色提示词').classes('text-body2 text-grey-7')
                role_name_input = ui.input(
                    label='角色名称',
                    placeholder='例如: 喜羊羊, 奥特曼...'
                ).classes('w-full').props('autofocus outlined rounded')
            
            # ===== 阶段 2：上传参考音频（初始隐藏）=====
            phase2 = ui.column().classes('gap-2 w-full')
            phase2.set_visibility(False)
            with phase2:
                ui.label('角色提示词已生成！').classes('text-positive text-subtitle2')
                ui.label('请上传一段参考音频（WAV 格式），用于语音克隆：').classes('text-body2')
                
                upload_status = ui.label('').classes('text-caption')
                
                # 文件上传结果容器
                upload_result = {'path': None, 'name': None}
                upload_done = asyncio.Event()
                
                async def on_upload(e):
                    """接收浏览器上传的音频文件并保存"""
                    ref_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference_audio')
                    os.makedirs(ref_dir, exist_ok=True)
                    safe_name = "".join(c for c in e.file.name if c.isalnum() or c in '._-')
                    filepath = os.path.join(ref_dir, safe_name)
                    try:
                        await e.file.save(filepath)
                        upload_result['path'] = filepath
                        upload_result['name'] = e.file.name
                        upload_status.set_text(f'已选择: {e.file.name}')
                    except Exception as ex:
                        upload_status.set_text(f'保存失败: {ex}')
                
                u = ui.upload(
                    on_upload=on_upload,
                    label='点击选择 WAV 音频文件',
                    auto_upload=True,
                ).props('accept=.wav,.mp3,.m4a,.flac').classes('w-full')
                
                ui.label('或').classes('text-caption text-grey self-center')
                
                skip_audio_btn = ui.button(
                    '跳过（使用默认音频）',
                    on_click=lambda: upload_done.set(),
                    color='grey-7'
                ).props('flat')
            
            # ===== 状态 & 进度 =====
            status_msg = ui.label('').classes('text-caption text-grey')
            progress = ui.spinner(size='sm')
            progress.set_visibility(False)
            
            # ===== 阶段 1 按钮 =====
            phase1_btns = ui.row().classes('gap-2')
            with phase1_btns:
                cancel_btn = ui.button('取消', on_click=dialog.close).props('flat rounded')
                create_btn = ui.button('生成角色提示词', on_click=lambda: do_create()).props('rounded glossy').style('background: #e55c5c; color: white')
            
            # ===== 阶段 2 按钮（初始隐藏）=====
            phase2_btns = ui.row().classes('gap-2')
            phase2_btns.set_visibility(False)
            with phase2_btns:
                back_btn = ui.button('← 返回', on_click=lambda: upload_done.set()).props('flat rounded')
                save_btn = ui.button('保存角色', on_click=lambda: finish_role()).props('rounded glossy').style('background: #e55c5c; color: white')
            
            # 跨阶段共享变量
            role_data = {'optimizer': None, 'name': None}
            
            async def do_create():
                """阶段 1：生成角色提示词"""
                name = role_name_input.value.strip()
                if not name:
                    ui.notify('请输入角色名称', type='warning')
                    return
                if name in state.roles:
                    ui.notify('该角色已存在', type='warning')
                    return
                
                dialog.props('persistent')
                cancel_btn.disable()
                create_btn.disable()
                progress.set_visibility(True)
                status_msg.set_text('正在生成角色提示词...')
                
                try:
                    optimizer = PromptOptimizer(name)
                    success, prompt_text = await asyncio.to_thread(
                        optimizer.generate_optimized_prompt
                    )
                    if not success:
                        ui.notify('提示词生成失败', type='negative')
                        return
                    
                    role_data['optimizer'] = optimizer
                    role_data['name'] = name
                    
                    # 切换到阶段 2
                    phase1.set_visibility(False)
                    phase1_btns.set_visibility(False)
                    phase2.set_visibility(True)
                    phase2_btns.set_visibility(True)
                    progress.set_visibility(False)
                    status_msg.set_text('')
                    dialog.props(remove='persistent')
                    cancel_btn.enable()
                    create_btn.enable()
                    
                except Exception as e:
                    ui.notify(f'生成失败: {str(e)}', type='negative')
                    dialog.props(remove='persistent')
                    cancel_btn.enable()
                    create_btn.enable()
                    progress.set_visibility(False)
                    status_msg.set_text('')
            
            async def finish_role():
                """阶段 2：保存角色"""
                optimizer = role_data['optimizer']
                name = role_data['name']
                if optimizer is None:
                    return
                
                dialog.props('persistent')
                save_btn.disable()
                back_btn.disable()
                skip_audio_btn.disable()
                progress.set_visibility(True)
                status_msg.set_text('正在保存...')
                
                try:
                    # 等待上传完成或跳过（如果还没选文件也未跳过）
                    if upload_result['path'] is None and not upload_done.is_set():
                        upload_done.set()  # 等同于跳过
                    
                    ref_path = upload_result['path'] or REFERENCE_AUDIO_PATH
                    optimizer.set_reference_audio_path(ref_path)
                    
                    saved = await asyncio.to_thread(optimizer.save_to_json)
                    
                    if saved:
                        state.roles = PromptOptimizer.list_all_roles()
                        ui_elements['role_select'].set_options(state.roles)
                        ui_elements['_skip_role_confirm'] = True
                        try:
                            ui_elements['role_select'].value = name
                        finally:
                            ui_elements['_skip_role_confirm'] = False
                        ui.notify(f'角色「{name}」创建成功！', type='positive')
                        dialog.close()
                    else:
                        ui.notify('保存失败', type='negative')
                        
                except Exception as e:
                    ui.notify(f'保存失败: {str(e)}', type='negative')
                finally:
                    dialog.props(remove='persistent')
                    save_btn.enable()
                    back_btn.enable()
                    skip_audio_btn.enable()
                    progress.set_visibility(False)
                    status_msg.set_text('')
        
        dialog.open()
        ui_elements['new_role_btn'].enable()
    
    
    # ===================== 初始化 =====================
    def on_page_ready():
        """页面加载完成后初始化"""
        # 构建初始系统提示词
        system_prompt = construct_system_prompt(state.current_role)
        state.messages.append({'role': 'system', 'content': system_prompt})
        
        # 加载历史
        load_history()
        
        # 显示历史消息
        for msg in state.messages:
            if msg['role'] == 'user':
                with chat_container:
                    ui.chat_message(text=msg['content'], name='你', sent=True)
            elif msg['role'] == 'assistant':
                with chat_container:
                    ui.chat_message(text=msg['content'], name=state.current_role, sent=False)
        
        # 如果没有历史消息，显示问候语
        has_history = any(m['role'] == 'assistant' for m in state.messages)
        if not has_history:
            greeting = f"嘿嘿，俺是{state.current_role}！今天想跟俺聊点啥子呀？"
            with chat_container:
                ui.chat_message(text=greeting, name=state.current_role, sent=False)
        
        # 启动后台初始化（timer 回调保留 slot 上下文）
        ui.timer(0.01, safe_background_init, once=True)
    
    # 页面就绪回调
    ui.timer(0.1, on_page_ready, once=True)
    
    # 安全包装：防止后台异步任务崩溃导致整个应用退出
    async def safe_background_init():
        try:
            await background_init()
        except Exception as e:
            print(f"后台初始化失败: {e}")
            import traceback
            traceback.print_exc()


# ============================================================
# 应用启动
# ============================================================

def main():
    """启动 NiceGUI 应用"""
    # 注册自定义 API 路由
    register_api_routes()
    
    # 挂载静态文件目录
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    if os.path.exists(static_dir):
        app.add_static_files('/static', static_dir)
    
    # 挂载 TTS 临时文件目录
    tts_dir = TTS_TEMP_DIR
    os.makedirs(tts_dir, exist_ok=True)
    app.add_static_files('/tts_audio', tts_dir)
    
    print("=" * 50)
    print("🧸 儿童陪伴智能助手 — NiceGUI 版本")
    print("=" * 50)
    print(f"📁 项目路径: {os.path.dirname(os.path.abspath(__file__))}")
    print(f"🌐 启动后访问: http://localhost:8080")
    print(f"💡 核心功能立即可用，TTS 语音在后台加载")
    print("=" * 50)
    
    # 启动 NiceGUI 服务器
    ui.run(
        title='儿童陪伴智能助手',
        host='0.0.0.0',
        port=8080,
        reload=False,
        show=True,  # 自动打开浏览器
        dark=False,
    )


if __name__ in {'__main__', '__mp_main__'}:
    main()
