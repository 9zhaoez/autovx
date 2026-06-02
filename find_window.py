# -*- coding: utf-8 -*-
"""查找所有微信相关窗口，不管是否可见"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import psutil
import win32gui
import win32process

WECHAT_PROCS = ["Weixin.exe", "WeChat.exe", "WeChatAppEx.exe"]

# 找微信进程
wechat_pid = None
for proc in psutil.process_iter(["pid", "name"]):
    try:
        name = str(proc.info.get("name", ""))
        if any(n.lower() == name.lower() for n in WECHAT_PROCS):
            wechat_pid = proc.info["pid"]
            print(f"微信进程: {name} PID={wechat_pid}")
            break
    except:
        continue

if not wechat_pid:
    print("未找到微信进程！")
    sys.exit(1)

# 枚举该进程所有窗口
print(f"\nPID={wechat_pid} 的所有窗口（含不可见）：")
print(f"{'可见':<6} {'标题':<40} {'类名':<40} {'尺寸':<15} {'句柄':<12}")
print("-" * 120)

windows = []

def enum_all(hwnd, _):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except:
        return
    if pid != wechat_pid:
        return
    try:
        cls = win32gui.GetClassName(hwnd)
        title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        visible = win32gui.IsWindowVisible(hwnd)
        iconic = win32gui.IsIconic(hwnd)

        windows.append({
            "hwnd": hwnd, "visible": visible, "iconic": iconic,
            "title": title, "class": cls, "w": w, "h": h
        })

        status = "可见" if visible else "隐藏"
        if iconic:
            status = "最小化"
        print(f"{status:<6} {title[:38]:<40} {cls[:38]:<40} {w}x{h:<10} {hwnd}")
    except Exception as e:
        print(f"ERROR: {e}")

win32gui.EnumWindows(enum_all, None)

# 找最可能是主窗口的
print("\n--- 分析 ---")
large_windows = [w for w in windows if w["w"] > 200 and w["h"] > 200]
if large_windows:
    print(f"大尺寸窗口({'>200px'}): {len(large_windows)} 个")
    for w in large_windows:
        print(f"  hwnd={w['hwnd']} 可见={w['visible']} 最小化={w['iconic']} {w['w']}x{w['h']} class={w['class']} title={w['title'][:30]}")
else:
    print("没有大尺寸窗口（可能全在托盘）")

if not any(w["visible"] and w["w"] > 100 for w in windows):
    print("\n⚠️  微信没有可见的大窗口，可能在系统托盘！")
    print("  请双击任务栏微信图标，让它显示出来。")
