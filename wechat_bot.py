# -*- coding: utf-8 -*-
"""
微信自动回复机器人 — 主控编排器
负责协调各模块（窗口、AI、OCR、记忆），自身只做流程编排

用法:
    python wechat_bot.py              # 启动自动回复循环
    python wechat_bot.py --once       # 单次：回复当前聊天窗口最新消息
    python wechat_bot.py --msg "你好" # 给当前窗口发消息
    python wechat_bot.py --clip       # 从剪贴板读消息并回复
"""

import sys
import time
import random
import logging
import threading
from typing import Optional

sys.stdout.reconfigure(encoding='utf-8')

# ── 基础依赖 ────────────────────────
import pyautogui
import pyperclip

# ── 新模块 ──────────────────────────
from ai_client import AIClient, create_ai_client_from_config
from wechat_window import (
    find_wechat_process, find_wechat_window,
    get_window_rect, process_is_alive, ensure_foreground,
    click_chat_area, click_input_area,
    WINDOW_RETRY_S, PROCESS_DEAD_CHECK_S,
    SEND_BEFORE_ENTER_MIN_S, SEND_BEFORE_ENTER_MAX_S,
)
from memory_store import MemoryStore

try:
    from human_like_operations import HumanLikeOperations
    HAS_HUMAN = True
except ImportError:
    HAS_HUMAN = False

try:
    from realtime_monitor import RealtimeChatMonitor
    HAS_REALTIME = True
except ImportError:
    HAS_REALTIME = False

from config import (
    REPLY_RULES, CHECK_INTERVAL,
    ENABLE_DEFAULT_REPLY, DEFAULT_REPLY,
    ENABLE_AI_REPLY,
    OCR_ENABLED, OCR_ENGINE, OCR_BOTTOM_RATIO, OCR_DEBUG,
    CHAT_LEFT_RATIO, CHAT_RIGHT_RATIO,
    CHAT_TOP_RATIO, CHAT_BOTTOM_RATIO,
)

# ── 日志 ────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(message)s'
)
logger = logging.getLogger('WeChatBot')


