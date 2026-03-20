# -*- coding: UTF-8 -*-
# gui_main_optimized.py
# 性能优化版本：异步显示界面，后台加载非关键组件

# Standard Libraries
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog, filedialog
import threading
import time
import re
import json
import os
import sys

# Custom Modules
from logger import Logger
from api import call_qwen_stream
from tts import IndexTTSClient
from sr import VoiceRecognizer
from config import (
    SYSTEM_PROMPT, 
    MAX_HISTORY, 
    HISTORY_FILE, 
    Qwen_API_KEY, 
    MAX_BUFFER_LENGTH, 
    LOGGER_PATH, 
    VOSK_MODEL_PATH,
    SYSTEM_PROMPT_FILE
)

# Integration Modules
from MemoryGenerate import MemoryGenerate
from PromptOptimizer import PromptOptimizer

import dashscope

# Set DashScope API Key
dashscope.api_key = Qwen_API_KEY


class ChatApplication:
    def __init__(self, root):
        self.root = root
        self.root.title("儿童陪伴智能助手")
        self.root.geometry("900x700") 
        self.root.configure(bg='#f0f0f0')
        
        # ========== 快速初始化阶段 ==========
        # 这些是必须立即初始化的基础属性
        
        # 初始化状态标志
        self._audio_ready = False           # 音频组件是否就绪
        self._memory_ready = False          # 记忆模块是否就绪
        self._is_closing = False            # 是否正在关闭
        
        # 默认角色设置
        self.current_role_name = "熊大"
        self.available_roles = []           # 先设为空，后台加载
        
        # 音频组件占位
        self.voice_recognizer = None
        self.tts_client = None
        self.is_listening = False
        
        # 记忆模块占位
        self.memory_generator = None
        self.loaded_memories = []
        
        # 对话状态
        self.messages = []
        self.interaction_count = 0
        
        # ========== 立即显示UI ==========
        # 先设置UI组件，让用户看到界面
        self.setup_components()
        
        # 绑定事件
        self.bind_events()
        
        # 显示加载状态
        self.update_status("正在加载后台组件...")
        
        # ========== 启动后台初始化线程 ==========
        # 在后台线程中加载耗时组件
        threading.Thread(target=self._background_init, daemon=True).start()
    
    def _background_init(self):
        """后台初始化线程：加载耗时组件"""
        try:
            # Step 1: 加载角色列表（轻量级，先加载）
            if not self._is_closing:
                self._init_roles()
            
            # Step 2: 初始化记忆模块
            if not self._is_closing:
                self._init_memory_module()
            
            # Step 3: 初始化音频组件（最耗时，最后加载）
            if not self._is_closing:
                self._init_audio_module()
            
            # Step 4: 初始化对话系统
            if not self._is_closing:
                self.root.after(0, self._finalize_init)
                
        except Exception as e:
            print(f"后台初始化出错: {e}")
            self.root.after(0, lambda: self.update_status(f"初始化出错: {e}"))
    
    def _init_roles(self):
        """初始化角色列表"""
        try:
            self.available_roles = PromptOptimizer.list_all_roles(SYSTEM_PROMPT_FILE)
            # 回到主线程更新UI
            self.root.after(0, self._update_role_combobox)
        except Exception as e:
            print(f"加载角色列表失败: {e}")
            self.available_roles = [self.current_role_name]
    
    def _update_role_combobox(self):
        """更新角色下拉框（主线程）"""
        self.role_combobox['values'] = self.available_roles
        if self.current_role_name in self.available_roles:
            self.role_combobox.set(self.current_role_name)
        elif self.available_roles:
            self.role_combobox.current(0)
            self.current_role_name = self.role_combobox.get()
    
    def _init_memory_module(self):
        """初始化记忆模块"""
        try:
            self.memory_generator = MemoryGenerate()
            self.loaded_memories = self.memory_generator.get_memories(limit=5)
            self._memory_ready = True
            self.root.after(0, lambda: self.update_status("记忆模块加载完成，继续加载语音..."))
        except Exception as e:
            print(f"记忆模块初始化失败: {e}")
            self.memory_generator = None
            self.root.after(0, lambda: self.update_status(f"记忆模块加载失败: {e}"))
    
    def _init_audio_module(self):
        """初始化音频组件（语音识别和TTS）"""
        try:
            # 初始化语音识别
            try:
                self.voice_recognizer = VoiceRecognizer(model_path=VOSK_MODEL_PATH)
                self.root.after(0, lambda: self.update_status("语音识别模块加载完成"))
            except Exception as e:
                print(f"语音识别初始化失败: {e}")
                self.root.after(0, lambda: self.voice_button.config(state=tk.DISABLED, bg='gray'))
            
            # 初始化TTS
            self._init_tts_for_role_async(self.current_role_name)
            
            self._audio_ready = True
            
        except Exception as e:
            print(f"音频模块初始化失败: {e}")
    
    def _init_tts_for_role_async(self, role_name):
        """异步初始化TTS"""
        try:
            # 关闭旧的 client
            if self.tts_client and hasattr(self.tts_client, 'close'):
                self.tts_client.close()
            
            # 获取该角色的音频路径
            ref_audio_path = PromptOptimizer.get_reference_audio_by_role(role_name, SYSTEM_PROMPT_FILE)
            
            if not ref_audio_path or not os.path.exists(ref_audio_path):
                print(f"警告: 角色 '{role_name}' 没有有效的参考音频: {ref_audio_path}")
                ref_audio_path = "" 
            
            print(f"正在初始化TTS，参考音频: {ref_audio_path}")
            self.tts_client = IndexTTSClient(reference_audio_path=ref_audio_path)
            
        except Exception as e:
            print(f"TTS初始化失败 ({role_name}): {e}")
            self.tts_client = None
    
    def _finalize_init(self):
        """完成初始化（主线程）"""
        if self._is_closing:
            return
            
        # 初始化对话系统
        self.setup_conversation()
        
        # 启用按钮
        self.enable_buttons()
        
        # 更新状态
        status_parts = []
        if self._audio_ready:
            status_parts.append("语音就绪")
        if self._memory_ready:
            status_parts.append("记忆就绪")
        
        if status_parts:
            self.update_status(f"系统初始化完成 ({' | '.join(status_parts)})，等待指令...")
        else:
            self.update_status("系统初始化完成（部分功能受限），等待指令...")
    
    def setup_components(self):
        """设置UI组件"""
        # --- Top Title & Role Management Frame ---
        top_frame = tk.Frame(self.root, bg='#2E8B57', height=80)
        top_frame.pack(fill=tk.X, padx=0, pady=0)
        top_frame.pack_propagate(False)
        
        # Title
        title_label = tk.Label(
            top_frame, 
            text="儿童陪伴智能助手", 
            font=("微软雅黑", 16, "bold"), 
            fg='white', 
            bg='#2E8B57'
        )
        title_label.pack(side=tk.LEFT, padx=20)
        
        # 加载指示器（显示在标题旁边）
        self.loading_label = tk.Label(
            top_frame,
            text="⏳ 加载中...",
            font=("微软雅黑", 10),
            fg='#FFC107',
            bg='#2E8B57'
        )
        self.loading_label.pack(side=tk.LEFT, padx=10)
        
        # Role Selector Frame (Right side of top bar)
        role_frame = tk.Frame(top_frame, bg='#2E8B57')
        role_frame.pack(side=tk.RIGHT, padx=20, pady=20)
        
        tk.Label(role_frame, text="当前角色:", bg='#2E8B57', fg='white', font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=5)
        
        self.role_combobox = ttk.Combobox(role_frame, values=[], state="readonly", width=15)
        self.role_combobox.set(self.current_role_name)  # 先设置默认值
        self.role_combobox.pack(side=tk.LEFT, padx=5)
        self.role_combobox.bind("<<ComboboxSelected>>", self.on_role_change)
        
        self.new_role_btn = tk.Button(
            role_frame, 
            text="+ 新角色", 
            command=self.create_new_role_dialog,
            bg='#FFC107', 
            font=("微软雅黑", 9),
            state=tk.DISABLED  # 初始禁用，后台加载完成后启用
        )
        self.new_role_btn.pack(side=tk.LEFT, padx=5)
        
        # --- Status Bar ---
        self.status_var = tk.StringVar(value="正在初始化...")
        status_bar = tk.Label(
            self.root, 
            textvariable=self.status_var, 
            relief=tk.SUNKEN, 
            anchor=tk.W,
            font=("微软雅黑", 10),
            bg='#e0e0e0'
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # --- Main Content Area ---
        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Chat Display
        chat_frame = tk.LabelFrame(main_frame, text="对话记录", font=("微软雅黑", 11), bg='#f0f0f0')
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame, 
            wrap=tk.WORD, 
            width=80, 
            height=20,
            font=("微软雅黑", 11),
            bg='white',
            fg='#333333'
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chat_display.config(state=tk.DISABLED)
        
        # Input Area
        input_frame = tk.Frame(main_frame, bg='#f0f0f0')
        input_frame.pack(fill=tk.X, pady=5)
        
        self.input_text = tk.Text(
            input_frame, 
            height=3, 
            wrap=tk.WORD,
            font=("微软雅黑", 11),
            bg='white'
        )
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        # Buttons
        button_frame = tk.Frame(input_frame, bg='#f0f0f0')
        button_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.send_button = tk.Button(
            button_frame,
            text="发送",
            command=self.send_message,
            font=("微软雅黑", 10),
            bg='#4CAF50',
            fg='white',
            width=8,
            height=1,
            state=tk.DISABLED  # 初始禁用
        )
        self.send_button.pack(pady=2)
        
        self.voice_button = tk.Button(
            button_frame,
            text="🎤 语音",
            command=self.start_voice_input,
            font=("微软雅黑", 10),
            bg='#2196F3',
            fg='white',
            width=8,
            height=1,
            state=tk.DISABLED  # 初始禁用
        )
        self.voice_button.pack(pady=2)
        
        # 记忆按钮
        self.memory_button = tk.Button(
            button_frame,
            text="🧠 记忆",
            command=self.manual_memory_trigger,
            font=("微软雅黑", 10),
            bg='#9C27B0',
            fg='white',
            width=8,
            height=1,
            state=tk.DISABLED  # 初始禁用
        )
        self.memory_button.pack(pady=2)
        
        self.clear_button = tk.Button(
            button_frame,
            text="清空",
            command=self.clear_conversation,
            font=("微软雅黑", 10),
            bg='#FF9800',
            fg='white',
            width=8,
            height=1,
            state=tk.DISABLED  # 初始禁用
        )
        self.clear_button.pack(pady=2)

    def setup_conversation(self):
        """初始化对话系统"""
        initial_system_prompt = self._construct_system_prompt(self.current_role_name)
        self.messages = [{'role': 'system', 'content': initial_system_prompt}]
        self.load_history()
        self.add_to_display("system", self.current_role_name, f"你好，我是{self.current_role_name}")
        
        # 隐藏加载指示器
        self.loading_label.config(text="✓ 就绪", fg='#90EE90')
        
        # 启用新角色按钮
        self.new_role_btn.config(state=tk.NORMAL)

    def _construct_system_prompt(self, role_name):
        """构建系统提示词"""
        base_prompt = PromptOptimizer.get_prompt_by_role(role_name, SYSTEM_PROMPT_FILE)
        if not base_prompt:
            base_prompt = SYSTEM_PROMPT 
            
        memories_text = ""
        if self.loaded_memories:
            mem_list = [m['content'] for m in self.loaded_memories]
            memories_text = "\n\n【长期记忆】(这些是你过去的经历，请参考):\n" + "\n- ".join(mem_list)
            
        return base_prompt + memories_text

    def bind_events(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.input_text.bind("<Return>", self.on_enter_pressed)
        self.input_text.bind("<Control-Return>", self.on_ctrl_enter)

    def on_enter_pressed(self, event):
        if event.state == 0:
            self.send_message()
            return "break"
        return None
        
    def on_ctrl_enter(self, event):
        return None

    def update_status(self, message):
        """更新状态栏（线程安全）"""
        self.status_var.set(message)
        self.root.update_idletasks()

    def add_to_display(self, role, name, message):
        self.chat_display.config(state=tk.NORMAL)
        
        if role == "user":
            color = "#2E7D32"
            prefix = "你"
        elif role == "assistant":
            color = "#D84315"
            prefix = name
        else:
            color = "#1565C0"
            prefix = name 
            
        self.chat_display.insert(tk.END, f"{prefix}: ", f"bold_{role}")
        self.chat_display.insert(tk.END, f"{message}\n\n", role)
        
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)
        
        self.chat_display.tag_configure(f"bold_{role}", font=("微软雅黑", 11, "bold"), foreground=color)
        self.chat_display.tag_configure(role, font=("微软雅黑", 11), foreground=color)

    # --- Role Management Logic ---

    def on_role_change(self, event):
        selected_role = self.role_combobox.get()
        if selected_role == self.current_role_name:
            return
            
        if messagebox.askyesno("切换角色", f"确定要切换到 '{selected_role}' 吗？\n这将清空当前的对话上下文并重新加载语音配置。"):
            self.current_role_name = selected_role
            
            # 1. 清空并重置对话
            self.clear_conversation_internal(switch_role=True)
            
            # 2. 在后台线程重新初始化TTS
            self.update_status(f"正在加载 {selected_role} 的语音配置...")
            threading.Thread(target=self._init_tts_for_role_async, args=(selected_role,), daemon=True).start()
            
            self.update_status(f"角色已切换为: {selected_role}")

    def create_new_role_dialog(self):
        new_role_name = simpledialog.askstring("新建角色", "请输入新角色的名字:")
        if not new_role_name:
            return
            
        if new_role_name in self.available_roles:
            messagebox.showwarning("提示", "该角色已存在！")
            return
            
        self.update_status(f"正在为 '{new_role_name}' 生成专属人设 (Step 1/2)...")
        self.new_role_btn.config(state=tk.DISABLED)
        
        # 启动生成线程
        threading.Thread(target=self.process_new_role_prompt, args=(new_role_name,), daemon=True).start()

    def process_new_role_prompt(self, role_name):
        """Thread Step 1: Generate Prompt"""
        # 创建优化器实例
        optimizer = PromptOptimizer(role_name)
        # 只生成，先不保存
        success, prompt = optimizer.generate_optimized_prompt()
        
        # 回到主线程处理后续步骤 (选择音频 + 保存)
        self.root.after(0, self.continue_new_role_setup, success, role_name, prompt, optimizer)

    def continue_new_role_setup(self, success, role_name, prompt, optimizer):
        """Main Thread Step 2: Select Audio & Save"""
        if not success:
            self.new_role_btn.config(state=tk.NORMAL)
            messagebox.showerror("失败", f"角色 '{role_name}' 提示词生成失败: {prompt}")
            self.update_status("角色创建失败")
            return

        # 询问用户选择音频文件
        self.update_status(f"请为 '{role_name}' 选择参考音频文件 (Step 2/2)...")
        
        audio_path = filedialog.askopenfilename(
            title=f"选择 {role_name} 的参考音频 (.wav)",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")]
        )
        
        if audio_path:
            optimizer.set_reference_audio_path(audio_path)
        else:
            if not messagebox.askyesno("警告", "未选择参考音频。是否继续保存？\n(如果没有音频，TTS可能使用默认声音)"):
                self.new_role_btn.config(state=tk.NORMAL)
                self.update_status("角色创建已取消")
                return
        
        # 保存到JSON
        save_success = optimizer.save_to_json(SYSTEM_PROMPT_FILE)
        
        self.new_role_btn.config(state=tk.NORMAL)
        
        if save_success:
            self.available_roles = PromptOptimizer.list_all_roles(SYSTEM_PROMPT_FILE)
            self.role_combobox['values'] = self.available_roles
            self.role_combobox.set(role_name)
            self.current_role_name = role_name
            
            messagebox.showinfo("成功", f"角色 '{role_name}' 创建成功！\n提示词和音频配置已应用。")
            
            # 应用新角色配置
            self.clear_conversation_internal(switch_role=True)
            threading.Thread(target=self._init_tts_for_role_async, args=(role_name,), daemon=True).start()
        else:
            messagebox.showerror("错误", "保存角色配置失败")

    # --- Message Handling Logic ---

    def send_message(self):
        user_input = self.input_text.get("1.0", tk.END).strip()
        if not user_input:
            return
            
        self.input_text.delete("1.0", tk.END)
        self.add_to_display("user", "你", user_input)
        
        self.disable_buttons() 
        
        threading.Thread(target=self.process_ai_response, args=(user_input,), daemon=True).start()

    def process_ai_response(self, user_input):
        try:
            self.messages.append({'role': 'user', 'content': user_input})
            self.update_status(f"{self.current_role_name} 正在思考...")
            
            buffer = ""
            full_response = []
            qwen_stream = call_qwen_stream(self.messages)
            
            for chunk in qwen_stream:
                chunk = ''.join(c for c in chunk if c.isprintable())
                full_response.append(chunk)
                buffer += chunk
                buffer = self.process_tts_buffer(buffer)
                
            if buffer.strip():
                self.synthesize_text(buffer)
                
            ai_response = ''.join(full_response)
            self.root.after(0, self.display_ai_response, ai_response)
            
        except Exception as e:
            error_msg = f"处理AI响应时出错: {e}"
            self.root.after(0, self.display_error, error_msg)

    def process_tts_buffer(self, buffer):
        if not self.tts_client:
            return buffer
        processed_buffer = buffer
        while True:
            sentence_end_pattern = r'(?<=[.!?。！？])'
            sentences = re.split(sentence_end_pattern, processed_buffer)
            if len(sentences) >= 2:
                complete_sentence = sentences[0].strip()
                if complete_sentence:
                    self.synthesize_text(complete_sentence)
                    processed_buffer = processed_buffer[len(complete_sentence):].lstrip()
                    continue
            elif len(processed_buffer) > MAX_BUFFER_LENGTH:
                text_to_speak = processed_buffer[:MAX_BUFFER_LENGTH]
                self.synthesize_text(text_to_speak)
                processed_buffer = processed_buffer[MAX_BUFFER_LENGTH:].lstrip()
                continue
            break
        return processed_buffer
    
    def synthesize_text(self, text):
        if not text.strip() or not self.tts_client:
            return
        try:
            self.tts_client.synthesize(text)
        except Exception as e:
            print(f"TTS合成失败: {e}")
        
    def display_ai_response(self, ai_response):
        """Display response and Trigger Memory Generation Logic"""
        self.add_to_display("assistant", self.current_role_name, ai_response)
        self.messages.append({'role': 'assistant', 'content': ai_response})
        
        max_messages = 1 + MAX_HISTORY * 2
        if len(self.messages) > max_messages:
            self.messages = [self.messages[0]] + self.messages[-max_messages+1:]
            
        self.save_history()
        self.interaction_count += 1
        
        # Check Memory Condition (Automatic)
        if self.interaction_count > 0 and self.interaction_count % 3 == 0:
            self.update_status(f"正在后台整理记忆...")
            threading.Thread(target=self.run_memory_generation, kwargs={'manual': False}, daemon=True).start()
        else:
            self.enable_buttons()

    # --- Memory Logic ---

    def manual_memory_trigger(self):
        if not self._memory_ready or not self.memory_generator:
            messagebox.showwarning("提示", "记忆模块尚未加载完成，请稍后再试")
            return
            
        if messagebox.askyesno("手动整理记忆", "是否立即整理近期对话并生成长期记忆？\n(这将消耗一定的Token)"):
            self.update_status("正在手动整理记忆...")
            self.disable_buttons()
            threading.Thread(target=self.run_memory_generation, kwargs={'manual': True}, daemon=True).start()

    def run_memory_generation(self, manual=False):
        if not self.memory_generator:
            return
            
        try:
            new_mem = self.memory_generator.generate_memory(max_history_messages=10)
            
            if new_mem:
                print(f"Memory Generated: {new_mem}")
                self.loaded_memories = self.memory_generator.get_memories(limit=5)
                
                if manual:
                    self.root.after(0, lambda: messagebox.showinfo("记忆生成成功", f"新生成的记忆：\n{new_mem}"))
                    self.root.after(0, lambda: self.update_status(f"记忆整理完成"))
                else:
                    self.root.after(0, lambda: self.update_status(f"后台记忆更新完成"))
            else:
                msg = "未能生成新记忆 (可能信息量不足)"
                if manual:
                    self.root.after(0, lambda: messagebox.showinfo("提示", msg))
                self.root.after(0, lambda: self.update_status(msg))
                
        except Exception as e:
            print(f"Memory Gen Error: {e}")
            if manual:
                 self.root.after(0, lambda: messagebox.showerror("错误", f"记忆生成出错: {e}"))
        finally:
            self.root.after(0, self.enable_buttons)

    # --- Button State Management ---

    def disable_buttons(self):
        self.send_button.config(state=tk.DISABLED)
        self.voice_button.config(state=tk.DISABLED)
        self.memory_button.config(state=tk.DISABLED)
        self.clear_button.config(state=tk.DISABLED)
    
    def enable_buttons(self):
        self.send_button.config(state=tk.NORMAL)
        self.clear_button.config(state=tk.NORMAL)
        
        # 只有音频组件就绪才启用语音按钮
        if self._audio_ready and self.voice_recognizer:
            self.voice_button.config(state=tk.NORMAL, bg='#2196F3')
        
        # 只有记忆模块就绪才启用记忆按钮
        if self._memory_ready:
            self.memory_button.config(state=tk.NORMAL)
            
        self.update_status("就绪")

    def display_error(self, error_msg):
        self.add_to_display("system", "系统", error_msg)
        self.enable_buttons()

    # --- Voice Input Logic ---

    def start_voice_input(self):
        if not self._audio_ready or not self.voice_recognizer:
            messagebox.showerror("错误", "语音识别模块尚未加载完成")
            return
        if self.is_listening:
            return
        self.is_listening = True
        self.voice_button.config(state=tk.DISABLED, bg='gray')
        self.update_status("请开始说话...")
        threading.Thread(target=self.voice_input_thread, daemon=True).start()
        
    def voice_input_thread(self):
        try:
            voice_input = self.voice_recognizer.recognize_from_microphone(timeout=10)
            if voice_input:
                self.root.after(0, self.set_voice_input, voice_input)
                self.root.after(0, self.update_status, f"识别结果: {voice_input}")
            else:
                self.root.after(0, self.update_status, "未识别到语音")
        except Exception as e:
            error_msg = f"语音识别出错: {e}"
            self.root.after(0, self.update_status, error_msg)
        finally:
            self.root.after(0, self.voice_input_finished)
            
    def set_voice_input(self, text):
        self.input_text.delete("1.0", tk.END)
        self.input_text.insert("1.0", text)
        self.root.after(500, self.send_message) 
        
    def voice_input_finished(self):
        self.is_listening = False
        if self.send_button['state'] == tk.NORMAL: 
            self.voice_button.config(state=tk.NORMAL, bg='#2196F3')

    # --- Maintenance Logic ---

    def clear_conversation(self):
        if messagebox.askyesno("确认", "确定要清空对话记录吗？"):
            self.clear_conversation_internal(switch_role=False)

    def clear_conversation_internal(self, switch_role=False):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete("1.0", tk.END)
        self.chat_display.config(state=tk.DISABLED)
        
        new_sys_prompt = self._construct_system_prompt(self.current_role_name)
        self.messages = [{'role': 'system', 'content': new_sys_prompt}]
        
        self.save_history()
        
        msg = f"你好，我是{self.current_role_name}！" if switch_role else "对话已清空！"
        self.add_to_display("system", self.current_role_name, msg)
        self.interaction_count = 0

    def load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    self.messages.extend(history[-MAX_HISTORY*2:])
                    for msg in history[-MAX_HISTORY*2:]:
                        if msg['role'] == 'user':
                            self.add_to_display("user", "你", msg['content'])
                        elif msg['role'] == 'assistant':
                            self.add_to_display("assistant", self.current_role_name, msg['content'])
        except Exception as e:
            print(f"加载历史记录失败: {e}")
            
    def save_history(self):
        try:
            history_to_save = [msg for msg in self.messages if msg['role'] in ['user', 'assistant']]
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存历史记录失败: {e}")
            
    def on_closing(self):
        """关闭窗口时的清理工作"""
        self._is_closing = True  # 通知后台线程停止
        
        if messagebox.askokcancel("退出", "确定要退出程序吗？"):
            if self.tts_client and hasattr(self.tts_client, 'close'):
                self.tts_client.close()
            self.root.destroy()


def main():
    logger = Logger(LOGGER_PATH)
    sys.stdout = logger
    sys.stderr = logger
    
    root = tk.Tk()
    app = ChatApplication(root)
    root.mainloop()

if __name__ == "__main__":
    main()
