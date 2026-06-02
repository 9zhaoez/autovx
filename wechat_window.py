# -*- coding: utf-8 -*-
"""
微信窗口管理模块 — 进程发现、窗口定位、截图区域计算

特性:
  - 集中管理所有 timing 常量，方便全局调优
  - 进程/窗口自动发现 + 重试
  - 跨进程枚举（微信 4.x 多进程架构）
  - DPI 感知的物理坐标计算
"""

import time
import logging
from typing import Optional, Tuple

import psutil
import pyautogui
import win32gui
import win32con
import win32process

logger = logging.getLogger("WeChatWindow")

# ── Timing 常量（集中管理）──────────────────────────
CLICK_SETTLE_MS = 0.30       # 点击后等待界面响应
FOCUS_RESTORE_MS = 0.30     # 最小化窗口恢复等待
PASTE_DELAY_MIN_MS = 0.05   # Ctrl+V 前等待
SEND_BEFORE_ENTER_MIN_S = 0.8  # 发送前最小停顿
SEND_BEFORE_ENTER_MAX_S = 1.2  # 发送前最大停顿（随机）
WINDOW_RETRY_S = 3.0        # 找不到窗口时重试间隔
PROCESS_DEAD_CHECK_S = 5.0  # 进程失活检查间隔

WECHAT_PROCESS_NAMES = ["Weixin.exe", "WeChat.exe", "WeChatAppEx.exe"]
WECHAT_WINDOW_CLASSES = ["Qt51514QWindowIcon", "WeChatMainWndForPC"]


def find_wechat_process() -> Optional[int]:
    """查找微信进程 PID"""
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = str(proc.info.get("name", ""))
            if any(n.lower() == name.lower() for n in WECHAT_PROCESS_NAMES):
                pid = proc.info["pid"]
                logger.info(f"找到微信进程: {name} (PID: {pid})")
                return pid
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def find_wechat_window(pid: Optional[int] = None) -> Optional[int]:
    """查找微信主窗口句柄

    优先匹配 PID + 类名，回退到仅类名匹配（跨进程场景）。
    """
    if pid is None:
        pid = find_wechat_process()
    if pid is None:
        logger.warning("未找到微信进程，请启动并登录微信")
        return None

    windows = []

    def enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
        cls = win32gui.GetClassName(hwnd)
        title = win32gui.GetWindowText(hwnd)
        windows.append({"hwnd": hwnd, "pid": win_pid, "class": cls, "title": title})

    win32gui.EnumWindows(enum_cb, None)

    # 优先同进程
    pid_windows = [w for w in windows if w["pid"] == pid]
    if not pid_windows:
        pid_windows = [w for w in windows if any(c in w["class"] for c in WECHAT_WINDOW_CLASSES)]

    if not pid_windows:
        logger.warning("未找到微信窗口，请确保微信已登录且窗口可见")
        return None

    # 优先匹配已知类名
    for cls in WECHAT_WINDOW_CLASSES:
        for w in pid_windows:
            if cls in w["class"]:
                logger.info(f"找到微信窗口: {w['title'][:30]}")
                return w["hwnd"]

    # 回退：取面积最大的
    best = max(pid_windows,
               key=lambda w: win32gui.GetWindowRect(w["hwnd"])[2] * win32gui.GetWindowRect(w["hwnd"])[3])
    return best["hwnd"]


def get_window_rect(hwnd: Optional[int]) -> Optional[Tuple[int, int, int, int]]:
    """获取窗口物理坐标 (left, top, right, bottom)"""
    if hwnd is None:
        return None
    try:
        return win32gui.GetWindowRect(hwnd)
    except Exception:
        return None


def process_is_alive(pid: Optional[int]) -> bool:
    """检查进程是否仍在运行"""
    if pid is None:
        return False
    try:
        psutil.Process(pid)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def ensure_foreground(hwnd: Optional[int]) -> bool:
    """温和地将微信窗口恢复到前台（不强制抢占焦点）"""
    if hwnd is None:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(FOCUS_RESTORE_MS)
        return True
    except Exception:
        return False


def click_chat_area(rect: Tuple[int, int, int, int]) -> None:
    """点击聊天区中央，确保焦点在消息区域"""
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    chat_x = left + w // 2
    chat_y = top + int(h * 0.65)
    pyautogui.moveTo(chat_x, chat_y, duration=0.2)
    time.sleep(0.1)
    pyautogui.click(chat_x, chat_y)
    time.sleep(CLICK_SETTLE_MS)


def click_input_area(rect: Tuple[int, int, int, int]) -> None:
    """点击输入框区域"""
    left, top, right, bottom = rect
    w = right - left
    input_x = left + w // 2
    input_y = bottom - 30
    pyautogui.moveTo(input_x, input_y, duration=0.2)
    time.sleep(0.1)
    pyautogui.click(input_x, input_y)
    time.sleep(CLICK_SETTLE_MS)