# ============================================================
# 微信机器人 — 纯编排层
# ============================================================
class WeChatBot:
    """微信自动回复机器人 — 只做模块编排"""

    def __init__(self):
        self.wechat_pid: Optional[int] = None
        self.main_hwnd: Optional[int] = None
        self.running = False
        self.reply_count = 0
        self.last_clipboard = ""
        self.last_reply_text = ""

        # 子模块
        self.human = HumanLikeOperations() if HAS_HUMAN else None
        self.ai = create_ai_client_from_config() if ENABLE_AI_REPLY else None
        self._memory = MemoryStore()
        self._msg_queue: list = []
        self._msg_lock = threading.Lock()
        self._monitor: Optional[RealtimeChatMonitor] = None
        self._last_detect_time = time.time()

        # OCR 读取器
        self.ocr = None
        if OCR_ENABLED:
            try:
                from ocr_reader import OCRReader
                self.ocr = OCRReader(
                    engine=OCR_ENGINE, bottom_ratio=OCR_BOTTOM_RATIO,
                    left_ratio=CHAT_LEFT_RATIO, right_ratio=CHAT_RIGHT_RATIO,
                    top_ratio=CHAT_TOP_RATIO, bottom_offset_ratio=CHAT_BOTTOM_RATIO,
                    debug=OCR_DEBUG,
                )
                if self.ocr.available:
                    logger.info("OCR 消息读取已启用")
                else:
                    logger.warning("OCR 不可用，回退到剪贴板方式")
            except ImportError:
                logger.warning("ocr_reader.py 未找到，使用剪贴板方式")

    # ── 微信连接 ──────────────────────

    def connect(self) -> bool:
        """连接微信：找进程 → 找窗口 → 激活"""
        self.wechat_pid = find_wechat_process()
        if not self.wechat_pid:
            return False
        self.main_hwnd = find_wechat_window(self.wechat_pid)
        return self.main_hwnd is not None

    def is_alive(self) -> bool:
        return process_is_alive(self.wechat_pid)

    # ── 消息读取 ──────────────────────

    def read_last_message(self) -> Optional[str]:
        """剪贴板方式：选中最新消息 → Ctrl+C → 读剪贴板"""
        if not ensure_foreground(self.main_hwnd):
            return None

        rect = get_window_rect(self.main_hwnd)
        if not rect:
            return None

        click_chat_area(rect)

        if not self.is_alive():
            return None

        left, top, right, bottom = rect
        w, h = right - left, bottom - top
        chat_x = left + w // 2
        chat_y = top + int(h * 0.65)

        # 三击选中消息
        pyautogui.click(chat_x, chat_y, clicks=3, interval=0.1)
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.2)

        try:
            text = pyperclip.paste()
            if text and text != self.last_clipboard:
                self.last_clipboard = text
                return text.strip()
        except Exception:
            pass
        return None

    def read_last_message_ocr(self) -> Optional[str]:
        """OCR 方式读取最新消息"""
        if not self.ocr:
            return None
        rect = get_window_rect(self.main_hwnd)
        if not rect:
            return None
        return self.ocr.read_latest_message(rect)

    # ── 消息发送 ──────────────────────

    def send_message(self, text: str) -> bool:
        """粘贴文本到输入框并回车发送"""
        if not self.is_alive():
            logger.warning("微信已关闭，无法发送")
            return False

        rect = get_window_rect(self.main_hwnd)
        if not rect:
            return False

        click_input_area(rect)

        if not self.is_alive():
            return False

        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey('ctrl', 'v')
        # 模拟真人停顿
        time.sleep(SEND_BEFORE_ENTER_MIN_S + random.random() * (SEND_BEFORE_ENTER_MAX_S - SEND_BEFORE_ENTER_MIN_S))
        pyautogui.press('enter')

        self.reply_count += 1
        self.last_reply_text = text
        logger.info(f"已回复({self.reply_count}): {text[:40]}...")
        return True

    # ── 消息去重 ──────────────────────

    def _is_my_message(self, text: str) -> bool:
        """判断是不是自己刚发的消息（容忍 OCR 误差）"""
        if not self.last_reply_text:
            return False

        def normalize(s: str) -> str:
            return re.sub(r'[^一-鿿\w]', '', s.strip())  # noqa: F821

        import re as _re
        t = _re.sub(r'[^一-鿿\w]', '', text.strip())
        last = _re.sub(r'[^一-鿿\w]', '', self.last_reply_text.strip())
        if not t or not last:
            return False
        if t == last:
            return True
        if len(t) >= 4 and len(last) >= 4 and t[:8] == last[:8]:
            return True
        if len(last) >= 6 and last in t:
            return True
        if len(t) >= 6 and t in last:
            return True
        return False

    # ── 规则匹配 ──────────────────────

    @staticmethod
    def match_reply(text: str) -> Optional[str]:
        """关键词规则匹配"""
        text = text.strip()
        for rule in REPLY_RULES:
            for kw in rule["keywords"]:
                if rule.get("match", "contains") == "exact":
                    if text == kw:
                        return rule["reply"]
                elif kw in text:
                    return rule["reply"]
        return None

    # ── AI 回复 ───────────────────────

    def ai_reply(self, text: str) -> Optional[str]:
        """调用 AI 生成回复（带记忆上下文）"""
        if not self.ai:
            return None
        if not self.ai.available:
            return None

        context = self._memory.get_context(max_recent=6, max_facts=3)
        prompt = f"【你的记忆】\n{context}\n\n【对方刚发的消息】\n{text}" if context else text
        return self.ai.chat(prompt)

    def _save_memory(self, incoming: str, reply: str):
        self._memory.add(incoming, reply)

    # ── 消息处理流水线 ────────────────

    def process_message(self, msg: str) -> bool:
        """消息处理流水线：去重 → 规则匹配 → AI → 默认兜底 → 发送"""
        clean = msg.strip().replace(' ', '').replace('|', '').replace('.', '').replace(',', '')
        if len(clean) <= 1:
            return False

        if self._is_my_message(msg):
            return False

        logger.info(f"收到: {msg[:50]}...")

        reply = self.match_reply(msg)
        if not reply and ENABLE_AI_REPLY:
            reply = self.ai_reply(msg)
        if not reply and ENABLE_DEFAULT_REPLY:
            reply = DEFAULT_REPLY
        if not reply:
            return False

        self.send_message(reply)
        self._save_memory(msg, reply)
        if self._monitor:
            self._monitor.set_replied(msg, reply)
        return True

    # ── 实时监听回调 ──────────────────

    def _on_message_detected(self, text: str):
        self._last_detect_time = time.time()
        with self._msg_lock:
            self._msg_queue.append(text)

    # ── 主循环 ────────────────────────

    def run(self):
        """启动主循环"""
        self.running = True
        print("\n" + "=" * 50)
        print("  WeChat Auto Reply Bot v2.2")
        print("=" * 50)
        print(f"  关键词规则: {len(REPLY_RULES)} 条")
        print(f"  AI 回复: {'开' if ENABLE_AI_REPLY and self.ai else '关'}")
        print(f"  默认回复: {'开' if ENABLE_DEFAULT_REPLY else '关'}")
        print(f"  监听模式: {'实时差分检测' if HAS_REALTIME else '定时轮询'}")
        print(f"  存储引擎: SQLite")
        print("=" * 50)
        print("  1. 微信中打开你要回复的聊天窗口")
        print("  2. Ctrl+C 停止")
        print()

        # ── 启动实时监听器 ──
        if HAS_REALTIME:
            self._monitor = RealtimeChatMonitor(
                get_window_rect=lambda: get_window_rect(self.main_hwnd),
                on_new_message=self._on_message_detected,
                ocr_engine=OCR_ENGINE, bottom_ratio=OCR_BOTTOM_RATIO,
                left_ratio=CHAT_LEFT_RATIO, right_ratio=CHAT_RIGHT_RATIO,
                top_ratio=CHAT_TOP_RATIO, bottom_offset_ratio=CHAT_BOTTOM_RATIO,
                debug=OCR_DEBUG,
            )
            self._monitor.start()
            logger.info("实时监听已启动（屏幕差分 + OCR）")
        else:
            logger.info("定时轮询模式启动")

        # ── 主循环 ──
        try:
            while self.running:
                if not self.is_alive():
                    logger.warning("微信进程不在，等待恢复...")
                    time.sleep(PROCESS_DEAD_CHECK_S)
                    self.connect()
                    continue

                if HAS_REALTIME and self._monitor:
                    msgs = []
                    with self._msg_lock:
                        if self._msg_queue:
                            msgs = self._msg_queue[:]
                            self._msg_queue.clear()
                    for msg in msgs:
                        if not self.is_alive():
                            break
                        try:
                            self.process_message(msg)
                        except Exception as e:
                            logger.warning(f"处理消息异常: {e}")
                    time.sleep(0.1)
                else:
                    self._poll_once()
                    time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            self.running = False
            if self._monitor:
                self._monitor.stop()
            self._memory.close()
            logger.info(f"已停止，共回复 {self.reply_count} 条")

    def _poll_once(self):
        """单次轮询"""
        msg = None
        if self.ocr and self.ocr.available:
            msg = self.read_last_message_ocr()
        else:
            msg = self.read_last_message()
        if msg:
            self.process_message(msg)

    # ── 一次性模式 ────────────────────

    def once(self) -> bool:
        """单次回复当前窗口消息"""
        if not self.connect():
            return False
        ensure_foreground(self.main_hwnd)
        return self._poll_once()

    def send(self, msg: str) -> bool:
        """发送指定消息"""
        if not self.connect():
            return False
        ensure_foreground(self.main_hwnd)
        return self.send_message(msg)


