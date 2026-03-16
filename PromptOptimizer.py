# -*- coding: UTF-8 -*-

# PromptOptimizer.py

import json
import os
import subprocess
import tempfile
import dashscope
from datetime import datetime
from api import call_qwen_stream
from config import PROMPT_OPTIMIZER_PROMPT, Qwen_API_KEY, SYSTEM_PROMPT_FILE 

# 设置 DashScope API Key
dashscope.api_key = Qwen_API_KEY


class PromptOptimizer:
    def __init__(self, role_name, system_prompt_template=PROMPT_OPTIMIZER_PROMPT):
        """
        初始化Prompt优化器
        
        Args:
            role_name (str): 用户输入的角色名字，如"熊大"
            system_prompt_template (str): 系统提示词模板
        """
        self.role_name = role_name
        self.system_prompt_template = system_prompt_template
        self.optimized_prompt = ""
        self.reference_audio_path = ""
    
    def select_reference_audio_powershell(self, initial_dir=None):
        """
        使用PowerShell显示文件选择对话框选择参考音频文件
        
        Args:
            initial_dir (str): 初始目录路径
            
        Returns:
            str: 选择的音频文件路径，如果取消选择则返回空字符串
        """
        try:
            # 构建PowerShell命令
            ps_script = '''
            Add-Type -AssemblyName System.Windows.Forms
            $FileBrowser = New-Object System.Windows.Forms.OpenFileDialog
            $FileBrowser.Filter = "音频文件 (*.wav)|*.wav|所有文件 (*.*)|*.*"
            $FileBrowser.Title = "选择参考音频文件"
            $FileBrowser.InitialDirectory = "{0}"
            $FileBrowser.Multiselect = $false
            $result = $FileBrowser.ShowDialog()
            if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{
                $FileBrowser.FileName
            }}
            '''.format(initial_dir.replace("\\", "\\\\") if initial_dir else os.path.expanduser("~").replace("\\", "\\\\"))
            
            # 将PowerShell脚本写入临时文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False) as temp_file:
                temp_file.write(ps_script)
                temp_file_path = temp_file.name
            
            try:
                # 执行PowerShell脚本
                result = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", temp_file_path],
                    capture_output=True,
                    text=True,
                    encoding='utf-8'
                )
                
                # 清理临时文件
                os.unlink(temp_file_path)
                
                if result.returncode == 0 and result.stdout.strip():
                    selected_file = result.stdout.strip()
                    self.reference_audio_path = selected_file
                    print(f"已选择参考音频文件: {selected_file}")
                    return selected_file
                else:
                    print("未选择音频文件")
                    return ""
                    
            except Exception as e:
                # 确保临时文件被清理
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                raise e
                
        except Exception as e:
            print(f"选择文件时出错: {str(e)}")
            return ""
    
    def select_reference_audio_simple(self, initial_dir=None):
        """
        简单的文件选择方法 - 通过控制台输入路径
        作为备选方案
        
        Args:
            initial_dir (str): 初始目录路径
            
        Returns:
            str: 选择的音频文件路径，如果取消选择则返回空字符串
        """
        try:
            print("请手动输入音频文件路径，或按Enter跳过:")
            print(f"当前目录: {initial_dir or os.getcwd()}")
            print("支持的格式: .wav")
            
            file_path = input("文件路径: ").strip()
            
            if not file_path:
                print("未输入文件路径")
                return ""
            
            # 如果是相对路径，转换为绝对路径
            if not os.path.isabs(file_path):
                base_dir = initial_dir or os.getcwd()
                file_path = os.path.join(base_dir, file_path)
            
            # 检查文件是否存在
            if os.path.exists(file_path):
                # 检查是否是音频文件
                audio_extensions = ['.wav']
                file_ext = os.path.splitext(file_path)[1].lower()
                
                if file_ext in audio_extensions:
                    self.reference_audio_path = file_path
                    print(f"已设置参考音频文件: {file_path}")
                    return file_path
                else:
                    print(f"警告: 文件 '{file_path}' 不是常见的音频格式")
                    confirm = input("是否继续使用此文件? (y/n): ").lower()
                    if confirm == 'y':
                        self.reference_audio_path = file_path
                        print(f"已设置参考音频文件: {file_path}")
                        return file_path
                    else:
                        print("取消选择")
                        return ""
            else:
                print(f"错误: 文件 '{file_path}' 不存在")
                return ""
                
        except Exception as e:
            print(f"选择文件时出错: {str(e)}")
            return ""
    
    def select_reference_audio(self, initial_dir=None):
        """
        选择参考音频文件的主方法
        先尝试PowerShell方法，失败则使用简单方法
        
        Args:
            initial_dir (str): 初始目录路径
            
        Returns:
            str: 选择的音频文件路径，如果取消选择则返回空字符串
        """
        # 设置初始目录
        if not initial_dir:
            initial_dir = os.path.expanduser("~")
        
        print(f"尝试使用PowerShell打开文件选择对话框...")
        file_path = self.select_reference_audio_powershell(initial_dir)
        
        # 如果PowerShell方法失败或用户取消，使用简单方法
        if not file_path:
            print("\nPowerShell方法可能不可用，使用控制台输入方式...")
            file_path = self.select_reference_audio_simple(initial_dir)
        
        return file_path
    
    def set_reference_audio_path(self, path):
        """
        手动设置参考音频路径
        
        Args:
            path (str): 音频文件路径
        """
        if os.path.exists(path):
            self.reference_audio_path = path
            print(f"已设置参考音频路径: {path}")
        else:
            print(f"警告: 文件路径不存在: {path}")
    
    def generate_optimized_prompt(self):
        """
        生成优化的系统提示词
        
        Returns:
            tuple: (success: bool, prompt: str) 生成是否成功和优化后的提示词
        """
        try:
            # 构造消息列表
            messages = [
                {
                    "role": "system", 
                    "content": self.system_prompt_template
                },
                {
                    "role": "user", 
                    "content": f"请为角色'{self.role_name}'创建一个系统级提示词:"
                }
            ]
            
            # 调用流式API并累加结果
            full_response = ""
            print(f"正在为角色'{self.role_name}'生成优化提示词...")
            
            for chunk in call_qwen_stream(messages):
                if chunk.startswith("\n[ERROR]"):
                    print(f"生成失败: {chunk}")
                    return False, chunk
                
                full_response += chunk
                # 可以在这里添加实时显示逻辑
                print(chunk, end="", flush=True)
            
            print("\n")  # 换行
            self.optimized_prompt = full_response.strip()
            return True, self.optimized_prompt
            
        except Exception as e:
            error_msg = f"生成过程中出现异常: {str(e)}"
            print(error_msg)
            return False, error_msg
    
    def save_to_json(self, filename=SYSTEM_PROMPT_FILE):
        """
        将优化后的提示词保存到JSON文件
        
        Args:
            filename (str): 保存的文件名
            
        Returns:
            bool: 保存是否成功
        """
        if not self.optimized_prompt:
            print("没有可保存的提示词，请先调用generate_optimized_prompt()")
            return False
        
        try:
            # 构造保存的数据结构
            new_data = {
                "role_name": self.role_name,
                "system_prompt": self.optimized_prompt,
                "reference_audio_path": self.reference_audio_path,
                "timestamp": datetime.now().isoformat()
            }
            
            # 读取现有数据（如果文件存在）
            all_data = []
            if os.path.exists(filename):
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                        # 如果文件内容是一个列表，直接使用
                        if isinstance(existing_data, list):
                            all_data = existing_data
                        # 如果文件内容是单个对象，转换为列表
                        else:
                            all_data = [existing_data]
                except json.JSONDecodeError:
                    print("警告：现有文件格式错误，将创建新文件")
                    all_data = []
            
            # 检查是否已存在相同角色的提示词
            role_exists = False
            for i, item in enumerate(all_data):
                if isinstance(item, dict) and item.get("role_name") == self.role_name:
                    # 更新已存在的角色提示词
                    all_data[i] = new_data
                    role_exists = True
                    print(f"更新角色 '{self.role_name}' 的提示词")
                    break
            
            # 如果角色不存在，添加到列表
            if not role_exists:
                all_data.append(new_data)
                print(f"添加新角色 '{self.role_name}' 的提示词")
            
            # 保存到文件
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            
            print(f"提示词已成功保存到 {filename}")
            return True
            
        except Exception as e:
            print(f"保存文件失败: {str(e)}")
            return False
    
    def run_optimization(self, save_file=True, filename=SYSTEM_PROMPT_FILE, ask_for_audio=False):
        """
        完整的优化流程
        
        Args:
            save_file (bool): 是否保存到文件
            filename (str): 保存的文件名
            ask_for_audio (bool): 是否询问选择参考音频文件
            
        Returns:
            tuple: (success: bool, prompt: str) 整体流程是否成功和优化后的提示词
        """
        success, prompt = self.generate_optimized_prompt()
        
        if success and ask_for_audio:
            print("请为角色选择参考音频文件...")
            self.select_reference_audio()
        
        if success and save_file:
            self.save_to_json(filename)
        
        return success, prompt
    
    @staticmethod
    def load_prompts(filename=SYSTEM_PROMPT_FILE):
        """
        从JSON文件加载所有提示词
        
        Args:
            filename (str): 文件名
            
        Returns:
            list: 提示词列表，如果文件不存在或格式错误返回空列表
        """
        if not os.path.exists(filename):
            return []
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else [data]
        except (json.JSONDecodeError, Exception) as e:
            print(f"加载提示词文件失败: {str(e)}")
            return []
    
    @staticmethod
    def get_prompt_by_role(role_name, filename=SYSTEM_PROMPT_FILE):
        """
        根据角色名获取对应的提示词
        
        Args:
            role_name (str): 角色名
            filename (str): 文件名
            
        Returns:
            str: 对应的系统提示词，如果找不到返回None
        """
        prompts = PromptOptimizer.load_prompts(filename)
        for item in prompts:
            if isinstance(item, dict) and item.get("role_name") == role_name:
                return item.get("system_prompt")
        return None
    
    @staticmethod
    def get_reference_audio_by_role(role_name, filename=SYSTEM_PROMPT_FILE):
        """
        根据角色名获取对应的参考音频路径
        
        Args:
            role_name (str): 角色名
            filename (str): 文件名
            
        Returns:
            str: 对应的参考音频路径，如果找不到返回None
        """
        prompts = PromptOptimizer.load_prompts(filename)
        for item in prompts:
            if isinstance(item, dict) and item.get("role_name") == role_name:
                return item.get("reference_audio_path", "")
        return None
    
    @staticmethod
    def list_all_roles(filename=SYSTEM_PROMPT_FILE):
        """
        列出所有已保存的角色
        
        Args:
            filename (str): 文件名
            
        Returns:
            list: 角色名列表
        """
        prompts = PromptOptimizer.load_prompts(filename)
        role_names = []
        for item in prompts:
            if isinstance(item, dict) and "role_name" in item:
                role_names.append(item["role_name"])
        return role_names
    
    @staticmethod
    def get_role_info(role_name, filename=SYSTEM_PROMPT_FILE):
        """
        获取角色的完整信息
        
        Args:
            role_name (str): 角色名
            filename (str): 文件名
            
        Returns:
            dict: 包含角色完整信息的字典，如果找不到返回None
        """
        prompts = PromptOptimizer.load_prompts(filename)
        for item in prompts:
            if isinstance(item, dict) and item.get("role_name") == role_name:
                return item
        return None
    
    @staticmethod
    def get_all_role_info(filename=SYSTEM_PROMPT_FILE):
        """
        获取所有角色的完整信息
        
        Args:
            filename (str): 文件名
            
        Returns:
            list: 包含所有角色信息的字典列表
        """
        return PromptOptimizer.load_prompts(filename)


