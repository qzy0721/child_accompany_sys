# 项目介绍

## 项目名称
#### 基于角色拟人化提示词的交互式儿童语音陪伴系统
---

## 功能特性

本项目是一款专为儿童设计的**高度可定制语音陪伴系统**，集成了离线语音识别、大语言模型流式对话与本地语音合成三大核心模块，通过创新的流式并行处理架构、角色拟人化提示词工程和长期记忆机制，实现了低延迟、高拟真、强个性化的交互体验，为家庭场景提供安全、自然、有温度的智能陪伴。

> 本项目基于开源组件构建，融合前沿 AI 技术与儿童发展心理学理念，致力于为每个家庭打造**有温度、懂陪伴、可成长**的智能语音伙伴。  
语音合成基于 [IndexTTS 1.5](https://github.com/index-tts/index-tts/tree/v1.5.0) 开源项目，对话和语音识别功能通过调用阿里云 LLM API 实现   （需自行申请 API Key 并写入 `config.py`）。

---

## ✨ 核心功能

### 1. 角色人格化定制 —— 让每个声音都有灵魂
- **一键生成角色人格**：用户只需输入角色名称（如“熊大”“奶龙”），系统自动调用大语言模型生成包含**核心身份、性格标签、说话口吻、知识范围、安全禁令及口头禅**的详细设定，并作为高优先级系统提示词固化，确保角色行为一致、人格稳定。
- **多角色动态切换**：支持保存多个角色设定，通过下拉菜单快速切换，每个角色拥有独立的语音风格和交互逻辑。
- **零样本语音克隆**：基于 IndexTTS 的语音克隆技术，仅需数秒参考音频即可定制角色声线（如父母声音、卡通形象），强化情感亲和力与专属感。

### 2. 低延迟流式对话 —— 对话如真人般流畅
- **流水线并行处理**：打破传统“识别→生成→合成”串行流程，采用 **ASR 实时输出 → LLM 流式生成 → TTS 边合成边播放** 的全链路并行架构，实现“边想边说、边说边播”。
- **实时分句与合成**：主控逻辑根据句末标点动态切分 LLM 输出的文本片段，立即触发 TTS 合成与播放，一定程度消除卡顿感。

### 3. 双轨记忆机制 —— 越用越懂孩子的成长伙伴
- **短期对话缓存**：自动保存最近多轮对话历史，用于维持上下文连贯性。
- **长期结构化记忆**：内置“记忆生成器”模块，定期（如每10轮对话）或手动触发，从对话历史中提取儿童**偏好、习惯、重要事件**等关键信息，以结构化 JSON 格式存储。
- **记忆主动调用**：每次对话初始化时，系统自动加载最新记忆并注入系统提示词，使 AI 能够“回忆”过往经历（如“你上次说喜欢恐龙，今天想听恐龙故事吗？”），实现个性化成长陪伴。

### 4. 本地化部署与隐私保护 —— 家庭数据安全无忧
- **隐私内容本地化**：同时敏感数据例如**对话历史、历史记忆**均在本地保存，最大限度保护家庭隐私。
- **云端仅语音识别和LLM**：语音合成（IndexTTS）完全本地运行，不依赖网络；仅语音识别和LLM需联网（阿里云 API），用户可自行替换为本地模型以实现完全离线。
- **敏感信息过滤**：提示词生成环节中提示词嵌入安全边界，确保不生成不适宜儿童的内容。

---

## 🧩 模块化设计

系统采用**多线程、事件驱动**的模块化架构，各组件通过线程安全队列和共享状态协同工作，便于维护和功能扩展：

| 模块 | 说明 |
|------|------|
| **语音识别 (sr.py)** | 基于阿里云 语音识别API 实现，可实时采集音频与静音检测（VAD），识别准确率较高 。 |
| **对话生成 (api.py)** | 封装阿里云 LLM 流式接口，支持增量输出与错误重试，实现可控上下文管理。 |
| **语音合成 (tts.py)** | 基于 IndexTTS，支持零样本克隆，双队列架构确保合成与播放异步流畅。 |
| **提示词优化器 (PromptOptimizer.py)** | 根据角色名自动生成详细人格设定，支持多角色持久化。 |
| **记忆生成器 (MemoryGenerate.py)** | 定期从对话中提取关键信息，形成长期记忆库。 |
| **主控与 GUI (gui_main.py)** | Tkinter 图形界面，整合所有模块，提供对话展示、角色管理、记忆操作等交互。 |
| **日志与配置 (logger.py, config.py)** | 统一日志追踪运行状态，集中管理 API 密钥、模型路径等参数。 |

---

## 🚀 使用流程简介

1. **启动系统**：执行 `python gui_main.py`，界面显示“就绪”。
2. **选择或创建角色**：
   - 从下拉菜单选择已有角色（如“熊大”）。
   - 点击“新建角色”，输入名称，系统自动生成人格设定并保存。
3. **开始对话**：
   - 点击“🎤 语音”按钮说话，或直接在输入框键入文本。
   - AI 回复以文字流式显示，同时播放合成语音。
4. **记忆管理**：
   - 系统自动每10轮对话生成记忆；也可点击“生成记忆”手动触发。
   - 记忆内容可在后续对话中自动调用，实现个性化回应。
5. **切换角色**：随时通过下拉菜单更换角色，系统立即应用新设定。

---

# 🔧 安装与配置
## 📌 重要说明

- 当前版本使用 **IndexTTS 1.5**（非 2.0），其安装依赖 conda 虚拟环境，不支持 IndexTTS 2.0 新增的八维情感控制、时间控制等特性。未来计划升级至 2.0 版本。
- 所有与 IndexTTS 1.5 相关的安装操作应在独立的目录中进行，避免与本项目主程序文件混淆。

---

## 🔧 配置步骤

### 1. 安装 IndexTTS 1.5
>以下脚本均在indextts的独立目录下执行

#### 1.1 克隆仓库
选择一个独立目录（不要与后续主程序目录重合），执行：
```bash
git clone https://github.com/AdamHawkinsa/index-tts.git
cd index-tts
```
> 这是indextts官方仓库的一个fork，是直接可用的indextts1.5版本。官方仓库已经更新到indextts2.0，且由于git历史被清空，难以通过类似git checkout v1.5.0 切换版本

#### 1.2 创建 conda 环境
使用 Anaconda Prompt 在 `index-tts` 目录下执行：
```bash
conda create -n indextts python=3.10
conda activate indextts
```

#### 1.3 安装 PyTorch
根据你的 GPU 型号和驱动版本选择合适的 PyTorch 版本。  
例如，对于支持 CUDA 12.4 的 RTX 4060：
```bash
pip install torch==2.5.1+cu124 torchaudio==2.5.1+cu124 -f https://download.pytorch.org/whl/cu124
```
> 若下载速度慢，可预先下载对应 `.whl` 文件本地安装。

#### 1.4 安装其他依赖
```bash
pip install -r requirements.txt
```
（该文件由 IndexTTS 1.5 项目提供）

#### 1.5 安装 ffmpeg
```bash
conda install -c conda-forge ffmpeg
```

#### 1.6 修复 pynini 问题（Windows 适用）
```bash
conda install -c conda-forge pynini==2.1.6
pip install WeTextProcessing --no-deps
```

#### 1.7 将 IndexTTS 安装为 Python 包（含 WebUI 扩展）
在 `index-tts` 目录下执行：
```bash
pip install -e ".[webui]" --no-build-isolation
```
此步骤确保后续主程序能正确导入 IndexTTS 模块。

#### 1.8 下载模型文件
创建 `checkpoints` 目录，并从 [HuggingFace IndexTTS-1.5](https://huggingface.co/IndexTeam/IndexTTS-1.5/tree/main) 下载以下文件放入其中：
- `config.yaml`
- `bigvgan_discriminator.pth`
- `bigvgan_generator.pth`
- `bpe.model`
- `dvae.pth`
- `gpt.pth`
- `unigram_12000.vocab`

完成后目录结构应类似：
```
index-tts/
├── checkpoints/
│   ├── config.yaml
│   ├── bigvgan_discriminator.pth
│   ├── ...
├── assets/
├── indextts/
├── tools/
├── webui.py
└── ...
```

#### 1.9 测试 IndexTTS 1.5
在 `indextts` 环境下运行 WebUI 测试：
```bash
python webui.py
```
若正常启动，则安装成功。

---

### 2. 准备主程序环境

将本项目的所有主程序文件放置于另一个独立文件夹中（例如 `child_accompany_sys/`）。

#### 2.1 安装主程序依赖
确保仍处于 `indextts` conda 环境，在项目主目录下执行：
```bash
pip install -r requirements.txt
```
（此 `requirements.txt` 由本项目提供，包含阿里云 SDK 等必要库）



#### 2.2 修改配置文件
复制 `config.py.example`为 `config.py`，并根据注释填写以下参数：
- 阿里云 API Key ；文件路径
- 其他自定义配置（如音频设备、语音参数等）

---

## 🚀 运行

在项目主目录下，确保 `indextts` 环境已激活，执行：
```bash
python gui_main.py
```

---

## 📝 备注

- **IndexTTS 2.0 差异**：若未来升级至 IndexTTS 2.0，需使用 `uv` 管理虚拟环境，安装方式有所不同。可参考 [IndexTTS 官方文档](https://github.com/index-tts/index-tts/blob/main/docs/README_zh.md)。
- 如遇到 pynini 相关错误，请检查步骤 1.6 是否完整执行。
- 建议使用 NVIDIA GPU 以获得最佳性能，并确保已安装匹配的 CUDA Toolkit（可从 [NVIDIA 官网](https://developer.nvidia.com/cuda-toolkit) 下载）。

---

## 📧 联系

如有问题，欢迎提交 Issue 或联系项目作者。

---

> 本项目基于开源组件构建，感谢 IndexTTS、阿里云等团队的支持。