# ============================================================
# 剪贴板快速回复（独立于主程序）
# ============================================================
class SimpleWeChatReply:
    """复制消息 → 运行脚本 → 自动回复"""

    def __init__(self):
        self.ai = create_ai_client_from_config() if ENABLE_AI_REPLY else None
        self.last_reply_text = ""

    def reply_from_clipboard(self) -> bool:
        try:
            text = pyperclip.paste().strip()
        except Exception:
            print("无法读取剪贴板")
            return False

        if not text:
            print("剪贴板为空，请先在微信中 Ctrl+C 复制对方消息")
            return False

        print(f"剪贴板消息: {text[:60]}...")

        if self.last_reply_text and (text.strip() == self.last_reply_text.strip()
                                      or text.strip()[:15] == self.last_reply_text.strip()[:15]):
            print("跳过（自己发的）")
            return False

        reply = None
        for rule in REPLY_RULES:
            for kw in rule["keywords"]:
                if rule.get("match", "contains") == "exact":
                    if text == kw:
                        reply = rule["reply"]
                        break
                elif kw in text:
                    reply = rule["reply"]
                    break
            if reply:
                break

        if not reply and ENABLE_AI_REPLY and self.ai and self.ai.available:
            print("调用 AI...")
            reply = self.ai.chat(text)

        if not reply and ENABLE_DEFAULT_REPLY:
            reply = DEFAULT_REPLY

        if not reply:
            print("未匹配规则，AI 未开启或调用失败")
            return False

        pyperclip.copy(reply)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        pyautogui.press('enter')
        self.last_reply_text = reply
        print(f"已回复: {reply[:50]}...")
        return True


# ============================================================
# CLI 入口
# ============================================================
def main():
    if len(sys.argv) > 1:
        if sys.argv[1] in ("--help", "-h"):
            print("用法:")
            print("  python wechat_bot.py              启动自动回复循环")
            print("  python wechat_bot.py --once       单次检测并回复")
            print("  python wechat_bot.py --msg MSG    发送消息到当前窗口")
            print("  python wechat_bot.py --clip       从剪贴板读消息并回复")
            return
        if sys.argv[1] == "--clip":
            SimpleWeChatReply().reply_from_clipboard()
            return
        if sys.argv[1] == "--once":
            bot = WeChatBot()
            if bot.connect():
                bot.once()
            return
        if sys.argv[1] == "--msg" and len(sys.argv) > 2:
            bot = WeChatBot()
            if bot.connect():
                bot.send(sys.argv[2])
            return

    bot = WeChatBot()
    while not bot.connect():
        print(f"[等待中] 请打开微信并登录，{WINDOW_RETRY_S}秒后重试...")
        time.sleep(WINDOW_RETRY_S)
    print("微信已连接，开始监听...")
    bot.run()


if __name__ == "__main__":
    main()