# 调用实例
def main():
    # 用户输入角色名
    role_name = "熊大"
    
    # 创建优化器实例
    optimizer = PromptOptimizer(role_name)
    
    # 生成优化提示词
    success, optimized_prompt = optimizer.generate_optimized_prompt()
    
    if success:
        # 输入路径
        optimizer.select_reference_audio()
        # 保存到文件
        optimizer.save_to_json()
        print("优化完成！")
        print(f"生成的提示词: {optimized_prompt}")
        if optimizer.reference_audio_path:
            print(f"参考音频路径: {optimizer.reference_audio_path}")
    else:
        print("优化失败")
     
    # 显示所有已保存的角色
    all_roles = PromptOptimizer.list_all_roles()
    print(f"当前已保存的角色: {', '.join(all_roles)}")
    
    # 查询角色的提示词和音频路径
    role_to_ask = "达芬奇"
    print(f"你要查询的角色: {role_to_ask}")
    
    if role_to_ask in all_roles:
        # 获取提示词
        role_prompt = PromptOptimizer.get_prompt_by_role(role_to_ask)
        print(f"提示词: {role_prompt}")
        
        # 获取参考音频路径
        audio_path = PromptOptimizer.get_reference_audio_by_role(role_to_ask)
        if audio_path:
            print(f"参考音频路径: {audio_path}")
            # 检查文件是否存在
            if os.path.exists(audio_path):
                print("音频文件存在")
            else:
                print("警告: 音频文件不存在或路径错误")
        else:
            print("该角色没有设置参考音频路径")
    else:
        print(f"角色 {role_to_ask} 不存在")
    
    # 示例：获取所有角色完整信息
    print("\n--- 所有角色完整信息 ---")
    all_role_info = PromptOptimizer.get_all_role_info()
    for role_info in all_role_info:
        print(f"角色: {role_info.get('role_name')}")
        print(f"创建时间: {role_info.get('timestamp')}")
        print(f"音频路径: {role_info.get('reference_audio_path', '未设置')}")
        if role_info.get('reference_audio_path'):
            if os.path.exists(role_info['reference_audio_path']):
                print("音频文件状态: 存在")
            else:
                print("音频文件状态: 不存在")
        print("-" * 40)


if __name__ == "__main__":
    main()