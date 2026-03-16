# -*- coding: UTF-8 -*-

# MemoryGenerate.py

import json
import dashscope
import os
from datetime import datetime
from config import MEMORY_GENERATE_PROMPT , HISTORY_FILE , HISTORY_MEMROY, Qwen_API_KEY
from api import call_qwen_stream


# 设置 DashScope API Key
dashscope.api_key = Qwen_API_KEY

class MemoryGenerate:
    def __init__(self, history_file=HISTORY_FILE, memory_file= HISTORY_MEMROY):
        """
        初始化记忆生成器
        
        Args:
            history_file: 对话历史文件路径
            memory_file: 记忆存储文件路径
        """
        self.history_file = history_file
        self.memory_file = memory_file
        self.memory_data = self._load_memory()
    
    def _load_conversation_history(self):
        """读取对话历史记录"""
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"警告: 对话历史文件 {self.history_file} 不存在")
            return []
        except json.JSONDecodeError:
            print(f"错误: 对话历史文件 {self.history_file} 格式错误")
            return []
    
    def _load_memory(self):
        """读取现有记忆"""
        if not os.path.exists(self.memory_file):
            return {"memories": [], "last_updated": None}
        
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"memories": [], "last_updated": None}
    
    def _save_memory(self):
        """保存记忆到文件"""
        self.memory_data["last_updated"] = datetime.now().isoformat()
        
        try:
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(self.memory_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存记忆文件失败: {e}")
            return False
    
    def _format_conversation_for_prompt(self, conversation_history):
        """格式化对话历史用于提示词"""
        formatted = []
        for msg in conversation_history:
            role = "用户" if msg["role"] == "user" else "助手"
            formatted.append(f"{role}: {msg['content']}")
        
        return "\n".join(formatted)
    
    def generate_memory(self, max_history_messages=1000):
        """
        生成新的记忆
        
        Args:
            max_history_messages: 最多使用多少条历史消息生成记忆
            
        Returns:
            str: 生成的记忆内容，失败时返回None
        """
        # 读取对话历史
        conversation_history = self._load_conversation_history()
        if not conversation_history:
            print("没有可用的对话历史")
            return None
        
        # 使用最近的对话历史
        recent_history = conversation_history[-max_history_messages:]
        
        # 构建提示词
        formatted_conversation = self._format_conversation_for_prompt(recent_history)
        
        system_prompt = MEMORY_GENERATE_PROMPT
        user_prompt = f"以下是最近的对话记录：\n\n{formatted_conversation}\n\n请基于这段对话生成记忆："
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        print("正在生成记忆...")
        
        try:
            # 调用API生成记忆
            memory_content = ""
            for chunk in call_qwen_stream(messages):
                memory_content += chunk
                print(chunk, end="", flush=True)
            
            print("\n")  # 换行
            
            if memory_content and not memory_content.startswith("[ERROR]"):
                # 创建新的记忆条目
                new_memory = {
                    "id": len(self.memory_data["memories"]) + 1,
                    "content": memory_content.strip(),
                    "timestamp": datetime.now().isoformat(),
                    "source_conversation_count": len(recent_history)
                }
                
                # 添加到记忆列表
                self.memory_data["memories"].append(new_memory)
                
                # 保存到文件
                if self._save_memory():
                    print(f"记忆已保存到 {self.memory_file}")
                    return memory_content.strip()
                else:
                    print("记忆生成成功但保存失败")
                    return None
            else:
                print(f"记忆生成失败: {memory_content}")
                return None
                
        except Exception as e:
            print(f"调用API时发生错误: {e}")
            return None
    
    def get_memories(self, limit=None):
        """获取所有记忆"""
        memories = self.memory_data.get("memories", [])
        if limit:
            return memories[-limit:]
        return memories
    
    def clear_memories(self):
        """清空所有记忆"""
        self.memory_data = {"memories": [], "last_updated": datetime.now().isoformat()}
        return self._save_memory()
    


def main():
    # 创建记忆生成器实例
    memory_gen = MemoryGenerate()
    
    # 生成新记忆
    print("=== 开始生成记忆 ===")
    new_memory = memory_gen.generate_memory(max_history_messages=100)
    
    if new_memory:
        print(f"\n✅ 生成的记忆: {new_memory}")
    else:
        print("\n❌ 记忆生成失败")
    
    # 查看所有记忆
    print("\n=== 所有记忆 ===")
    all_memories = memory_gen.get_memories()
    for memory in all_memories:
        print(f"记忆 #{memory['id']}: {memory['content']}")
        print(f"时间: {memory['timestamp']}\n")

if __name__ == "__main__":
    main()