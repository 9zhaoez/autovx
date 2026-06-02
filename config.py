"""
自动回复配置文件
修改关键词和回复内容即可定制回复规则
"""
import os
from pathlib import Path

# 🔐 从 .env 文件加载密钥（优先环境变量，其次 .env 文件）
def _load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value

_load_env()

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

# ============================================================
# 自动回复规则列表
# keywords: 触发关键词（支持多个，任意匹配即可触发）
# reply:    回复内容
# match:    "exact" 精确匹配 / "contains" 包含即匹配（默认）
# ============================================================
REPLY_RULES = [
    {
        "keywords": ["在吗", "在不在", "在么"],
        "reply": "在呢",
        "match": "exact",
    },
    {
        "keywords": ["你好", "hello", "hi", "嗨"],
        "reply": "嗨",
        "match": "contains",
    },
    {
        "keywords": ["谢谢", "感谢", "thanks", "多谢"],
        "reply": "没事",
        "match": "contains",
    },
    {
        "keywords": ["晚安", "早点休息"],
        "reply": "晚安",
        "match": "contains",
    },
    {
        "keywords": ["早安", "早上好", "早啊"],
        "reply": "早啊",
        "match": "contains",
    },
    {
        "keywords": ["吃了吗", "吃饭", "吃了没"],
        "reply": "吃了哈哈，你呢",
        "match": "contains",
    },
    {
        "keywords": ["生日快乐", "生日"],
        "reply": "生日快乐！",
        "match": "contains",
    },
    {
        "keywords": ["好的", "ok", "OK", "收到", "知道了", "行", "可以"],
        "reply": "嗯嗯",
        "match": "contains",
    },
]

# ============================================================
# 通用设置
# ============================================================

# 白名单：只自动回复这些人的消息（留空则回复所有人）
# 填写微信昵称的完整或部分名称
WHITELIST = []

# 黑名单：不回复这些人的消息
BLACKLIST = []

# 群聊设置：是否对群聊消息也自动回复
# 注意：群聊中需要 @机器人 才会触发回复（微信限制）
ENABLE_GROUP_REPLY = False

# 群聊白名单：只回复这些群的 @消息（留空则回复所有群）
GROUP_WHITELIST = []

# 群聊黑名单：不回复这些群的消息
GROUP_BLACKLIST = []

# 检查新消息的间隔（秒），建议 2-5 秒
CHECK_INTERVAL = 3

# 默认回复：当消息不匹配任何规则且该功能开启时发送
ENABLE_DEFAULT_REPLY = True
DEFAULT_REPLY = "嗯嗯好的"

# ============================================================
# AI 智能回复（DeepSeek API，兼容 OpenAI 格式）
# 开启后，不匹配规则的消息会交给 AI 回复
# ============================================================
ENABLE_AI_REPLY = True

# AI 提供商: "deepseek" 便宜 / "siliconflow" 有免费额度 / "openai" / "ollama" 本地免费
AI_PROVIDER = "deepseek"

# DeepSeek 官方（推荐，￥2/百万token）
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "sk-your-deepseek-key")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 硅基流动（注册送额度，DeepSeek模型可用）
SILICONFLOW_API_KEY = "sk-your-siliconflow-key"
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V3"

# OpenAI
OPENAI_API_KEY = "sk-your-openai-key"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-4o-mini"

# Ollama 本地模型（免费，需先安装 Ollama 并下载模型）
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "qwen2.5:0.5b"

# AI 系统提示词
AI_SYSTEM_PROMPT = """你是tfe，一个幽默风趣、执行力爆表、脑子转得快的男生。你就是tfe本人。

个人信息：
- 你住在四川省成都市高新区孵化园
- 别人问你家在哪、住哪里、地址的时候如实回答

核心原则：
- 回复要短，但该说清楚的时候不省字。闲聊15字以内，正经问题放开了说
- 每条回复都要有信息量，不说正确的废话
- 看人下菜：对方认真你就认真，对方开玩笑你就接梗，对方急了你就正经

执行力（最重要）：
- 别人让你干啥，回答只有三种：直接干、干完了汇报、干不了说具体原因
- 不说"我试试""我看看""稍等"这种废话，要么直接给结果，要么说清楚卡在哪
- 别人问你能不能做某事，默认你能，直接给方案
- 别人催你，不解释不道歉，加速给结果
- 接到任务第一反应是"好"或"行"，然后给具体行动

能力要求：
- 数学/逻辑题认真算，算完可以嘴贫一句但先把答案说对
- 别人问路、问方法、问怎么做，给具体可执行的答案
- 别人情绪低落时正经安慰，别在这种时候抖机灵
- 能读出对方话里的潜台词，别当复读机

性格：
- 嘴贫但讨喜，冷不丁来句好笑的
- 会接梗也会抛梗，能自己造梗
- 记性好，聊过的事能拿出来调侃
- 偶尔自黑，偶尔吐槽，不冒犯

对话范例（学习这个风格）：
问：在吗
答：在呢
问：帮我查一下明天成都天气
答：明天多云转晴，18到26度，不用带伞。
问：从犀浦站到你家怎么坐
答：2号线到天府广场换1号线，孵化园站A口出，直走200米。来之前说一声，可乐给你冰好。
问：2X+X平方=8，X等于多少
答：X=2或者X=-4。你作业没写完吧？
问：今天好烦
答：怎么了？说说
问：叫爸爸
答：你先叫声哥来听听
问：你叫什么
答：tfe，记住没？下次再问收费了
问：帮我写个快递地址
答：四川省成都市高新区孵化园，收件人写tfe就行。寄啥好东西？
问：发个红包
答：没钱。换个别的事，分分钟给你办妥。
问：你行不行啊
答：行。说事。

禁止：
- 不说"助手""AI""机器人""主人""留言"
- 不用"您""请""您好"
- 不发emoji
- 不油腻不中二不装逼
- 不反问不推脱不找理由
- 不加括号动作描写，这是打字聊天不是演戏
- 不每条都硬搞笑，该正经就正经"""

# ============================================================
# OCR 图像识别设置（方案 B：截取聊天区底部）
# 开启后用 OCR 替代剪贴板方式读取消息，更可靠
# ============================================================

# 是否启用 OCR 读取消息（True=OCR, False=剪贴板）
OCR_ENABLED = True

# OCR 引擎: "easyocr"（推荐，安装简单）/ "paddleocr"（中文更准）
OCR_ENGINE = "rapidocr"

# 截取聊天区底部的比例（1.0=截满整区）
OCR_BOTTOM_RATIO = 1.0

# 聊天区上边距比例（消息开始的位置）
CHAT_TOP_RATIO = 0.47

# 聊天区下边距比例（输入框上方的位置）
CHAT_BOTTOM_RATIO = 0.77

# OCR 调试模式：保存截图到当前目录（排查问题时开启）
OCR_DEBUG = True

# 聊天区左侧偏移比例（排除左侧联系人列表）
# 微信窗口左侧是联系人/公众号列表，右侧才是聊天消息区
# 根据你的微信布局调整：0.25=左侧占25%，0.30=左侧占30%
CHAT_LEFT_RATIO = 0.3704

# 聊天区右侧偏移比例
CHAT_RIGHT_RATIO = 0.0278


