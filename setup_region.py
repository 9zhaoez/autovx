# -*- coding: utf-8 -*-
"""
手动框选消息检测区域 — 一次性设置 (tkinter 版)
运行后在微信窗口上拖拽框出聊天消息区，坐标自动保存到 config.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import win32gui
import numpy as np
import os
import tkinter as tk
from PIL import Image, ImageTk

# ── 找微信窗口 ──
hwnd = None

def cb(h, _):
    global hwnd
    if win32gui.IsWindowVisible(h) and 'Qt51514QWindowIcon' in win32gui.GetClassName(h):
        hwnd = h

win32gui.EnumWindows(cb, None)

if not hwnd:
    def cb2(h, _):
        global hwnd
        if win32gui.IsWindowVisible(h) and '微信' in win32gui.GetWindowText(h):
            hwnd = h
    win32gui.EnumWindows(cb2, None)

if not hwnd:
    print("❌ 未找到微信窗口！请确保微信已打开且可见")
    input("按回车退出...")
    sys.exit(1)

rect = win32gui.GetWindowRect(hwnd)
left, top, right, bottom = rect
w, h = right - left, bottom - top
print(f"微信窗口: ({left},{top}) {w}x{h}")

# ── 截图 ──
try:
    import mss
    try:
        sct = mss.MSS()
    except AttributeError:
        sct = mss.mss()
    monitor = {"left": left, "top": top, "width": w, "height": h}
    img_bgr = np.array(sct.grab(monitor))[:, :, :3]
except ImportError:
    import pyautogui
    img_bgr = np.array(pyautogui.screenshot(region=(left, top, w, h)))[:, :, ::-1]

# BGR → RGB for PIL
img_rgb = img_bgr[:, :, ::-1]
pil_img = Image.fromarray(img_rgb)

# ── tkinter 窗口 ──
root = tk.Tk()
root.title("框选聊天消息区 — 按住左键拖拽，Enter 保存")

# 尽量占满屏幕，方便看清微信窗口细节进行框选
screen_w = root.winfo_screenwidth()
screen_h = root.winfo_screenheight()
scale = min(1.0, (screen_w - 40) / w, (screen_h - 100) / h)
display_w = int(w * scale)
display_h = int(h * scale)

if scale < 1.0:
    pil_img = pil_img.resize((display_w, display_h), Image.LANCZOS)

photo = ImageTk.PhotoImage(pil_img)
canvas = tk.Canvas(root, width=display_w, height=display_h, cursor="cross")
canvas.pack()

# 在 canvas 上创建背景图
canvas.create_image(0, 0, anchor=tk.NW, image=photo)

# 状态栏
status = tk.Label(root, text="按住左键拖拽框出聊天消息区 → 按 Enter 保存 → 按 R 重置", fg="white", bg="#333", font=("微软雅黑", 11))
status.pack(fill=tk.X)

# ── 框选逻辑 ──
roi = None
start_x = start_y = 0
rect_id = None

def on_mouse_down(event):
    global start_x, start_y
    start_x, start_y = event.x, event.y
    canvas.delete("roi_rect")

def on_mouse_drag(event):
    global rect_id
    canvas.delete("roi_rect")
    rect_id = canvas.create_rectangle(
        start_x, start_y, event.x, event.y,
        outline="#00FF00", width=2, tags="roi_rect"
    )

def on_mouse_up(event):
    global roi
    x1, y1 = start_x, start_y
    x2, y2 = event.x, event.y
    if abs(x2 - x1) < 10 and abs(y2 - y1) < 10:
        status.config(text="⚠️ 框选太小！请重新按住左键拖出一个大方框，覆盖整个聊天消息区")
        return
    x1_raw = int(x1 / scale)
    y1_raw = int(y1 / scale)
    x2_raw = int(x2 / scale)
    y2_raw = int(y2 / scale)
    roi = (
        min(x1_raw, x2_raw),
        min(y1_raw, y2_raw),
        abs(x2_raw - x1_raw),
        abs(y2_raw - y1_raw),
    )
    # 检查选框是否够大（至少 150×100 像素）
    if roi[2] < 150 or roi[3] < 100:
        status.config(text=f"⚠️ 选框太小 ({roi[2]}x{roi[3]}px)，请拖大一些覆盖整个消息区！")
        roi = None
        return
    canvas.delete("roi_rect")
    canvas.create_rectangle(x1, y1, x2, y2, outline="#00FF00", width=2, tags="roi_rect")
    status.config(text=f"✅ 已框选: {roi[2]}x{roi[3]}px → 按 Enter 保存")

def on_key(event):
    global roi
    if event.keysym == "Return":
        if roi is None:
            status.config(text="⚠️ 请先框选区域再按 Enter！")
            return
        root.quit()
    elif event.keysym.lower() == "r":
        roi = None
        canvas.delete("roi_rect")
        status.config(text="已重置，请重新框选")

canvas.bind("<ButtonPress-1>", on_mouse_down)
canvas.bind("<B1-Motion>", on_mouse_drag)
canvas.bind("<ButtonRelease-1>", on_mouse_up)
root.bind("<Key>", on_key)

# 提示标签
hint = tk.Label(
    root,
    text="🟢 按住左键拖拽框出聊天消息显示区\n⚠️ 不要包含左侧联系人栏和底部输入框\n按 Enter 保存 | 按 R 重新框选",
    fg="#aaa", bg="#222", font=("微软雅黑", 10), justify=tk.LEFT
)
hint.pack(fill=tk.X)

root.mainloop()

if roi is None:
    print("❌ 未框选，退出")
    sys.exit(0)

rx, ry, rw, rh = roi

# ── 计算相对于窗口的比值 ──
left_ratio = rx / w
right_ratio = (w - rx - rw) / w
bottom_ratio = rh / (h * 0.73)

print()
print(f"框选区域（相对值）:")
print(f"  左边距比例: {left_ratio:.4f}")
print(f"  右边距比例: {right_ratio:.4f}")
print(f"  区域高度占聊天区比例: {bottom_ratio:.4f}")

# ── 写入 config.py ──
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
with open(config_path, "r", encoding="utf-8") as f:
    content = f.read()

import re
content = re.sub(r'CHAT_LEFT_RATIO = [\d.]+', f'CHAT_LEFT_RATIO = {left_ratio:.4f}', content)
content = re.sub(r'CHAT_RIGHT_RATIO = [\d.]+', f'CHAT_RIGHT_RATIO = {right_ratio:.4f}', content)
content = re.sub(r'OCR_BOTTOM_RATIO = [\d.]+', f'OCR_BOTTOM_RATIO = {bottom_ratio:.4f}', content)

with open(config_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"\n✅ 已保存到 config.py!")
print(f"   CHAT_LEFT_RATIO = {left_ratio:.4f}")
print(f"   CHAT_RIGHT_RATIO = {right_ratio:.4f}")
print(f"   OCR_BOTTOM_RATIO = {bottom_ratio:.4f}")
print()
print("现在可以运行 启动自动回复.bat 了")
input("按回车退出...")
