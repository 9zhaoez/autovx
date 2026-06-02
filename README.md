# 🤖 autovx / 微信AI自动回复机器人

**WeChat AI Auto-Reply Bot — OCR + DeepSeek powered. No API hook. Just works.**

[![Python](https://img.shields.io/badge/Python-3.9+-blue)](https://python.org)

---

## 📖 这是什么 / What is this?

帮你自动回复微信消息的程序。屏幕截图 + OCR 识字 + AI 生成回复 + 模拟键盘打字，不需要 hook 微信任何接口，就像一个人真的坐在电脑前帮你回消息。

It watches your WeChat window, reads new messages via OCR, generates replies with AI (or keyword rules), and types them back — just like a real person would.

---

## 🚀 怎么用 / How to Use

### 1. 装依赖 / Install

```bash
pip install -r requirements_v2.txt
```

### 2. 配 AI / Set API Key

新建 `.env` 文件，写入你的 DeepSeek API Key：

```
DEEPSEEK_API_KEY=sk-你的key
```

### 3. 改规则（可选）/ Edit Rules

打开 `config.py`，修改 `REPLY_RULES` 关键词列表和 `AI_SYSTEM_PROMPT` 人设。

### 4. 框选聊天区域（首次必做）/ Calibrate Chat Area

> ⚠️ **这一步决定 OCR 识别准不准，必须做！**

双击 **`框选检测区域.bat`** → 按住左键拖拽框出微信聊天消息显示区（不要包含左侧联系人栏和底部输入框）→ 按 Enter 保存。

### 5. 启动 / Run

双击 **`启动自动回复.bat`** 即可。

或者命令行：

```bash
# 持续自动回复（最常用）
python wechat_bot.py

# 只回复当前窗口最新一条消息
python wechat_bot.py --once

# 给当前窗口发送指定内容
python wechat_bot.py --msg "你好"

# 从剪贴板读消息并回复
python wechat_bot.py --clip
```

---

## 🎮 四个BAT分别干嘛 / What the BAT Files Do

| 文件 / File | 作用 / Purpose |
|------------|---------------|
| **启动自动回复.bat** | 🟢 **主要入口** — 双击启动，持续监听并自动回复 |
| **框选检测区域.bat** | 🎯 **首次必用** — 框选微信聊天消息区，确定 OCR 识别范围 |
| **快速回复.bat** | ⚡ 复制对方消息 → 点这个 → 自动粘贴回复 |
| **查看演示.bat** | 🧪 模拟测试回复规则是否生效 |

---

## ✨ 功能 / Features

| 功能 / Feature | 说明 / Description |
|---------------|---------------------|
| 🔍 关键词匹配 | 8条内置规则，支持精确/模糊匹配，在 `config.py` 自定义 |
| 🧠 AI 智能回复 | DeepSeek / OpenAI / Ollama / SiliconFlow 四选一 |
| 👁️ OCR 识字 | RapidOCR 引擎，截图→识字→去重，不碰剪贴板 |
| ⚡ 实时监听 | 屏幕像素差分检测，有变化才 OCR，空闲近乎零 CPU |
| 📝 对话记忆 | SQLite 存聊天记录，自动提取对方名字、年龄、喜好 |
| 🔒 熔断保护 | AI API 连续失败自动暂停 30 秒 |
| 👤 黑白名单 | 指定回复/不回复哪些人、哪些群 |

---

## ⚙️ 怎么改规则 / How to Customize

编辑 `config.py`：

```python
REPLY_RULES = [
    {
        "keywords": ["在吗", "在不在"],
        "reply": "在呢",
        "match": "exact",    # exact=精确匹配, contains=包含即触发
    },
    # ... 加更多规则
]

# AI 人设在 AI_SYSTEM_PROMPT 里改
# AI 提供商在 AI_PROVIDER 切换: deepseek / openai / ollama / siliconflow
```

---

## ⚠️ 注意 / Notes

- 只支持 Windows（依赖 win32gui）
- 微信窗口不能关闭，可以最小化
- 聊天区不能被其他窗口遮挡（OCR 要能看到）
- **不建议 24 小时挂机**，微信可能检测异常
- 本程序仅供学习研究使用

---

## 📁 文件说明 / Project Structure

```
autovx/
├── 启动自动回复.bat        ← 🟢 双击这个启动
├── 框选检测区域.bat        ← 🎯 首次用这个校准
├── 快速回复.bat            ← ⚡ 剪贴板快速回复
├── 查看演示.bat            ← 🧪 测试规则
├── wechat_bot.py           # 主程序
├── ocr_reader.py           # OCR 识字
├── ai_client.py            # AI 客户端
├── realtime_monitor.py     # 实时监听
├── wechat_window.py        # 窗口管理
├── memory_store.py         # 对话记忆
├── human_like_operations.py # 模拟真人操作
├── config.py               # 配置文件（改规则看这个）
├── setup_region.py         # 框选工具
└── diagnose.py             # 诊断工具
```

---

**Made with ❤️ by [9zhaoez](https://github.com/9zhaoez)**
